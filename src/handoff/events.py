# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""A live feed of what a run is doing, for people watching it.

The audit log is the record; this is the window. Tools and the runner emit
short events as they go — "fetched 8 messages", "set aside msg_004 for you",
"archived msg_002" — and the UI streams them over SSE so a person can watch
the agent work rather than stare at a spinner and take it on faith.

In-memory, per process, bounded. A restart loses the feed but not the record;
the audit trail and the run's summary are what survive.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

#: Events kept per run, and how many runs to remember.
_PER_RUN = 400
_RUNS = 50

_lock = threading.RLock()
_history: dict[str, deque[dict[str, Any]]] = {}
_order: deque[str] = deque()
_subscribers: dict[str, list[queue.Queue]] = defaultdict(list)
_latest_run_id: str | None = None


def _trim() -> None:
    while len(_order) > _RUNS:
        old = _order.popleft()
        _history.pop(old, None)
        _subscribers.pop(old, None)


def emit(run_id: str, kind: str, text: str, **data: Any) -> dict[str, Any]:
    """Record one event and wake anyone streaming this run.

    Args:
        run_id: The run this belongs to. ``""`` is ignored.
        kind: A short tag the UI styles on: started, fetched, acted,
            deferred, memory, asked, decided, resumed, completed, failed,
            repaired, note.
        text: One line a person can read.
        **data: Anything structured the UI might want (item_id, action…).
    """
    if not run_id:
        return {}
    global _latest_run_id
    event = {
        "run_id": run_id,
        "kind": kind,
        "text": text,
        "at": datetime.now(UTC).isoformat(),
        "t": time.time(),
        **data,
    }
    with _lock:
        if run_id not in _history:
            _history[run_id] = deque(maxlen=_PER_RUN)
            _order.append(run_id)
            _trim()
        _history[run_id].append(event)
        _latest_run_id = run_id
        for q in list(_subscribers.get(run_id, [])):
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
        for q in list(_subscribers.get("*", [])):
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
    return event


def history(run_id: str) -> list[dict[str, Any]]:
    with _lock:
        return list(_history.get(run_id, ()))


def latest_run_id() -> str | None:
    return _latest_run_id


def subscribe(run_id: str, replay: bool = True, keepalive: float = 15.0) -> Iterator[dict[str, Any]]:
    """Yield events for a run as they happen. ``run_id="*"`` follows every run.

    Yields a ``{"kind": "keepalive"}`` event on idle so an SSE connection stays
    open through proxies; the UI ignores it.
    """
    q: queue.Queue = queue.Queue(maxsize=1000)
    with _lock:
        _subscribers[run_id].append(q)
        backlog = list(_history.get(run_id, ())) if replay and run_id != "*" else []
    try:
        yield from backlog
        while True:
            try:
                yield q.get(timeout=keepalive)
            except queue.Empty:
                yield {"kind": "keepalive", "run_id": run_id, "t": time.time()}
    finally:
        with _lock:
            try:
                _subscribers[run_id].remove(q)
            except ValueError:
                pass


def is_finished(run_id: str) -> bool:
    return any(e["kind"] in ("completed", "failed", "asked") for e in history(run_id))
