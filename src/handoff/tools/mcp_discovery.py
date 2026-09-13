# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Builder-agent tools for discovering, validating and previewing workflows."""

from __future__ import annotations

import json
from typing import Any

from strands import tool

from handoff.mcp.servers import MCP_SERVERS, registry_snapshot
from handoff.models import TriggerType, WorkflowConfig

_CRON_FIELDS = 5


@tool
def discover_mcp_tools() -> list[dict]:
    """List the integrations available for use in a workflow.

    Call this before proposing a workflow, so you only reference tools the
    user actually has. The `configured` flag says whether credentials are
    present — you may still design around an unconfigured tool, but tell the
    user they'll need to connect it.

    Returns:
        One entry per integration, with its name, description, the actions it
        supports, and whether it is currently configured.
    """
    return registry_snapshot()


def _validate_cron(expr: str) -> list[str]:
    parts = expr.split()
    if len(parts) != _CRON_FIELDS:
        return [
            f"Cron expression '{expr}' has {len(parts)} fields; expected "
            f"{_CRON_FIELDS} (minute hour day-of-month month day-of-week)"
        ]
    return []


def validate_config_dict(config: dict[str, Any]) -> dict[str, Any]:
    """Validate a workflow config dict. Shared by the tool and the UI."""
    errors: list[str] = []
    warnings: list[str] = []

    for required in ("workflow_id", "name", "trigger", "steps"):
        if required not in config:
            errors.append(f"Missing required field '{required}'")

    trigger = config.get("trigger") or {}
    trigger_type = trigger.get("type", "")
    if trigger_type and trigger_type not in {t.value for t in TriggerType}:
        errors.append(
            f"Unknown trigger type '{trigger_type}'; expected one of "
            f"{sorted(t.value for t in TriggerType)}"
        )
    if trigger_type == TriggerType.CRON.value:
        schedule = trigger.get("schedule", "")
        if not schedule:
            errors.append("A cron trigger needs a 'schedule' expression")
        else:
            errors.extend(_validate_cron(schedule))

    tools = config.get("mcp_tools") or []
    if not tools:
        warnings.append("No integrations listed — this workflow can only use built-in tools")
    for name in tools:
        if name not in MCP_SERVERS:
            errors.append(f"Unknown integration '{name}'")
        elif not MCP_SERVERS[name].configured:
            warnings.append(f"Integration '{name}' is not configured yet")

    steps = config.get("steps") or []
    if steps and not any(
        step.get("action") == "interrupt" or step.get("id") == "human_gate" for step in steps
    ):
        warnings.append(
            "No human gate in this workflow — it will act entirely on its own. "
            "That is fine for read-only work, risky for anything irreversible."
        )

    parsed = None
    if not errors:
        try:
            parsed = WorkflowConfig.model_validate(config).model_dump(mode="json")
        except Exception as exc:
            errors.append(f"Schema validation failed: {exc}")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "config": parsed,
    }


@tool
def validate_workflow(config_json: str) -> dict:
    """Check a workflow config before showing it to the user.

    Args:
        config_json: The workflow config, as a JSON string.

    Returns:
        `valid`, a list of blocking `errors`, a list of non-blocking
        `warnings`, and the normalised `config` when it validates.
    """
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        return {"valid": False, "errors": [f"Invalid JSON: {exc}"], "warnings": [], "config": None}

    if not isinstance(config, dict):
        return {
            "valid": False,
            "errors": ["Workflow config must be a JSON object"],
            "warnings": [],
            "config": None,
        }

    return validate_config_dict(config)


def render_preview(config: dict[str, Any]) -> str:
    """Human-readable summary of what a workflow will do. Shared with the UI."""
    trigger = config.get("trigger") or {}
    trigger_type = trigger.get("type", "manual")
    when = {
        "cron": f"on the schedule {trigger.get('schedule', '?')} ({trigger.get('timezone', 'UTC')})",
        "webhook": f"whenever {trigger.get('path', '/hook')} is called",
        "event": "whenever the configured event fires",
        "manual": "only when you run it",
    }.get(trigger_type, "on its configured trigger")

    tools = ", ".join(config.get("mcp_tools") or []) or "built-in tools only"

    gates = [
        step
        for step in config.get("steps") or []
        if step.get("action") == "interrupt" or step.get("id") == "human_gate"
    ]
    auto_rules: list[str] = []
    for step in config.get("steps") or []:
        for rule in step.get("rules") or []:
            if rule.get("auto"):
                auto_rules.append(f"{rule.get('category', '?')} → {rule.get('action', '?')}")

    lines = [
        f"Workflow: {config.get('name', 'Unnamed')}",
        f"Runs {when}.",
        f"Uses: {tools}.",
        "",
        "Handles on its own:",
    ]
    lines += [f"  - {r}" for r in auto_rules] or ["  - (nothing declared as automatic)"]
    lines += ["", "Asks you about:"]
    if gates:
        for gate in gates:
            options = ", ".join(gate.get("options") or [])
            lines.append(
                f"  - {gate.get('category', 'ambiguous')} items"
                + (f" — you choose between: {options}" if options else "")
            )
    else:
        lines.append("  - nothing; this workflow never interrupts you")

    completion = config.get("completion") or {}
    if completion.get("notify") and completion.get("notify") != "none":
        target = completion.get("channel", "")
        lines += ["", f"When it finishes: notifies {completion['notify']} {target}".rstrip()]

    return "\n".join(lines)


@tool
def preview_workflow(config_json: str) -> str:
    """Describe, in plain language, what a workflow config will actually do.

    Show this to the user before saving anything. They should be able to spot
    a misunderstanding here without reading JSON.

    Args:
        config_json: The workflow config, as a JSON string.

    Returns:
        A short readable summary: when it runs, what it handles silently, and
        what it will ask about.
    """
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as exc:
        return f"Could not read that config: {exc}"
    return render_preview(config)
