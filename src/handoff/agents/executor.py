# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Running a workflow, pausing it on a human decision, and picking it back up.

The interesting property here is that a paused run is not a special state
machine Handoff maintains — it is a Strands Graph with its state serialised.
``start()`` returns when the graph either finishes or raises interrupts;
``resume()`` rehydrates the same graph and feeds the human's answers back into
the tool call that was waiting for them. The agent's reasoning context survives
the gap, however long it is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from handoff import config, events
from handoff.graph.factory import build_workflow_graph
from handoff.graph.hooks.hitl import BATCH_INTERRUPT, HITLGate
from handoff.models import (
    AuditEntry,
    DecidedBy,
    InterruptPayload,
    RunStatus,
    TriggerType,
    UserDecision,
    WorkflowConfig,
    WorkflowRun,
)
from handoff.runtime import RunContext, run_context
from handoff.store import get_store
from handoff.tools.notify import notify_batch


class RunOutcome(dict):
    """Result of starting or resuming a run — plain dict for easy JSON return."""

    @property
    def waiting(self) -> bool:
        return bool(self.get("status") == RunStatus.WAITING_ON_HUMAN.value)


def _task_prompt(workflow: WorkflowConfig, trigger_type: str) -> str:
    """The instruction handed to the graph's entry node."""
    threshold = workflow.confidence_threshold or config.CONFIDENCE_THRESHOLD
    return (
        f"Run the workflow '{workflow.name}'.\n"
        f"Description: {workflow.description}\n"
        f"Trigger: {trigger_type}\n"
        f"Preference key: {workflow.memory.preference_key}\n"
        f"Confidence threshold: {threshold} — below this, escalate to the human "
        f"instead of acting.\n"
        f"Available integrations: {', '.join(workflow.mcp_tools) or 'built-in only'}"
    )


