# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The two levers a spoken turn needs that a typed one does not.

Typed chat shows a config and a "Save and switch on" button; the person
clicks. Spoken chat has no button, so the assistant has to do the saving
and the starting itself — and the page has to find out. Both tools emit an
event on the chat's channel (``workflow_saved``, ``run_started``) so the orb
page can draw the workspace card and follow the run without polling.

The channel comes from a context variable set for the duration of a turn,
because a Strands tool is called by the agent loop with only its declared
arguments; there is no other clean way to hand it the page it belongs to.
"""

from __future__ import annotations

import json
import threading
from contextvars import ContextVar

from strands import tool

from handoff import events
from handoff.store import get_store

#: The events channel of the chat whose turn is running, or "" outside one,
#: and that turn's number — the page follows one turn at a time.
current_channel: ContextVar[str] = ContextVar("handoff_chat_channel", default="")
current_turn: ContextVar[int] = ContextVar("handoff_chat_turn", default=0)


def _emit(kind: str, text: str, **data) -> None:
    channel = current_channel.get()
    if channel:
        events.emit(channel, kind, text, turn=current_turn.get(), **data)


@tool
def activate_workflow(config_json: str) -> dict:
    """Save a workflow config and switch it on, in one step.

    Use this when the person has asked you to set up a chore and you have
    designed the config: pass the complete JSON. It is validated, saved,
    activated, and scheduled if it has a cron trigger. Call it even when
    validate_workflow reported warnings — a warning that an integration is
    not configured yet is informational, not a reason to wait. Tell them in
    one sentence what you set up and when it will next run.

    Args:
        config_json: The full workflow config as a JSON string, matching the
            schema you were given (workflow_id, name, trigger, mcp_tools,
            steps, completion, memory).
    """
    from handoff.models import WorkflowConfig, WorkflowStatus
    from handoff.tools.mcp_discovery import validate_config_dict

    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"That config is not valid JSON: {exc}"}
    if not isinstance(parsed, dict) or not parsed.get("workflow_id") or not parsed.get("name"):
        return {"ok": False, "error": "A config needs at least workflow_id and name"}

    result = validate_config_dict(parsed)
    if not result.get("valid"):
        return {"ok": False, "error": "; ".join(result.get("errors", [])) or "invalid config"}
    try:
        workflow = WorkflowConfig.model_validate(result["config"])
    except Exception as exc:
        return {"ok": False, "error": f"Config rejected: {str(exc)[:200]}"}
    workflow.status = WorkflowStatus.ACTIVE
    get_store().save_workflow(workflow)

    _emit(
        "workflow_saved",
        f"Saved and switched on {workflow.name}",
        workflow_id=workflow.workflow_id,
        config=workflow.model_dump(mode="json"),
    )
    return {
        "ok": True,
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "status": "active",
        "schedule": workflow.trigger.schedule,
        "timezone": workflow.trigger.timezone,
    }


@tool
def start_run(workflow_id: str) -> dict:
    """Start a workflow now, in the background, and return its run id.

    Use when the person says to run it, try it, or go. The run continues
    after you reply; anything it cannot decide on its own will be asked
    on this same page.

    Args:
        workflow_id: The workflow's id, as returned by activate_workflow or
            listed by list_workflows.
    """
    from handoff.agents.executor import WorkflowRunner
    from handoff.models import TriggerType, WorkflowRun

    store = get_store()
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        return {"ok": False, "error": f"No workflow '{workflow_id}'"}

    run = WorkflowRun(workflow_id=workflow_id, trigger_type=TriggerType.MANUAL)
    store.save_run(run)
    # The bus stamps every event with the channel as ``run_id``, so the run
    # being started travels as ``run``.
    _emit(
        "run_started",
        f"Running {workflow.name}",
        run=run.run_id,
        workflow_id=workflow_id,
        workflow_name=workflow.name,
        mcp_tools=list(workflow.mcp_tools),
    )

    def target() -> None:
        try:
            WorkflowRunner(workflow)._start_existing(run, "voice")
        except Exception as exc:  # the runner already recorded the failure
            print(f"[handoff] voice-started run failed: {exc}")

    threading.Thread(target=target, name=f"run-{run.run_id}", daemon=True).start()
    return {"ok": True, "run_id": run.run_id, "workflow": workflow.name, "events": f"/events/{run.run_id}"}
