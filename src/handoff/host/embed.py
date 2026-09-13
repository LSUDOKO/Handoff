# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Running Handoff inside someone else's agent runtime.

Handoff has two front ends. Its own — the web UI and the desktop window —
raises an interrupt, shows a decision screen, and resumes the run when the
person answers. The other is this one: a host runtime that already has the
user's credentials and its own way of asking them a question. There, the same
gate answers inline through the host, and the run never unwinds.

The whole loop is unchanged either way — the same Strands Graph, the same
three agents, the same interrupt gate. Only where the question goes differs.

Embedding it takes one call:

    from handoff.host import run_in_host

    result = run_in_host(ctx, "run the morning triage")

``ctx`` is whatever your runtime hands an agent, and needs only:

    ctx.tools.list()              -> objects with .name, .description, .input_schema
    ctx.tools.call(name, args)    -> dict
    ctx.stream.progress(text)     -> None            (optional)

If the host exposes a ``request_human_input`` tool, Handoff uses it for
decisions. If it doesn't, nothing breaks — items it can't judge are left
alone and reported, rather than acted on unilaterally.
"""

from __future__ import annotations

from typing import Any

from handoff import config, events
from handoff.graph.factory import build_workflow_graph
from handoff.host.gate import HostGate
from handoff.host.tools import describe, load_host_tools
from handoff.models import RunStatus, TriggerType, WorkflowRun
from handoff.runtime import RunContext, run_context
from handoff.store import get_store
from handoff.tools.workflow_store import seed_examples

DEFAULT_WORKFLOW = "inbox-triage-morning"


def _progress(ctx: Any, text: str) -> None:
    stream = getattr(ctx, "stream", None)
    if stream is None:
        return
    try:
        stream.progress(text)
    except Exception:
        pass


def pick_workflow(prompt: str, store) -> Any:
    """Choose the workflow this invocation is about.

    The host's prompt usually names it; fall back to the demo workflow so a
    bare "run it" from a chat box still does something sensible.
    """
    workflows = store.list_workflows()
    lowered = (prompt or "").lower()
    for workflow in workflows:
        if workflow.workflow_id in lowered or workflow.name.lower() in lowered:
            return workflow
    return store.get_workflow(DEFAULT_WORKFLOW) or (workflows[0] if workflows else None)


def run_in_host(ctx: Any, prompt: str = "") -> dict[str, Any]:
    """Run a workflow, asking the host's human whenever the gate stops.

    Args:
        ctx: The host's agent context (see the module docstring's protocol).
        prompt: What the host was asked to do. Used to pick the workflow.

    Returns:
        A summary of the run: what was handled alone, what the person decided,
        what came from a learned rule, and any new rules written. On failure,
        ``{"ok": False, "error": ...}`` rather than an exception, because a
        host should be able to report a failed job without crashing.
    """
    config.configure_observability()
    seed_examples()
    store = get_store()

    workflow = pick_workflow(prompt, store)
    if workflow is None:
        return {"ok": False, "error": "No workflows configured."}

    _progress(ctx, f"Running '{workflow.name}' on the Strands graph")

    run = WorkflowRun(workflow_id=workflow.workflow_id, trigger_type=TriggerType.EVENT)
    store.save_run(run)

    def on_interrupt(payload) -> None:
        payload.run_id = run.run_id
        payload.workflow_id = workflow.workflow_id
        store.save_interrupt(payload)

    def on_decision(payload, decision) -> None:
        store.save_interrupt(payload)
        _progress(ctx, f"You chose: {decision.chosen_action}")

    gate = HostGate(
        ctx,
        run_id=run.run_id,
        workflow_id=workflow.workflow_id,
        threshold=workflow.confidence_threshold or config.CONFIDENCE_THRESHOLD,
        on_interrupt=on_interrupt,
        on_decision=on_decision,
    )

    # The host holds the OAuth. Take its already-authenticated tools rather
    # than opening a second set of connections with a second set of secrets.
    host_tools = load_host_tools(ctx, workflow.mcp_tools)
    _progress(ctx, describe(host_tools))

    graph = build_workflow_graph(workflow, config.get_model(), gate, extra_tools=host_tools)
    run_ctx = RunContext(
        run_id=run.run_id, workflow_id=workflow.workflow_id, workflow=workflow
    )

    task = (
        f"Run the workflow '{workflow.name}'.\n"
        f"Description: {workflow.description}\n"
        f"Trigger: event\n"
        f"Preference key: {workflow.memory.preference_key}\n"
        f"Signal: {prompt}\n"
        f"{describe(host_tools)}"
    )

    try:
        with run_context(run_ctx):
            result = graph(task)
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.summary = str(exc)[:300]
        store.save_run(run)
        events.emit(run.run_id, "failed", run.summary)
        return {"ok": False, "error": run.summary, "runId": run.run_id}

    run.status = RunStatus.COMPLETED
    run.auto_count = run_ctx.auto_count
    run.interrupt_count = run_ctx.human_count
    run.memory_count = run_ctx.memory_count
    run.summary = run_ctx.notes[-1] if run_ctx.notes else str(result)[:500]
    store.save_run(run)

    # Turn each decision the person made into a rule, so the next run is quieter.
    learned: list[str] = []
    if workflow.memory.learn_from_decisions and gate.decisions:
        from handoff.agents.learner import learn_from_decision

        for payload in gate.asked:
            if payload.decision is None:
                continue
            try:
                outcome = learn_from_decision(
                    payload,
                    payload.decision,
                    preference_key=workflow.memory.preference_key,
                )
                learned += [rule["pattern"] for rule in outcome.get("rules", [])]
            except Exception as exc:
                _progress(ctx, f"Couldn't store a rule: {exc}")

    _progress(
        ctx, f"Done — {run.auto_count} handled, {run.interrupt_count} decided by you"
    )

    return {
        "ok": True,
        "workflow": workflow.workflow_id,
        "runId": run.run_id,
        "summary": run.summary,
        "handledAutonomously": run.auto_count,
        "decidedByYou": run.interrupt_count,
        "handledFromMemory": run.memory_count,
        "rulesLearned": learned,
    }
