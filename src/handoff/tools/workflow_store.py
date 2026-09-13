# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Saving and loading workflow configs — the Builder agent's output tools."""

from __future__ import annotations

import json
from pathlib import Path

from strands import tool

from handoff import config as cfg
from handoff.models import WorkflowConfig, WorkflowStatus
from handoff.store import get_store
from handoff.tools.mcp_discovery import validate_config_dict


@tool
def save_workflow(config_json: str, activate: bool = False) -> dict:
    """Save a validated workflow so it can be run and scheduled.

    Only call this once the user has seen a preview and agreed to it.

    Args:
        config_json: The workflow config, as a JSON string.
        activate: Whether to mark it active immediately. Leave false to save
            it as a draft the user can review first.

    Returns:
        Whether the save succeeded, the workflow id, and any validation errors.
    """
    result = validate_config_dict(json.loads(config_json)) if config_json.strip() else {
        "valid": False,
        "errors": ["Empty config"],
    }
    if not result.get("valid"):
        return {"saved": False, "errors": result.get("errors", []), "workflow_id": None}

    workflow = WorkflowConfig.model_validate(result["config"])
    workflow.status = WorkflowStatus.ACTIVE if activate else WorkflowStatus.DRAFT
    get_store().save_workflow(workflow)

    return {
        "saved": True,
        "workflow_id": workflow.workflow_id,
        "status": workflow.status.value,
        "warnings": result.get("warnings", []),
    }


@tool
def list_workflows() -> list[dict]:
    """List the workflows this user already has.

    Returns:
        Each workflow's id, name, status, trigger and integrations.
    """
    return [
        {
            "workflow_id": w.workflow_id,
            "name": w.name,
            "description": w.description,
            "status": w.status.value,
            "trigger": w.trigger.model_dump(mode="json"),
            "mcp_tools": w.mcp_tools,
        }
        for w in get_store().list_workflows()
    ]


def load_workflow_file(path: str | Path) -> WorkflowConfig:
    """Load one workflow config from a JSON file on disk."""
    data = json.loads(Path(path).read_text())
    return WorkflowConfig.model_validate(data)


def load_example_workflows() -> list[WorkflowConfig]:
    """Load every example config shipped in ``workflows/examples``."""
    if not cfg.WORKFLOWS_DIR.exists():
        return []
    out: list[WorkflowConfig] = []
    for path in sorted(cfg.WORKFLOWS_DIR.glob("*.json")):
        try:
            out.append(load_workflow_file(path))
        except Exception as exc:
            print(f"[handoff] skipping {path.name}: {exc}")
    return out


def seed_examples(activate: bool = True) -> list[WorkflowConfig]:
    """Load the example workflows into the store if they aren't there yet."""
    store = get_store()
    seeded: list[WorkflowConfig] = []
    for workflow in load_example_workflows():
        if store.get_workflow(workflow.workflow_id) is None:
            workflow.status = WorkflowStatus.ACTIVE if activate else WorkflowStatus.DRAFT
            store.save_workflow(workflow)
            seeded.append(workflow)
    return seeded
