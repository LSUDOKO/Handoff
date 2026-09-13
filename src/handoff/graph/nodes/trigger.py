# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Trigger node — confirms the workflow was woken for a legitimate reason."""

from __future__ import annotations

from datetime import UTC, datetime

from strands import tool


@tool
def check_trigger(trigger_type: str, payload: dict | None = None) -> dict:
    """Confirm the workflow's trigger condition is satisfied.

    Args:
        trigger_type: One of "cron", "webhook", "event" or "manual".
        payload: The raw signal body, for webhook and event triggers.

    Returns:
        A dict with `triggered` (bool), the trigger type, the reason, and an
        ISO-8601 timestamp of when the check ran.
    """
    payload = payload or {}
    now = datetime.now(UTC).isoformat()

    if trigger_type == "cron":
        # The schedule already fired to start this process; nothing to verify.
        return {
            "triggered": True,
            "trigger_type": trigger_type,
            "reason": "Scheduled trigger fired",
            "timestamp": now,
        }

    if trigger_type in ("webhook", "event"):
        triggered = bool(payload)
        return {
            "triggered": triggered,
            "trigger_type": trigger_type,
            "reason": "Signal payload received" if triggered else "Empty signal payload",
            "timestamp": now,
        }

    return {
        "triggered": True,
        "trigger_type": trigger_type or "manual",
        "reason": "Manual run requested by the user",
        "timestamp": now,
    }
