# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff workflows` — the saved workflows, and switching them on and off."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("workflows", help="List, inspect, enable, disable, delete or export workflows")
    p.set_defaults(handle=handle)
    ws = p.add_subparsers(dest="wf_command", metavar="<action>")

    ws.add_parser("list", help="List saved workflows (the default)")

    p_show = ws.add_parser("show", help="Everything about one workflow")
    p_show.add_argument("workflow_id")

    p_enable = ws.add_parser("enable", help="Mark a workflow active so its schedule fires")
    p_enable.add_argument("workflow_id")

    p_disable = ws.add_parser("disable", help="Pause a workflow; its schedule stops firing")
    p_disable.add_argument("workflow_id")

    p_delete = ws.add_parser("delete", help="Delete a workflow and its schedule")
    p_delete.add_argument("workflow_id")

    p_export = ws.add_parser("export", help="Write one workflow's config as JSON")
    p_export.add_argument("workflow_id")
    p_export.add_argument("path", nargs="?", default="", help="File to write (default: stdout)")


def _get(workflow_id: str):
    from handoff.store import get_store

    workflow = get_store().get_workflow(workflow_id)
    if workflow is None:
        raise KeyError(f"No workflow with id '{workflow_id}'")
    return workflow


def _set_status(workflow_id: str, status) -> int:
    from handoff.daemon import sync_schedules
    from handoff.store import get_store

    store = get_store()
    workflow = _get(workflow_id)
    workflow.status = status
    store.save_workflow(workflow)
    sync_schedules()
    for schedule in store.list_schedules(None):
        if schedule.workflow_id == workflow_id:
            schedule.enabled = status.value == "active"
            store.schedules.put(schedule, "schedule_id")
    _ui.emit({"workflow_id": workflow_id, "status": status.value})
    return 0


def list_rows() -> list[dict]:
    from handoff.store import get_store

    store = get_store()
    rows = []
    for workflow in store.list_workflows():
        latest = store.latest_run(workflow.workflow_id)
        rows.append(
            {
                "workflow_id": workflow.workflow_id,
                "name": workflow.name,
                "status": workflow.status.value,
                "trigger": workflow.trigger.type.value,
                "schedule": workflow.trigger.schedule,
                "timezone": workflow.trigger.timezone,
                "tools": workflow.mcp_tools,
                "last_run": latest.started_at.isoformat() if latest else "",
                "last_status": latest.status.value if latest else "",
            }
        )
    return rows


def handle(args: argparse.Namespace) -> int:
    from handoff.models import WorkflowStatus
    from handoff.store import get_store

    action = args.wf_command or "list"

    if action == "list":
        rows = list_rows()
        _ui.emit(
            rows,
            lambda: _ui.table(
                "Workflows",
                ["id", "status", "name", "trigger", "last run"],
                [
                    [
                        r["workflow_id"], r["status"], r["name"],
                        f"{r['trigger']} {r['schedule']}".strip(),
                        f"{_ui.when(r['last_run'])} {r['last_status']}".strip(),
                    ]
                    for r in rows
                ],
            ),
        )
        return 0

    if action == "show":
        workflow = _get(args.workflow_id)
        if _ui.json_mode():
            _ui.print_json(workflow)
            return 0
        _ui.console.print(
            _ui.kv_table(
                workflow.name,
                {
                    "id": workflow.workflow_id,
                    "status": workflow.status.value,
                    "description": workflow.description,
                    "trigger": workflow.trigger.type.value,
                    "schedule": f"{workflow.trigger.schedule} {workflow.trigger.timezone}".strip(),
                    "tools": ", ".join(workflow.mcp_tools) or "built-in only",
                    "threshold": workflow.confidence_threshold or "default",
                    "notify": f"{workflow.completion.notify} {workflow.completion.channel}".strip(),
                    "learns": _ui.yes_no(workflow.memory.learn_from_decisions),
                    "updated": _ui.when(workflow.updated_at),
                },
            )
        )
        if workflow.steps:
            _ui.console.print(
                _ui.code_panel(json.dumps(workflow.steps, indent=2, default=str), title="steps")
            )
        return 0

    if action == "enable":
        return _set_status(args.workflow_id, WorkflowStatus.ACTIVE)

    if action == "disable":
        return _set_status(args.workflow_id, WorkflowStatus.PAUSED)

    if action == "delete":
        from handoff.tools.workflow_store import load_example_workflows

        store = get_store()
        workflow = _get(args.workflow_id)
        store.workflows.delete("workflow_id", workflow.workflow_id)
        for schedule in store.list_schedules(None):
            if schedule.workflow_id == workflow.workflow_id:
                store.schedules.delete("schedule_id", schedule.schedule_id)
        # Shipped templates are re-seeded on every start; deleting one only
        # lasts until then. Say so rather than let it look like it stuck.
        shipped = any(w.workflow_id == workflow.workflow_id for w in load_example_workflows())
        if _ui.json_mode():
            _ui.print_json({"deleted": workflow.workflow_id, "shipped_template": shipped})
        else:
            _ui.ok(f"deleted {workflow.name}")
            if shipped:
                _ui.warn("that is a shipped template — it comes back on the next start; `workflows disable` keeps it off")
        return 0

    if action == "export":
        workflow = _get(args.workflow_id)
        text = workflow.model_dump_json(indent=2, exclude={"created_at", "updated_at"})
        if args.path:
            Path(args.path).write_text(text + "\n")
            if _ui.json_mode():
                _ui.print_json({"wrote": args.path, "workflow_id": workflow.workflow_id})
            else:
                _ui.ok(f"wrote {args.path}")
        else:
            _ui.out(text)
        return 0

    return 2