class WorkflowRunner:
    """Owns one workflow's execution lifecycle."""

    def __init__(self, workflow: WorkflowConfig, model: Any = None) -> None:
        self.workflow = workflow
        self.model = model if model is not None else config.get_model()
        self.store = get_store()

    # -- gate callbacks ----------------------------------------------------

    def _make_gate(self, run: WorkflowRun) -> HITLGate:
        def on_interrupt(payload: InterruptPayload) -> None:
            payload.run_id = run.run_id
            payload.workflow_id = self.workflow.workflow_id
            self.store.save_interrupt(payload)
            if payload.interrupt_id not in run.pending_interrupt_ids:
                run.pending_interrupt_ids.append(payload.interrupt_id)

        def on_decision(payload: InterruptPayload, decision: UserDecision) -> None:
            self.store.save_interrupt(payload)
            self.store.write_audit(
                AuditEntry(
                    run_id=run.run_id,
                    workflow_id=self.workflow.workflow_id,
                    action=decision.chosen_action,
                    item_id=payload.item.item_id,
                    decision_by=DecidedBy.HUMAN,
                    confidence=payload.agent_analysis.confidence,
                    details={
                        "summary": payload.item.summary,
                        "note": decision.user_note,
                        "agent_suggested": payload.agent_analysis.suggested_action,
                        "reason": payload.reason,
                    },
                )
            )

        return HITLGate(
            run_id=run.run_id,
            workflow_id=self.workflow.workflow_id,
            threshold=self.workflow.confidence_threshold or config.CONFIDENCE_THRESHOLD,
            on_interrupt=on_interrupt,
            on_decision=on_decision,
            batch=True,
        )

    # -- start -------------------------------------------------------------

    def start(self, trigger_type: str = "manual", payload: dict | None = None) -> RunOutcome:
        """Start a run. Returns once it completes or stops for a human."""
        run = WorkflowRun(
            workflow_id=self.workflow.workflow_id,
            trigger_type=TriggerType(trigger_type)
            if trigger_type in {t.value for t in TriggerType}
            else TriggerType.MANUAL,
        )
        return self._start_existing(run, trigger_type, payload)

    def _start_existing(
        self, run: WorkflowRun, trigger_type: str = "manual", payload: dict | None = None
    ) -> RunOutcome:
        """Start a run whose record already exists (the UI pre-creates one so
        it can hand back a run id before the model has said a word)."""
        self.store.save_run(run)
        events.emit(
            run.run_id, "started",
            f"Starting {self.workflow.name} ({trigger_type}) on {config.active_model_id()}",
            workflow_id=self.workflow.workflow_id,
        )

        gate = self._make_gate(run)
        graph = build_workflow_graph(self.workflow, self.model, gate)
        ctx = RunContext(
            run_id=run.run_id, workflow_id=self.workflow.workflow_id, workflow=self.workflow
        )

        task = _task_prompt(self.workflow, trigger_type)
        if payload:
            task += f"\nSignal payload: {payload}"

        try:
            with run_context(ctx):
                result = graph(task)
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.finished_at = datetime.now(UTC)
            run.summary = f"Failed: {str(exc)[:300]}"
            self.store.save_run(run)
            events.emit(run.run_id, "failed", run.summary)
            raise

        return self._settle(run, graph, ctx, gate, result)

    # -- resume ------------------------------------------------------------

    def resume(self, run: WorkflowRun, decisions: list[UserDecision]) -> RunOutcome:
        """Feed human decisions back into a paused run and let it finish."""
        if not run.graph_state:
            raise ValueError(f"Run {run.run_id} has no saved graph state to resume")

        gate = self._make_gate(run)
        graph = build_workflow_graph(self.workflow, self.model, gate)
        graph.deserialize_state(run.graph_state)

        ctx = RunContext(
            run_id=run.run_id, workflow_id=self.workflow.workflow_id, workflow=self.workflow
        )

        raised = self.store.interrupts_for_run(run.run_id)
        batch = [p for p in raised if p.batch]
        if batch:
            # One interrupt for many items: it can only be answered once every
            # item has a decision. Until then, record what we have and wait.
            unresolved = [p for p in batch if not p.resolved]
            if unresolved:
                outcome = self._describe(run, resumed=False)
                outcome["status"] = RunStatus.WAITING_ON_HUMAN.value
                outcome["pending_interrupts"] = [p.model_dump(mode="json") for p in unresolved]
                return outcome

            for payload in batch:
                gate.payloads[payload.interrupt_name] = payload
                ctx.defer(payload.item.item_id, payload)

            responses = [
                {
                    "interruptResponse": {
                        "interruptId": batch[0].strands_interrupt_id,
                        "response": {
                            p.item.item_id: {
                                "action": p.decision.chosen_action if p.decision else "skip",
                                "note": p.decision.user_note if p.decision else "",
                            }
                            for p in batch
                        },
                    }
                }
            ]
            events.emit(run.run_id, "resumed", f"Resuming with your {len(batch)} decision(s)")
            with run_context(ctx):
                result = graph(responses)
            return self._settle(run, graph, ctx, gate, result, resumed=True)

        # Pre-seed the gate with every interrupt this run has already raised —
        # not just the ones being answered now. Replaying the graph re-executes
        # the gated tool calls, and a gate that doesn't recognise them would
        # mint fresh interrupt ids, orphaning the decision links the UI holds
        # and re-notifying the user about questions they have already seen.
        for existing in self.store.interrupts_for_run(run.run_id):
            if existing.interrupt_name and not existing.resolved:
                gate.payloads[existing.interrupt_name] = existing

        responses: list[dict[str, Any]] = []
        for decision in decisions:
            payload = self.store.get_interrupt(decision.interrupt_id)
            if payload is None or not payload.strands_interrupt_id:
                continue
            if payload.interrupt_name:
                gate.payloads[payload.interrupt_name] = payload
            responses.append(
                {
                    "interruptResponse": {
                        "interruptId": payload.strands_interrupt_id,
                        "response": {
                            "action": decision.chosen_action,
                            "note": decision.user_note,
                        },
                    }
                }
            )

        if not responses:
            raise ValueError("None of those decisions match a pending interrupt on this run")

        with run_context(ctx):
            result = graph(responses)

        return self._settle(run, graph, ctx, gate, result, resumed=True)

    def _describe(self, run: WorkflowRun, resumed: bool) -> RunOutcome:
        """Outcome dict for a run whose state hasn't changed."""
        return RunOutcome(
            run_id=run.run_id,
            workflow_id=self.workflow.workflow_id,
            status=run.status.value,
            resumed=resumed,
            auto_count=run.auto_count,
            human_count=run.interrupt_count,
            memory_count=run.memory_count,
            pending_interrupts=[],
            summary=run.summary,
        )

    # -- shared tail -------------------------------------------------------

    def _settle(
        self,
        run: WorkflowRun,
        graph: Any,
        ctx: RunContext,
        gate: HITLGate,
        result: Any,
        resumed: bool = False,
    ) -> RunOutcome:
        """Persist whatever just happened and describe it to the caller."""
        interrupts = list(getattr(result, "interrupts", []) or [])

        # Link each Strands interrupt back to the payload(s) the gate raised, so
        # the decision screen can resume the right tool call later. A batch
        # interrupt maps to every deferred payload at once.
        pending_ids: list[str] = []
        fresh: list[InterruptPayload] = []
        for interrupt in interrupts:
            name = getattr(interrupt, "name", "")
            sid = getattr(interrupt, "id", "")
            if name == BATCH_INTERRUPT:
                targets = [p for p in ctx.deferred.values()]
            else:
                targets = [p for p in [gate.payloads.get(name)] if p is not None]
            for payload in targets:
                payload.strands_interrupt_id = sid
                payload.run_id = run.run_id
                payload.workflow_id = self.workflow.workflow_id
                self.store.save_interrupt(payload)
                pending_ids.append(payload.interrupt_id)
                if not payload.resolved:
                    fresh.append(payload)

        if fresh:
            notify_batch(fresh)

        # Derive the counts from what was persisted rather than accumulating
        # them per invocation. Resuming replays already-executed tool calls, so
        # anything additive would double-count every time a human answers one
        # of several pending decisions.
        raised = self.store.interrupts_for_run(run.run_id)
        audit = self.store.list_audit(run.run_id, limit=1000)
        run.auto_count = sum(
            1
            for e in audit
            if e.decision_by is DecidedBy.AGENT and e.action != "run_completed"
        )
        run.interrupt_count = sum(1 for i in raised if i.resolved)
        run.memory_count = sum(
            1 for e in audit if e.decision_by is DecidedBy.MEMORY
        )
        run.pending_interrupt_ids = pending_ids

        if interrupts:
            run.status = RunStatus.WAITING_ON_HUMAN
            run.graph_state = graph.serialize_state()
            n = len(pending_ids) or len(interrupts)
            run.summary = f"Paused on {n} decision{'s' if n != 1 else ''} that need you."
            events.emit(
                run.run_id, "asked", f"Set aside {n} item{'s' if n != 1 else ''} for you",
                pending=[p for p in pending_ids],
            )
        else:
            run.status = RunStatus.COMPLETED
            run.finished_at = datetime.now(UTC)
            run.graph_state = None
            run.summary = ctx.notes[-1] if ctx.notes else str(result)[:500]
            events.emit(
                run.run_id, "completed",
                f"Done — {run.auto_count} handled alone, {run.interrupt_count} decided by you, "
                f"{run.memory_count} from your rules",
                auto=run.auto_count, human=run.interrupt_count, memory=run.memory_count,
            )

        self.store.save_run(run)

        return RunOutcome(
            run_id=run.run_id,
            workflow_id=self.workflow.workflow_id,
            status=run.status.value,
            resumed=resumed,
            auto_count=run.auto_count,
            human_count=run.interrupt_count,
            memory_count=run.memory_count,
            pending_interrupts=[
                (self.store.get_interrupt(i) or InterruptPayload()).model_dump(mode="json")
                for i in pending_ids
            ],
            summary=run.summary,
        )


