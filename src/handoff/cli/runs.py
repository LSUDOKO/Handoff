# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff run`, and everything about runs after the fact.

``run --watch`` follows the events bus the web UI paints from, so the
terminal sees the same "fetched 8 messages … set aside msg_004 for you" a
browser would, as it happens.
"""

from __future__ import annotations

import argparse
import threading
from typing import Any

from handoff.cli import _ui

#: Event kinds that end a run's live feed.
TERMINAL = ("completed", "failed", "asked")


def register(sub: argparse._SubParsersAction) -> None:
    p_run = sub.add_parser("run", help="Run a workflow now")
    p_run.add_argument("workflow_id", nargs="?", default="inbox-triage-morning")
    p_run.add_argument("--trigger", default="manual", help="Recorded as the run's trigger type")
    p_run.add_argument("--watch", action="store_true", help="Follow the run's events live")
    p_run.set_defaults(handle=handle_run)

    p_runs = sub.add_parser("runs", help="Recent runs, newest first")
    p_runs.add_argument("--limit", type=int, default=25)
    p_runs.add_argument("--workflow", default="", help="Only runs of this workflow")
    p_runs.set_defaults(handle=handle_runs)

    p_inspect = sub.add_parser("inspect", help="Every model and tool step of one run")
    p_inspect.add_argument("run_id")
    p_inspect.set_defaults(handle=handle_inspect)

    p_pending = sub.add_parser("pending", help="List decisions waiting on you")
    p_pending.set_defaults(handle=handle_pending)

    p_activity = sub.add_parser("activity", help="The audit log: what was done, by whom")
    p_activity.add_argument("--limit", type=int, default=25)
    p_activity.add_argument("--run", default="", help="Only this run's entries")
    p_activity.set_defaults(handle=handle_activity)

    p_decide = sub.add_parser("decide", help="Answer a pending decision")
    p_decide.add_argument("interrupt_id", nargs="?", default="", help="The decision's id (see `pending`)")
    p_decide.add_argument("action", nargs="?", default="", help="archive, file_ticket, draft_reply, skip…")
    p_decide.add_argument("--note", default="", help="Why — it becomes the rule that is learned")
    p_decide.add_argument("--all", action="store_true", help="Apply the action to every pending decision")
    p_decide.set_defaults(handle=handle_decide)


# --- running ----------------------------------------------------------------


def start_and_watch(workflow: Any, trigger: str = "manual") -> dict[str, Any]:
    """Start a run on a thread and print its events until it settles.

    Mirrors the web server's background start: the run row exists before
    the model says a word, so the feed can be followed by id from the start.
    """
    from handoff import events
    from handoff.agents.executor import WorkflowRunner
    from handoff.models import TriggerType, WorkflowRun
    from handoff.store import get_store

    store = get_store()
    trigger_type = TriggerType(trigger) if trigger in {t.value for t in TriggerType} else TriggerType.MANUAL
    run = WorkflowRun(workflow_id=workflow.workflow_id, trigger_type=trigger_type)
    store.save_run(run)

    holder: dict[str, Any] = {}

    def target() -> None:
        try:
            holder["outcome"] = WorkflowRunner(workflow)._start_existing(run, trigger)
        except Exception as exc:  # the runner already recorded the failure
            holder["error"] = exc

    thread = threading.Thread(target=target, name=f"run-{run.run_id}", daemon=True)
    thread.start()

    feed = events.subscribe(run.run_id, replay=True, keepalive=0.5)
    try:
        for event in feed:
            kind = event.get("kind", "note")
            if kind == "keepalive":
                if not thread.is_alive():
                    break
                continue
            if not _ui.json_mode():
                _ui.console.print(
                    f"[dim]{_ui.stamp(event)}[/] [bold]{kind:<10}[/] {_ui.escape(str(event.get('text', '')))}",
                    soft_wrap=True,
                )
            if kind in TERMINAL:
                break
    finally:
        feed.close()

    thread.join(timeout=60)
    if "error" in holder:
        raise holder["error"]
    if "outcome" in holder:
        return holder["outcome"]
    # The feed ended but the runner is still settling; describe the row as is.
    current = store.get_run(run.run_id) or run
    return {
        "run_id": current.run_id,
        "workflow_id": current.workflow_id,
        "status": current.status.value,
        "auto_count": current.auto_count,
        "human_count": current.interrupt_count,
        "memory_count": current.memory_count,
        "pending_interrupts": [],
        "summary": current.summary,
    }


def print_outcome(outcome: dict[str, Any]) -> int:
    if _ui.json_mode():
        _ui.print_json(dict(outcome))
    else:
        status = outcome.get("status", "")
        pending = outcome.get("pending_interrupts") or []
        _ui.console.print(
            _ui.kv_table(
                "",
                {
                    "run": outcome.get("run_id", ""),
                    "status": status,
                    "handled alone": outcome.get("auto_count", 0),
                    "decided by you": outcome.get("human_count", 0),
                    "from your rules": outcome.get("memory_count", 0),
                    "summary": outcome.get("summary", ""),
                },
            )
        )
        if pending:
            _ui.warn(f"{len(pending)} decision(s) need you — `handoff pending`")
    return 1 if outcome.get("status") == "failed" else 0


def handle_run(args: argparse.Namespace) -> int:
    from handoff.agents.executor import run_workflow
    from handoff.store import get_store

    workflow = get_store().get_workflow(args.workflow_id)
    if workflow is None:
        raise KeyError(f"No workflow with id '{args.workflow_id}'")

    if args.watch:
        outcome = start_and_watch(workflow, args.trigger)
    else:
        outcome = run_workflow(args.workflow_id, args.trigger)
    return print_outcome(outcome)


# --- reading back -----------------------------------------------------------


def handle_runs(args: argparse.Namespace) -> int:
    from handoff.store import get_store

    store = get_store()
    names = {w.workflow_id: w.name for w in store.list_workflows()}
    runs = store.list_runs(args.workflow or None, limit=args.limit)
    rows = [
        {
            **run.model_dump(mode="json", exclude={"graph_state"}),
            "workflow": names.get(run.workflow_id, run.workflow_id),
        }
        for run in runs
    ]
    _ui.emit(
        rows,
        lambda: _ui.table(
            "Runs",
            ["run", "workflow", "status", "started", "alone", "you", "rules", "summary"],
            [
                [
                    r["run_id"], r["workflow"], r["status"], _ui.when(r["started_at"]),
                    r["auto_count"], r["interrupt_count"], r["memory_count"], r["summary"],
                ]
                for r in rows
            ],
        ),
    )
    return 0


def handle_inspect(args: argparse.Namespace) -> int:
    from handoff.store import get_store

    store = get_store()
    run = store.get_run(args.run_id)
    session = store.get_session(args.run_id)
    if run is None and session is None:
        raise KeyError(f"No run with id '{args.run_id}'")

    steps = session.steps if session else []
    if _ui.json_mode():
        _ui.print_json(
            {
                "run": run.model_dump(mode="json", exclude={"graph_state"}) if run else None,
                "steps": [s.model_dump(mode="json") for s in steps],
            }
        )
        return 0

    if run is not None:
        _ui.console.print(
            _ui.kv_table(
                run.run_id,
                {
                    "workflow": run.workflow_id,
                    "status": run.status.value,
                    "started": _ui.when(run.started_at),
                    "finished": _ui.when(run.finished_at),
                    "summary": run.summary,
                },
            )
        )
    _ui.console.print(
        _ui.table(
            f"{len(steps)} steps",
            ["#", "node", "kind", "name", "status", "ms"],
            [[s.index, s.node, s.kind, s.name, s.status + (" (gated)" if s.gated else ""), s.duration_ms] for s in steps],
        )
    )
    return 0


def pending_rows() -> list[dict[str, Any]]:
    from handoff.store import get_store

    return [p.model_dump(mode="json") for p in get_store().pending_interrupts()]


def handle_pending(args: argparse.Namespace) -> int:
    rows = pending_rows()
    _ui.emit(
        rows,
        lambda: _ui.table(
            f"{len(rows)} waiting on you",
            ["id", "from", "confidence", "subject", "suggested"],
            [
                [
                    r["interrupt_id"], r["item"]["sender"],
                    f"{float(r['agent_analysis']['confidence']):.0%}",
                    r["item"]["subject"] or r["item"]["summary"],
                    r["agent_analysis"]["suggested_action"],
                ]
                for r in rows
            ],
        ),
    )
    return 0


def handle_activity(args: argparse.Namespace) -> int:
    from handoff.tools.audit_log import read_audit_log

    rows = read_audit_log(run_id=args.run, limit=args.limit)
    _ui.emit(
        rows,
        lambda: _ui.table(
            "Activity",
            ["when", "action", "by", "confidence", "item", "workflow"],
            [
                [
                    _ui.when(r["timestamp"]), r["action"], r["decision_by"],
                    f"{float(r['confidence']):.0%}",
                    (r["details"] or {}).get("summary") or r["item_id"], r["workflow_id"],
                ]
                for r in rows
            ],
        ),
    )
    return 0


# --- deciding ---------------------------------------------------------------


def handle_decide(args: argparse.Namespace) -> int:
    from handoff.agents.executor import submit_decision
    from handoff.store import get_store

    if args.all:
        action = args.action or args.interrupt_id
        if not action:
            raise ValueError("decide --all needs the action to apply, e.g. `decide --all archive`")
        outcomes = []
        for payload in list(get_store().pending_interrupts()):
            outcome = submit_decision(payload.interrupt_id, action, args.note)
            outcomes.append({"interrupt_id": payload.interrupt_id, **dict(outcome)})
            if not _ui.json_mode():
                _ui.ok(f"{payload.interrupt_id}  {action}  → run {outcome.get('status')}")
        if _ui.json_mode():
            _ui.print_json(outcomes)
        elif not outcomes:
            _ui.dim("nothing was waiting")
        return 0

    if not args.interrupt_id or not args.action:
        raise ValueError("decide needs an interrupt id and an action (or --all <action>)")
    outcome = submit_decision(args.interrupt_id, args.action, args.note)
    if _ui.json_mode():
        _ui.print_json(dict(outcome))
        return 0
    learned = outcome.get("learned") or {}
    _ui.ok(f"{args.action} recorded — run {outcome.get('status')}")
    if learned.get("stored"):
        _ui.dim(f"learned: {learned.get('pattern', 'a new rule')}")
    return 0
