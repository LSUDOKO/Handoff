# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The scheduler that makes Handoff autonomous rather than a button.

Everything else in the product is about what happens *during* a run. This is
what makes runs happen at all when nobody is watching: a loop that wakes every
half-minute, works out which schedules are due, and fires them in the
background.

It runs inside the web process by default, so `handoff serve` or the desktop
app is a complete installation — no second service to start, no message bus.
That is a deliberate limit rather than an oversight: one process means the
schedule only fires while the app is open. For a laptop that is usually what
you want; for a workflow that must fire whether or not the laptop is awake,
deploy to AgentCore and let EventBridge own the schedule (`infra/`).

Cron parsing is done here rather than pulled in as a dependency because the
subset that matters — `*`, `a,b`, `a-b`, `*/n` across five fields — is small,
and a scheduler you can read is worth more than one you can't when it fires
at the wrong hour.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from handoff import events
from handoff.platform.models import Schedule
from handoff.store import get_store

#: How often the loop wakes. A minute's resolution is what cron promises, so
#: checking twice a minute is enough to never miss a slot.
TICK_SECONDS = 30


# --- cron ------------------------------------------------------------------


def _field(expression: str, low: int, high: int) -> set[int]:
    """Expand one cron field into the set of values it matches."""
    values: set[int] = set()
    for part in expression.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, _, raw_step = part.partition("/")
            step = int(raw_step or 1)
        if part in ("*", "?", ""):
            start, end = low, high
        elif "-" in part:
            raw_start, _, raw_end = part.partition("-")
            start, end = int(raw_start), int(raw_end)
        else:
            start = end = int(part)
        values.update(v for v in range(start, end + 1) if (v - start) % step == 0)
    return {v for v in values if low <= v <= high}


def matches(cron: str, moment: datetime) -> bool:
    """Does this 5-field cron expression fire at this minute?"""
    parts = cron.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    # cron treats Sunday as both 0 and 7; Python's weekday() is Monday=0.
    weekday = (moment.weekday() + 1) % 7
    return (
        moment.minute in _field(minute, 0, 59)
        and moment.hour in _field(hour, 0, 23)
        and moment.day in _field(dom, 1, 31)
        and moment.month in _field(month, 1, 12)
        and (weekday in _field(dow, 0, 7) or (weekday == 0 and 7 in _field(dow, 0, 7)))
    )


def next_fire(cron: str, timezone: str = "UTC", after: datetime | None = None) -> datetime | None:
    """When this expression next fires. Searches a year, then gives up."""
    try:
        zone = ZoneInfo(timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC

    moment = (after or datetime.now(UTC)).astimezone(zone).replace(second=0, microsecond=0)
    moment += timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if matches(cron, moment):
            return moment.astimezone(UTC)
        moment += timedelta(minutes=1)
    return None


def describe_next(schedule: Schedule) -> str:
    when = next_fire(schedule.cron, schedule.timezone)
    if when is None:
        return "never — check the expression"
    delta = when - datetime.now(UTC)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "within the minute"
    if minutes < 60:
        return f"in {minutes} min"
    if minutes < 1440:
        return f"in {minutes // 60}h {minutes % 60:02d}m"
    return f"in {minutes // 1440}d"


# --- the loop ---------------------------------------------------------------


class Scheduler:
    """Fires due schedules. One per process."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.started_at: datetime | None = None
        self.ticks = 0
        self.fired = 0
        self.last_tick: datetime | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.started_at = datetime.now(UTC)
        self._thread = threading.Thread(target=self._loop, name="handoff-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # a bad schedule must not kill the loop
                print(f"[handoff] scheduler tick failed: {exc}")
            self._stop.wait(TICK_SECONDS)

    def tick(self, now: datetime | None = None) -> list[str]:
        """Fire everything due. Returns the run ids started."""
        now = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
        self.ticks += 1
        self.last_tick = now

        store = get_store()
        started: list[str] = []

        for schedule in store.list_schedules(None):
            if not schedule.enabled:
                continue
            try:
                zone = ZoneInfo(schedule.timezone or "UTC")
            except (ZoneInfoNotFoundError, ValueError):
                zone = UTC
            local = now.astimezone(zone)

            if not matches(schedule.cron, local):
                continue
            # Don't double-fire within the same minute if the loop is fast.
            if schedule.last_run_at and schedule.last_run_at.replace(
                second=0, microsecond=0
            ) == now:
                continue

            run_id = self._fire(schedule)
            if run_id:
                started.append(run_id)
        return started

    def _fire(self, schedule: Schedule) -> str:
        from handoff.agents.executor import WorkflowRunner
        from handoff.models import TriggerType, WorkflowRun

        store = get_store()
        workflow = store.get_workflow(schedule.workflow_id)
        if workflow is None:
            return ""

        run = WorkflowRun(workflow_id=workflow.workflow_id, trigger_type=TriggerType.CRON)
        store.save_run(run)

        schedule.last_run_at = datetime.now(UTC)
        schedule.last_run_id = run.run_id
        schedule.run_count += 1
        schedule.next_run_at = next_fire(schedule.cron, schedule.timezone)
        store.schedules.put(schedule, "schedule_id")
        self.fired += 1

        events.emit(
            run.run_id,
            "started",
            f"Schedule fired: {workflow.name} ({schedule.cron} {schedule.timezone})",
            workflow_id=workflow.workflow_id,
        )

        def target() -> None:
            try:
                WorkflowRunner(workflow)._start_existing(run, "cron")
            except Exception as exc:
                print(f"[handoff] scheduled run failed: {exc}")

        threading.Thread(target=target, name=f"cron-{run.run_id}", daemon=True).start()
        return run.run_id

    def status(self) -> dict[str, Any]:
        store = get_store()
        schedules = store.list_schedules(None)
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "ticks": self.ticks,
            "fired": self.fired,
            "last_tick": self.last_tick.isoformat() if self.last_tick else "",
            "enabled_schedules": sum(1 for s in schedules if s.enabled),
            "total_schedules": len(schedules),
            "tick_seconds": TICK_SECONDS,
        }


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


# --- keeping schedules in step with workflows -------------------------------


def sync_schedules() -> list[Schedule]:
    """Give every active cron workflow a schedule, once.

    A workflow declares when it wants to run; a Schedule is the live,
    switchable instance of that. Creating them here means importing a
    template or saving a workflow in chat is enough to make it real.
    """
    from handoff.models import TriggerType, WorkflowStatus

    store = get_store()
    have = {s.workflow_id for s in store.list_schedules(None)}
    created: list[Schedule] = []

    for workflow in store.list_workflows():
        if workflow.trigger.type is not TriggerType.CRON or not workflow.trigger.schedule:
            continue
        if workflow.workflow_id in have:
            continue
        schedule = Schedule(
            workflow_id=workflow.workflow_id,
            cron=workflow.trigger.schedule,
            timezone=workflow.trigger.timezone or "UTC",
            enabled=workflow.status is WorkflowStatus.ACTIVE,
        )
        schedule.next_run_at = next_fire(schedule.cron, schedule.timezone)
        store.schedules.put(schedule, "schedule_id")
        created.append(schedule)
    return created
