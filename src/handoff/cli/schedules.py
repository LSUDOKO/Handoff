# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff schedules` and `handoff scheduler` — when things fire, and the loop that fires them."""

from __future__ import annotations

import argparse
import time

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("schedules", help="Cron schedules: list, switch on/off, fire one now")
    p.set_defaults(handle=handle)
    s = p.add_subparsers(dest="schedules_command", metavar="<action>")

    s.add_parser("list", help="Every schedule and when it next fires (the default)")

    p_toggle = s.add_parser("toggle", help="Switch a schedule on or off")
    p_toggle.add_argument("schedule_id")

    p_run = s.add_parser("run", help="Fire a schedule's workflow now")
    p_run.add_argument("schedule_id")
    p_run.add_argument("--watch", action="store_true", help="Follow the run's events live")

    p_daemon = sub.add_parser("scheduler", help="Run the scheduler in the foreground until Ctrl-C")
    p_daemon.set_defaults(handle=handle_scheduler)


def _get(schedule_id: str):
    from handoff.store import get_store

    schedule = get_store().schedules.get("schedule_id", schedule_id)
    if schedule is None:
        raise KeyError(f"No schedule with id '{schedule_id}'")
    return schedule


def rows() -> list[dict]:
    from handoff import daemon
    from handoff.store import get_store

    store = get_store()
    names = {w.workflow_id: w.name for w in store.list_workflows()}
    out = []
    for schedule in store.list_schedules(_ui.workspace()):
        out.append(
            {
                **schedule.model_dump(mode="json"),
                "workflow": names.get(schedule.workflow_id, schedule.workflow_id),
                "next": daemon.describe_next(schedule) if schedule.enabled else "off",
            }
        )
    return out


def handle(args: argparse.Namespace) -> int:
    from handoff import daemon
    from handoff.cli import runs
    from handoff.store import get_store

    action = args.schedules_command or "list"

    if action == "list":
        data = rows()
        _ui.emit(
            data,
            lambda: _ui.table(
                "Schedules",
                ["id", "workflow", "cron", "timezone", "on", "next", "last run", "fired"],
                [
                    [
                        r["schedule_id"], r["workflow"], r["cron"], r["timezone"], _ui.yes_no(r["enabled"]),
                        r["next"], _ui.when(r["last_run_at"]), r["run_count"],
                    ]
                    for r in data
                ],
            ),
        )
        return 0

    if action == "toggle":
        store = get_store()
        schedule = _get(args.schedule_id)
        schedule.enabled = not schedule.enabled
        schedule.next_run_at = (
            daemon.next_fire(schedule.cron, schedule.timezone) if schedule.enabled else None
        )
        store.schedules.put(schedule, "schedule_id")
        if _ui.json_mode():
            _ui.print_json(schedule)
        else:
            state = f"on — next {daemon.describe_next(schedule)}" if schedule.enabled else "off"
            _ui.ok(f"{schedule.workflow_id} {schedule.cron} {schedule.timezone}: {state}")
        return 0

    if action == "run":
        from handoff.agents.executor import run_workflow

        schedule = _get(args.schedule_id)
        workflow = get_store().get_workflow(schedule.workflow_id)
        if workflow is None:
            raise KeyError(f"Schedule {schedule.schedule_id} points at a workflow that no longer exists")
        outcome = (
            runs.start_and_watch(workflow, "cron") if args.watch else run_workflow(workflow.workflow_id, "cron")
        )
        return runs.print_outcome(outcome)

    return 2


def handle_scheduler(args: argparse.Namespace) -> int:
    from handoff import events
    from handoff.daemon import get_scheduler

    scheduler = get_scheduler()
    scheduler.start()
    status = scheduler.status()
    if _ui.json_mode():
        _ui.print_json(status)
    else:
        _ui.ok(
            f"scheduler running — {status['enabled_schedules']} of {status['total_schedules']} schedules on, "
            f"checking every {status['tick_seconds']}s. Ctrl-C to stop."
        )

    feed = events.subscribe("*", replay=False, keepalive=1.0)
    try:
        for event in feed:
            kind = event.get("kind")
            if kind == "keepalive":
                continue
            if kind in ("started", "completed", "failed", "asked"):
                if _ui.json_mode():
                    _ui.print_json(event)
                else:
                    _ui.console.print(
                        f"[dim]{_ui.stamp(event)}[/] [bold]{kind:<10}[/] {event.get('run_id', '')}  "
                        f"{_ui.escape(str(event.get('text', '')))}",
                        soft_wrap=True,
                    )
    except KeyboardInterrupt:
        pass
    finally:
        feed.close()
        scheduler.stop()
        time.sleep(0.05)
    if not _ui.json_mode():
        _ui.console.print()
        _ui.dim(f"stopped after {scheduler.ticks} ticks, {scheduler.fired} runs fired")
    return 0
