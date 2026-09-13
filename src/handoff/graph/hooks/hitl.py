# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The human-in-the-loop decision gate.

This is the centre of Handoff. The hackathon brief asks for an agent that
"runs autonomously and only surfaces when there's a real decision to make" —
this module is that sentence expressed as code.

How it works, against the real Strands interrupt API (v1.55):

    1. The executor agent calls ``submit_action`` for every item it processed.
    2. ``BeforeToolCallEvent`` fires *before* the tool body runs.
    3. This hook decides whether the call is clear-cut or genuinely ambiguous.
    4. Clear-cut  -> the hook returns, the tool runs, nobody is disturbed.
       Ambiguous  -> ``event.interrupt(...)`` raises ``InterruptException``,
                     which unwinds the agent loop. The run stops with
                     ``stop_reason == "interrupt"`` and the pending interrupt
                     is handed back to the caller.
    5. The caller shows the payload to a human, collects an answer, and
       re-invokes the agent with ``[{"interruptResponse": {...}}]``.
    6. Strands replays the tool call. ``event.interrupt()`` is reached a second
       time — but now it *returns* the human's answer instead of raising.
    7. The hook rewrites the tool input to match what the human chose (or
       cancels the tool outright if they said "skip"), and execution continues.

Note the shape of step 6: the gate is not a fork in the graph, it is a
suspension of one tool call. The agent's reasoning context survives intact
across the human's coffee break.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from handoff import config
from handoff.models import (
    AgentAnalysis,
    InterruptItem,
    InterruptPayload,
    UserDecision,
)

#: Tools whose effects a human must always sign off on, no matter how sure the
#: model is. Confidence is not the right control for "irreversible".
ALWAYS_GATED: set[str] = {
    "delete_item",
    "send_message",
    "send_email",
    "post_public_message",
}

#: Tools that are gated *conditionally* — only when the agent itself is unsure.
CONDITIONALLY_GATED: set[str] = {
    "submit_action",
    "create_ticket",
    "draft_reply",
}

#: Actions that mean "do nothing" and therefore cancel the underlying tool call.
NO_OP_ACTIONS: set[str] = {"skip", "ignore", "none", "do_nothing"}

#: The tool the executor calls once its pass is complete. In batch mode this
#: is where the single interrupt for every deferred item is raised.
BATCH_TOOL = "finish_batch"
BATCH_INTERRUPT = "handoff_batch"


class InterruptDecision:
    """Why (or why not) a given tool call is being gated."""

    __slots__ = ("gated", "reason")

    def __init__(self, gated: bool, reason: str = "") -> None:
        self.gated = gated
        self.reason = reason

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.gated


