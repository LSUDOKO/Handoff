# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Workspaces you can start from instead of a blank page.

Every template here is a complete, working setup — workflows, the skills that
encode its judgement, and the integrations it expects. Importing one gives
you something that runs today and that you then edit, which is a better
starting point than an empty workspace and a text box.
"""

from __future__ import annotations

import json
from typing import Any

from handoff import config
from handoff.models import WorkflowConfig
from handoff.platform.models import Skill, Workspace
from handoff.store import get_store

TEMPLATES: list[dict[str, Any]] = [
    {
        "slug": "inbox-zero",
        "name": "Inbox Zero",
        "tagline": "Triage the morning's mail before standup.",
        "description": (
            "Files real asks as tickets, archives the noise, drafts replies to "
            "your manager, and asks you about anything it genuinely can't call. "
            "The one to start with."
        ),
        "icon": "✉",
        "workflows": ["inbox-triage-morning"],
        "skills": ["sender-trust", "escalation-style"],
        "integrations": ["gmail", "linear", "slack"],
    },
    {
        "slug": "competitive-intel",
        "name": "Competitive Intel",
        "tagline": "Watch a competitor's pricing, weekly.",
        "description": (
            "Reads the page every Monday, says nothing if nothing moved, and "
            "summarises the diff when it did. Asks before posting anything that "
            "reads as a strategic call. Uses the credential-free web fetch tool, "
            "so it works on a fresh install."
        ),
        "icon": "◑",
        "workflows": ["competitor-pricing-watch"],
        "skills": ["irreversibility"],
        "integrations": ["web", "slack"],
    },
    {
        "slug": "engineering-ops",
        "name": "Engineering Ops",
        "tagline": "PR review triage and a Slack digest.",
        "description": (
            "First-pass review comments on small PRs from teammates; anything "
            "touching auth, billing or migrations gets flagged to you before a "
            "word is posted. Plus an evening digest of the channels you can't "
            "keep up with."
        ),
        "icon": "◈",
        "workflows": ["pr-review-triage", "slack-channel-digest"],
        "skills": ["irreversibility", "escalation-style"],
        "integrations": ["github", "slack", "linear"],
    },
    {
        "slug": "meeting-followup",
        "name": "Meeting Follow-up",
        "tagline": "Turn notes into commitments, automatically.",
        "description": (
            "After a meeting, pulls the commitments out of the notes, files "
            "yours as tickets, and drafts a recap. Asks before anything goes to "
            "someone outside the company."
        ),
        "icon": "◐",
        "workflows": ["meeting-followup"],
        "skills": ["irreversibility"],
        "integrations": ["gmail", "linear"],
    },
]


def catalogue() -> list[dict[str, Any]]:
    """Templates, each marked with whether it's already been imported."""
    store = get_store()
    have = {w.workflow_id for w in store.list_workflows()}
    rows = []
    for template in TEMPLATES:
        installed = all(w in have for w in template["workflows"])
        rows.append({**template, "installed": installed})
    return rows


def get(slug: str) -> dict[str, Any] | None:
    return next((t for t in TEMPLATES if t["slug"] == slug), None)


def _shipped_workflow(workflow_id: str) -> WorkflowConfig | None:
    path = config.WORKFLOWS_DIR
    for candidate in sorted(path.glob("*.json")):
        try:
            data = json.loads(candidate.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("workflow_id") == workflow_id:
            return WorkflowConfig.model_validate(data)
    return None


def install(slug: str, workspace_id: str = "") -> dict[str, Any]:
    """Import a template into a workspace.

    Creates the workspace if one isn't named, copies the workflows in, and
    enables the skills the template relies on. Idempotent: importing twice
    does not duplicate anything.
    """
    template = get(slug)
    if template is None:
        raise KeyError(slug)

    store = get_store()
    if not workspace_id:
        workspace = Workspace(
            name=template["name"],
            description=template["tagline"],
            icon=template.get("icon", "◆"),
        )
        store.workspaces.put(workspace, "workspace_id")
        workspace_id = workspace.workspace_id

    added: list[str] = []
    for workflow_id in template["workflows"]:
        if store.get_workflow(workflow_id) is not None:
            continue
        workflow = _shipped_workflow(workflow_id)
        if workflow is None:
            continue
        store.save_workflow(workflow)
        added.append(workflow.workflow_id)

    enabled: list[str] = []
    wanted = set(template.get("skills", []))
    for skill in store.skills.all():
        if skill.name in wanted and not skill.enabled:
            skill.enabled = True
            store.skills.put(skill, "skill_id")
            enabled.append(skill.name)

    return {
        "slug": slug,
        "workspace_id": workspace_id,
        "workflows_added": added,
        "skills_enabled": enabled,
    }


def export_workspace(workspace_id: str) -> dict[str, Any]:
    """A workspace as portable JSON — the thing you hand a teammate."""
    store = get_store()
    workspace = store.get_workspace(workspace_id)
    if workspace is None:
        raise KeyError(workspace_id)

    return {
        "handoff_version": 1,
        "workspace": workspace.model_dump(mode="json", exclude={"workspace_id"}),
        "workflows": [w.model_dump(mode="json") for w in store.list_workflows()],
        "skills": [
            s.model_dump(mode="json", exclude={"skill_id", "workspace_id"})
            for s in store.list_skills(workspace_id)
            if not s.builtin
        ],
        "agents": [
            a.model_dump(mode="json", exclude={"agent_id", "workspace_id"})
            for a in store.list_custom_agents(workspace_id)
            if not a.builtin
        ],
        # Credentials are deliberately absent. A workspace is shareable; the
        # keys it runs with are not.
    }


def import_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    """The other half of export — rebuild a workspace from portable JSON."""
    store = get_store()
    spec = payload.get("workspace") or {}
    workspace = Workspace(
        name=spec.get("name", "Imported"),
        description=spec.get("description", ""),
        icon=spec.get("icon", "◆"),
    )
    store.workspaces.put(workspace, "workspace_id")

    for raw in payload.get("workflows", []):
        try:
            store.save_workflow(WorkflowConfig.model_validate(raw))
        except Exception:
            continue

    for raw in payload.get("skills", []):
        try:
            store.skills.put(
                Skill(workspace_id=workspace.workspace_id, **raw), "skill_id"
            )
        except Exception:
            continue

    return {"workspace_id": workspace.workspace_id, "name": workspace.name}
