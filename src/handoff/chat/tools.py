# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""What the chat assistant can do to the workspace.

Friday's playground chat "actually drives your tools instead of describing
what it would do". These are the levers: run a workflow, see what happened,
answer a decision, remember a rule. The workflow-building tools come from the
Builder; the memory and artifact tools from their own modules.
"""

from __future__ import annotations

import threading
from typing import Any

from strands import tool

from handoff.store import get_store


@tool
def run_workflow_now(workflow_id: str) -> dict:
    """Start a workflow run right now, in the background, and return its run id.

    Use when the person asks to run, trigger, or try a workflow. The run
    continues after you reply; tell them they can watch it in Runs, and that
    anything it can't decide will show up in Activity.

    Args:
        workflow_id: The workflow's id, as listed by list_workflows.
    """
    from handoff.agents.executor import WorkflowRunner
    from handoff.models import TriggerType, WorkflowRun

    store = get_store()
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        return {"ok": False, "error": f"No workflow '{workflow_id}'"}
    run = WorkflowRun(workflow_id=workflow_id, trigger_type=TriggerType.MANUAL)
    store.save_run(run)

    def target() -> None:
        try:
            WorkflowRunner(workflow)._start_existing(run, "chat")
        except Exception as exc:  # the runner already recorded the failure
            print(f"[handoff] chat-started run failed: {exc}")

    threading.Thread(target=target, name=f"run-{run.run_id}", daemon=True).start()
    return {"ok": True, "run_id": run.run_id, "workflow": workflow.name, "status": "running"}


@tool
def recent_runs(limit: int = 5) -> list[dict]:
    """The most recent workflow runs: status, counts, and a one-line summary.

    Args:
        limit: How many to return, newest first.
    """
    store = get_store()
    rows = []
    for run in store.list_runs(limit=limit):
        workflow = store.get_workflow(run.workflow_id)
        rows.append(
            {
                "run_id": run.run_id,
                "workflow": workflow.name if workflow else run.workflow_id,
                "status": run.status.value,
                "handled_alone": run.auto_count,
                "decided_by_human": run.interrupt_count,
                "from_rules": run.memory_count,
                "started_at": run.started_at.isoformat(),
                "summary": run.summary,
            }
        )
    return rows


@tool
def pending_decisions() -> list[dict]:
    """Everything currently waiting on the person: the item, why it stopped,
    what the agent suggested, and the options."""
    return [
        {
            "interrupt_id": p.interrupt_id,
            "workflow_id": p.workflow_id,
            "subject": p.item.subject or p.item.summary,
            "sender": p.item.sender,
            "reason": p.agent_analysis.reasoning or p.reason,
            "suggested": p.agent_analysis.suggested_action,
            "confidence": p.agent_analysis.confidence,
            "options": p.options,
        }
        for p in get_store().pending_interrupts()
    ]


@tool
def decide(interrupt_id: str, action: str, note: str = "") -> dict:
    """Answer a pending decision on the person's behalf — only when they have
    told you, in this conversation, what to do with it.

    Args:
        interrupt_id: From pending_decisions.
        action: One of the decision's options (archive, file_ticket, draft_reply, skip…).
        note: What they said about it, so the rule that's learned is theirs.
    """
    from handoff.agents.executor import submit_decision

    try:
        outcome = submit_decision(interrupt_id, action, note)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "status": outcome.get("status"), "learned": outcome.get("learned")}


@tool
def workspace_overview() -> dict[str, Any]:
    """A snapshot of this workspace: workflows, schedules, connected
    integrations, and counters. Call this before answering questions about
    "what's set up" or "what happened"."""
    from handoff.platform import credentials as creds

    store = get_store()
    return {
        "workflows": [
            {
                "workflow_id": w.workflow_id,
                "name": w.name,
                "trigger": w.trigger.type.value,
                "schedule": w.trigger.schedule,
                "tools": w.mcp_tools,
                "status": w.status.value,
            }
            for w in store.list_workflows()
        ],
        "connected": [c["label"] for c in creds.catalogue() if c.get("connected")],
        "stats": store.stats(),
    }