def apply_learned_rules(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """If the user already answered this question once, answer it for them.

    Runs before the gate decides. A matching preference rewrites the call to
    the action the user chose last time, at the confidence they gave it, and
    stamps ``applied_preference`` so the audit trail attributes it to memory
    rather than to the model. This is the whole point of the learning loop,
    and putting it here — not in a separate classify step — means the model
    needs one tool call per item, not two.
    """
    if tool_name not in CONDITIONALLY_GATED:
        return tool_input

    from handoff.memory.store import find_matching_preference
    from handoff.runtime import current_run

    ctx = current_run()
    item_id = str(tool_input.get("item_id", ""))
    known = ctx.item(item_id) if ctx is not None else {}
    sender = str(tool_input.get("sender") or known.get("sender", ""))
    subject = str(tool_input.get("subject") or known.get("subject", ""))
    snippet = str(tool_input.get("snippet") or known.get("snippet", ""))
    if not (sender or subject):
        return tool_input

    key = ctx.workflow.memory.preference_key if ctx is not None and ctx.workflow else None
    preference = find_matching_preference(
        sender=sender, subject=subject, snippet=snippet, preference_key=key
    )
    if preference is None:
        return tool_input

    updated = dict(tool_input)
    updated["action"] = preference.action
    updated["confidence"] = max(float(tool_input.get("confidence", 0) or 0), preference.confidence)
    updated["force_interrupt"] = False
    updated["applied_preference"] = preference.preference_id
    updated["reasoning"] = (
        f"{tool_input.get('reasoning', '')} (Applying a rule you set earlier: "
        f"{preference.pattern})"
    ).strip()
    return updated


def evaluate_gate(
    tool_name: str,
    tool_input: dict[str, Any],
    threshold: float | None = None,
) -> InterruptDecision:
    """Pure decision function: should this tool call stop for a human?

    Separated from the hook so it can be unit-tested without constructing an
    agent, a model, or an event loop.
    """
    threshold = config.CONFIDENCE_THRESHOLD if threshold is None else threshold

    if tool_name in ALWAYS_GATED:
        return InterruptDecision(
            True, f"'{tool_name}' is irreversible and always requires human approval"
        )

    if tool_name not in CONDITIONALLY_GATED:
        return InterruptDecision(False)

    if tool_input.get("force_interrupt", False):
        return InterruptDecision(
            True, "The agent flagged this item as needing human judgement"
        )

    try:
        confidence = float(tool_input.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 0.0

    if confidence < threshold:
        return InterruptDecision(
            True,
            f"Confidence ({confidence:.0%}) is below the {threshold:.0%} threshold",
        )

    return InterruptDecision(False)


def build_payload(
    tool_name: str,
    tool_input: dict[str, Any],
    reason: str,
    *,
    run_id: str = "",
    workflow_id: str = "",
    interrupt_name: str = "",
) -> InterruptPayload:
    """Assemble the one-screen decision payload from a gated tool call.

    The model passes an id and a judgement; the sender, subject and preview
    come from what the run fetched. Falls back to whatever the tool input
    carries, so a gate outside a run context still produces a usable screen.
    """
    from handoff.runtime import current_run

    item_id = str(tool_input.get("item_id", ""))
    ctx = current_run()
    known = ctx.item(item_id) if ctx is not None else {}
    sender = str(tool_input.get("sender") or known.get("sender", ""))
    subject = str(tool_input.get("subject") or known.get("subject", ""))
    snippet = str(tool_input.get("snippet") or known.get("snippet", ""))
    summary = str(tool_input.get("summary") or "") or (
        f"{subject} — from {known.get('sender_name') or sender}" if subject else ""
    )
    return InterruptPayload(
        run_id=run_id,
        workflow_id=workflow_id,
        interrupt_name=interrupt_name,
        tool=tool_name,
        reason=reason,
        item=InterruptItem(
            item_id=item_id,
            summary=summary or subject,
            sender=sender,
            subject=subject,
            snippet=snippet,
        ),
        agent_analysis=AgentAnalysis(
            suggested_action=str(tool_input.get("action", "")),
            confidence=float(tool_input.get("confidence", 0.0) or 0.0),
            reasoning=str(tool_input.get("reasoning", "")),
        ),
        options=list(tool_input.get("options") or [])
        or ["approve_suggested", "archive", "draft_reply", "file_ticket", "skip"],
    )


def normalise_response(response: Any, payload: InterruptPayload) -> UserDecision:
    """Coerce whatever the caller sent back into a ``UserDecision``.

    Resume responses arrive from several places — the FastAPI decision screen,
    a host runtime's ``request_human_input`` tool, an AgentCore invoke
    payload, or a test — so accept a plain string, a dict, or a model.
    """
    if isinstance(response, UserDecision):
        return response
    if isinstance(response, dict):
        action = str(
            response.get("action")
            or response.get("chosen_action")
            or response.get("answer")
            or ""
        ).strip()
        note = str(response.get("note") or response.get("user_note") or "")
    else:
        action = str(response or "").strip()
        note = ""

    if not action or action == "approve_suggested":
        action = payload.agent_analysis.suggested_action or "skip"

    return UserDecision(
        interrupt_id=payload.interrupt_id, chosen_action=action, user_note=note
    )


class HITLGate(HookProvider):
    """Registers the decision gate on a Strands agent.

    Args:
        run_id: Correlates interrupts with the workflow run that raised them.
        workflow_id: Which workflow config this run belongs to.
        threshold: Confidence floor; below it the agent asks. Defaults to
            ``config.CONFIDENCE_THRESHOLD``.
        on_interrupt: Called with the ``InterruptPayload`` the moment a gate
            fires — used to persist it and to notify the human.
        on_decision: Called with ``(payload, decision)`` once a human answer
            comes back — used to write the audit entry and wake the learner.
    """

    def __init__(
        self,
        *,
        run_id: str = "",
        workflow_id: str = "",
        threshold: float | None = None,
        on_interrupt: Callable[[InterruptPayload], None] | None = None,
        on_decision: Callable[[InterruptPayload, UserDecision], None] | None = None,
        batch: bool = False,
    ) -> None:
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.threshold = config.CONFIDENCE_THRESHOLD if threshold is None else threshold
        self.on_interrupt = on_interrupt
        self.on_decision = on_decision
        #: Batch mode: an unsure item is set aside and the pass continues;
        #: ``finish_batch`` then asks about all of them at once. Immediate mode
        #: (the default, and what the unit tests exercise) suspends the loop
        #: on the spot. Batch mode needs an active run context.
        self.batch = batch

        #: Every payload this gate has raised, keyed by interrupt name. Lets the
        #: caller render pending decisions without touching Strands internals.
        self.payloads: dict[str, InterruptPayload] = {}
        #: Decisions applied so far, in order — the run's human-touch history.
        self.decisions: list[UserDecision] = []

    # -- HookProvider ------------------------------------------------------

    def register_hooks(self, registry: HookRegistry, **_: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.gate)

    # -- the gate itself ---------------------------------------------------

    def gate(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use.get("name", "")
        tool_input = event.tool_use.get("input", {}) or {}

        if tool_name == BATCH_TOOL:
            self._gate_batch(event)
            return

        # The user's past answers come first. If a rule covers this item, the
        # call is rewritten to what they chose and there is nothing to ask.
        ruled = apply_learned_rules(tool_name, tool_input)
        if ruled is not tool_input:
            event.tool_use = {**event.tool_use, "input": ruled}
            tool_input = ruled

        verdict = evaluate_gate(tool_name, tool_input, self.threshold)
        if not verdict.gated:
            return  # clear-cut: stay out of the human's way

        # One interrupt per item, so replays land on the same decision.
        interrupt_name = f"handoff_decision:{tool_input.get('item_id', tool_name)}"

        payload = self.payloads.get(interrupt_name)
        if payload is None:
            payload = build_payload(
                tool_name,
                tool_input,
                verdict.reason,
                run_id=self.run_id,
                workflow_id=self.workflow_id,
                interrupt_name=interrupt_name,
            )
            self.payloads[interrupt_name] = payload
            if self.on_interrupt is not None:
                self.on_interrupt(payload)

        from handoff.runtime import current_run

        ctx = current_run()
        if self.batch and ctx is not None:
            # Set it aside and let the pass continue. The tool body sees the
            # deferral and does nothing to this item; finish_batch will raise
            # one interrupt for everything deferred once the pass is done.
            payload.batch = True
            ctx.defer(payload.item.item_id or str(tool_input.get("item_id", "")), payload)
            return

        # --- THE LINE THE WHOLE PROJECT IS BUILT AROUND ---------------------
        # First pass: raises InterruptException and suspends the agent loop.
        # After resume: returns the human's answer and execution continues.
        response = event.interrupt(
            interrupt_name,
            reason=payload.model_dump(mode="json"),
        )
        # --------------------------------------------------------------------

        decision = normalise_response(response, payload)
        payload.decision = decision
        payload.resolved = True
        self.decisions.append(decision)

        if decision.chosen_action in NO_OP_ACTIONS:
            # The human said "leave it alone" — cancel the tool rather than
            # running it with a no-op argument, so the audit trail is honest.
            event.cancel_tool = (
                f"Human chose '{decision.chosen_action}' — no action taken on "
                f"{payload.item.item_id or payload.item.subject}."
            )
        else:
            # Rewrite the call to carry out what the human actually chose.
            new_input = dict(tool_input)
            new_input["action"] = decision.chosen_action
            new_input["confidence"] = 1.0
            new_input["force_interrupt"] = False
            new_input["decided_by"] = "human"
            new_input["human_note"] = decision.user_note
            event.tool_use = {**event.tool_use, "input": new_input}

        if self.on_decision is not None:
            self.on_decision(payload, decision)


    # -- batch mode: one interrupt for every deferred item -----------------

    def _gate_batch(self, event: BeforeToolCallEvent) -> None:
        """``finish_batch`` was called: ask about everything set aside, once.

        First pass: raises a single interrupt whose reason carries every
        deferred payload. After resume: the response maps item ids to the
        human's choices; each is recorded and handed to the tool body, which
        carries the chosen actions out.
        """
        from handoff.runtime import current_run

        ctx = current_run()
        if ctx is None or not ctx.deferred:
            return

        deferred = list(ctx.deferred.values())
        reason = {
            "count": len(deferred),
            "items": [p.model_dump(mode="json") for p in deferred],
        }

        # --- THE LINE THE WHOLE PROJECT IS BUILT AROUND (batch form) ---------
        response = event.interrupt(BATCH_INTERRUPT, reason=reason)
        # --------------------------------------------------------------------

        answers = response if isinstance(response, dict) else {}
        for payload in deferred:
            item_id = payload.item.item_id
            if payload.decision is None:
                answer = answers.get(item_id) or answers.get(payload.interrupt_id)
                payload.decision = normalise_response(answer, payload)
            payload.resolved = True
            self.decisions.append(payload.decision)
            ctx.batch_decisions[item_id] = payload.decision
            if self.on_decision is not None:
                self.on_decision(payload, payload.decision)


def register_hitl_gate(agent, **kwargs: Any) -> HITLGate:
    """Attach a fresh :class:`HITLGate` to an already-constructed agent."""
    gate = HITLGate(**kwargs)
    agent.add_hook(gate)
    return gate
