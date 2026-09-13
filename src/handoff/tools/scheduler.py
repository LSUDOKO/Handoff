# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Turning a workflow's cron trigger into a real EventBridge schedule.

Local runs don't need this — ``scripts/run_local.py`` fires a workflow
directly. It exists so that "every weekday at 8am" means the same thing after
deployment as it did in the chat where the user said it.
"""

from __future__ import annotations

import json
from typing import Any

from strands import tool

from handoff import config
from handoff.models import TriggerType, WorkflowConfig


def cron_to_eventbridge(expression: str, timezone: str = "UTC") -> str:
    """Convert a 5-field Unix cron expression to an EventBridge schedule.

    EventBridge uses a 6-field cron where day-of-week and day-of-month are
    mutually exclusive — exactly one must be the literal ``?``.
    """
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError(f"Expected a 5-field cron expression, got: {expression!r}")

    minute, hour, dom, month, dow = parts
    if dow in ("*", "?"):
        dow = "?"
    elif dom == "*":
        dom = "?"
    else:
        dow = "?"

    # EventBridge counts days of the week 1-7 starting on Sunday; Unix cron
    # counts 0-6 starting on Sunday.
    if dow != "?":
        dow = ",".join(
            "-".join(str(int(n) + 1) if n.isdigit() else n for n in token.split("-"))
            for token in dow.split(",")
        )

    return f"cron({minute} {hour} {dom} {month} {dow} *)"


def schedule_name(workflow_id: str) -> str:
    return f"handoff-{workflow_id}"[:64]


def create_schedule(workflow: WorkflowConfig, target_arn: str, role_arn: str) -> dict[str, Any]:
    """Create or update the EventBridge schedule for a cron workflow."""
    if workflow.trigger.type is not TriggerType.CRON:
        return {"scheduled": False, "reason": "Workflow is not cron-triggered"}

    import boto3

    client = boto3.client("scheduler", region_name=config.AWS_REGION)
    name = schedule_name(workflow.workflow_id)
    params = {
        "Name": name,
        "ScheduleExpression": cron_to_eventbridge(
            workflow.trigger.schedule, workflow.trigger.timezone
        ),
        "ScheduleExpressionTimezone": workflow.trigger.timezone or "UTC",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {
            "Arn": target_arn,
            "RoleArn": role_arn,
            "Input": json.dumps(
                {"type": "tick", "workflow_id": workflow.workflow_id}
            ),
        },
        "State": "ENABLED" if workflow.status.value == "active" else "DISABLED",
    }

    try:
        client.create_schedule(**params)
        action = "created"
    except client.exceptions.ConflictException:
        client.update_schedule(**params)
        action = "updated"

    return {"scheduled": True, "name": name, "action": action}


def delete_schedule(workflow_id: str) -> dict[str, Any]:
    import boto3

    client = boto3.client("scheduler", region_name=config.AWS_REGION)
    name = schedule_name(workflow_id)
    try:
        client.delete_schedule(Name=name)
        return {"deleted": True, "name": name}
    except Exception as exc:
        return {"deleted": False, "name": name, "error": str(exc)}


@tool
def describe_schedule(cron_expression: str, timezone: str = "UTC") -> dict:
    """Explain what a cron expression means and how it will be scheduled.

    Use this to read a schedule back to the user in words before saving it —
    "0 8 * * 1-5" is not something most people can check at a glance.

    Args:
        cron_expression: A 5-field Unix cron expression.
        timezone: IANA timezone name, e.g. "America/New_York".

    Returns:
        The EventBridge form of the schedule, and a plain-English reading, or
        an error if the expression is malformed.
    """
    try:
        eventbridge = cron_to_eventbridge(cron_expression, timezone)
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}

    minute, hour, dom, month, dow = cron_expression.split()
    day_names = {
        "1-5": "every weekday",
        "0": "every Sunday", "1": "every Monday", "2": "every Tuesday",
        "3": "every Wednesday", "4": "every Thursday", "5": "every Friday",
        "6": "every Saturday",
        "*": "every day", "?": "every day",
    }
    when = day_names.get(dow, f"on days-of-week {dow}")
    if dom not in ("*", "?"):
        when = f"on day {dom} of the month"
    if month not in ("*", "?"):
        when += f" in month {month}"

    try:
        readable = f"At {int(hour):02d}:{int(minute):02d} {timezone}, {when}"
    except ValueError:
        readable = f"At minute {minute}, hour {hour} {timezone}, {when}"

    return {
        "valid": True,
        "cron": cron_expression,
        "timezone": timezone,
        "eventbridge": eventbridge,
        "readable": readable,
    }