# --- module-level conveniences ---------------------------------------------


def run_workflow(
    workflow_id: str, trigger_type: str = "manual", payload: dict | None = None, model: Any = None
) -> RunOutcome:
    """Look up a workflow by id and run it."""
    workflow = get_store().get_workflow(workflow_id)
    if workflow is None:
        raise KeyError(f"No workflow with id '{workflow_id}'")
    return WorkflowRunner(workflow, model).start(trigger_type, payload)


def submit_decision(
    interrupt_id: str, action: str, note: str = "", model: Any = None
) -> RunOutcome:
    """Apply one human decision and resume the run it belongs to.

    Also wakes the Learning Agent, so the next run doesn't ask again.
    """
    store = get_store()
    payload = store.get_interrupt(interrupt_id)
    if payload is None:
        raise KeyError(f"No pending decision with id '{interrupt_id}'")

    run = store.get_run(payload.run_id)
    if run is None:
        raise KeyError(f"Decision '{interrupt_id}' has no run to resume")

    workflow = store.get_workflow(run.workflow_id)
    if workflow is None:
        raise KeyError(f"Run '{run.run_id}' references a workflow that no longer exists")

    decision = UserDecision(interrupt_id=interrupt_id, chosen_action=action, user_note=note)
    payload.decision = decision
    payload.resolved = True
    store.save_interrupt(payload)

    outcome = WorkflowRunner(workflow, model).resume(run, [decision])

    if workflow.memory.learn_from_decisions:
        from handoff.agents.learner import learn_from_decision

        try:
            outcome["learned"] = learn_from_decision(
                payload, decision, preference_key=workflow.memory.preference_key, model=model
            )
        except Exception as exc:
            outcome["learned"] = {"stored": False, "error": str(exc)}

    return outcome
