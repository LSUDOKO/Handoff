# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""A workspace as a file you can read, version, and hand to a teammate.

Conversation is how you build; configuration is how you ship. Everything the
chat produces lands in ``workspace.yml`` — workflows, the skills that encode
its judgement, custom agents, tool servers — and the file round-trips: edit
it and save, export it, bundle it with its skills, import it somewhere else.

Credentials are never in the file. A workspace is shareable; its keys are not.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

import yaml

from handoff.models import WorkflowConfig
from handoff.platform.models import CustomAgent, MCPServerConfig, Skill, Workspace
from handoff.platform.skills import render as render_skill
from handoff.store import get_store
from handoff.tools.mcp_discovery import validate_config_dict

HEADER = """# Handoff workspace — {name}
# Edit and save: the file is the configuration. Credentials live elsewhere.
"""

_WORKFLOW_DROP = {"created_at", "updated_at"}
_SKILL_DROP = {"skill_id", "workspace_id", "created_at", "updated_at", "builtin"}
_AGENT_DROP = {"agent_id", "workspace_id", "created_at", "updated_at", "builtin"}
_SERVER_DROP = {"server_id", "workspace_id", "created_at", "updated_at", "builtin", "last_error", "tool_names", "last_probed"}


def _clean(data: dict[str, Any], drop: set[str]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in drop and v not in (None, "", [], {})}


def document(workspace_id: str) -> dict[str, Any]:
    """The workspace as a plain dict, in the order a person would read it."""
    store = get_store()
    workspace = store.get_workspace(workspace_id)
    if workspace is None:
        raise KeyError(workspace_id)
    return {
        "handoff": 1,
        "workspace": {
            "name": workspace.name,
            "description": workspace.description,
            "color": workspace.color,
        },
        "workflows": [_clean(w.model_dump(mode="json"), _WORKFLOW_DROP) for w in store.list_workflows()],
        "skills": [
            _clean(s.model_dump(mode="json"), _SKILL_DROP)
            for s in store.list_skills(workspace_id)
            if not s.builtin
        ],
        "agents": [
            _clean(a.model_dump(mode="json"), _AGENT_DROP)
            for a in store.list_custom_agents(workspace_id)
            if not a.builtin
        ],
        "tool_servers": [
            _clean(m.model_dump(mode="json"), _SERVER_DROP)
            for m in store.list_mcp_servers(workspace_id)
            if not m.builtin
        ],
    }


def to_yaml(workspace_id: str) -> str:
    doc = document(workspace_id)
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
    return HEADER.format(name=doc["workspace"]["name"]) + body


def parse(text: str) -> dict[str, Any]:
    """Parse YAML (or JSON — it is a subset) and validate what it describes.

    Returns ``{"valid": bool, "errors": [...], "payload": dict}``. Errors are
    for a person: which workflow, which field, what was wrong.
    """
    errors: list[str] = []
    try:
        payload = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [f"Not valid YAML: {exc}"], "payload": {}}
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["The file must be a mapping at the top level."], "payload": {}}

    spec = payload.get("workspace") or {}
    if not isinstance(spec, dict) or not str(spec.get("name", "")).strip():
        errors.append("workspace.name is required.")

    workflows = payload.get("workflows") or []
    if not isinstance(workflows, list):
        errors.append("workflows must be a list.")
        workflows = []
    seen: set[str] = set()
    for index, raw in enumerate(workflows, start=1):
        if not isinstance(raw, dict):
            errors.append(f"workflows[{index}] must be a mapping.")
            continue
        wid = str(raw.get("workflow_id", "")) or f"#{index}"
        if wid in seen:
            errors.append(f"workflow '{wid}' appears twice.")
        seen.add(wid)
        result = validate_config_dict(raw)
        if not result["valid"]:
            errors.extend(f"workflow '{wid}': {e}" for e in result["errors"])

    for index, raw in enumerate(payload.get("skills") or [], start=1):
        if not isinstance(raw, dict) or not raw.get("name") or not raw.get("body"):
            errors.append(f"skills[{index}] needs a name and a body.")
        elif not re.match(r"^[a-z0-9][a-z0-9-]*$", str(raw["name"])):
            errors.append(f"skill '{raw['name']}': names are lowercase-with-dashes.")

    for index, raw in enumerate(payload.get("agents") or [], start=1):
        if not isinstance(raw, dict) or not raw.get("name"):
            errors.append(f"agents[{index}] needs a name.")

    return {"valid": not errors, "errors": errors, "payload": payload}


def apply(workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Make the workspace match the document. The file is the truth.

    Workflows, skills, agents and tool servers named in the file are created
    or updated; ones the workspace had but the file no longer lists are
    removed — otherwise deleting a line would silently do nothing. Built-ins
    are never touched, and neither are credentials.
    """
    store = get_store()
    workspace = store.get_workspace(workspace_id)
    if workspace is None:
        raise KeyError(workspace_id)
    before = document(workspace_id)

    spec = payload.get("workspace") or {}
    workspace.name = str(spec.get("name", workspace.name)).strip() or workspace.name
    workspace.description = str(spec.get("description", workspace.description) or "")
    workspace.color = str(spec.get("color", workspace.color) or "amber")
    workspace.updated_at = datetime.now(UTC)
    store.workspaces.put(workspace, "workspace_id")

    counts = {"workflows": 0, "skills": 0, "agents": 0, "tool_servers": 0, "removed": 0}

    wanted_workflows = {}
    for raw in payload.get("workflows") or []:
        existing = store.get_workflow(str(raw.get("workflow_id", "")))
        data = {**(existing.model_dump(mode="json") if existing else {}), **raw}
        workflow = WorkflowConfig.model_validate(data)
        workflow.updated_at = datetime.now(UTC)
        store.save_workflow(workflow)
        wanted_workflows[workflow.workflow_id] = workflow
        counts["workflows"] += 1
    for old in before["workflows"]:
        if old["workflow_id"] not in wanted_workflows:
            store.workflows.delete("workflow_id", old["workflow_id"])
            counts["removed"] += 1

    existing_skills = {s.name: s for s in store.list_skills(workspace_id) if not s.builtin}
    wanted_skills = set()
    for raw in payload.get("skills") or []:
        skill = existing_skills.get(raw["name"]) or Skill(workspace_id=workspace_id, name=raw["name"], body="")
        for key in ("description", "body", "namespace", "enabled", "tags"):
            if key in raw:
                setattr(skill, key, raw[key])
        skill.updated_at = datetime.now(UTC)
        store.skills.put(skill, "skill_id")
        wanted_skills.add(skill.name)
        counts["skills"] += 1
    for name, skill in existing_skills.items():
        if name not in wanted_skills:
            store.skills.delete("skill_id", skill.skill_id)
            counts["removed"] += 1

    existing_agents = {a.name: a for a in store.list_custom_agents(workspace_id) if not a.builtin}
    wanted_agents = set()
    for raw in payload.get("agents") or []:
        agent = existing_agents.get(raw["name"]) or CustomAgent(workspace_id=workspace_id, name=raw["name"])
        for key in ("description", "system_prompt", "tools", "skills", "model_override", "enabled"):
            if key in raw:
                setattr(agent, key, raw[key])
        agent.updated_at = datetime.now(UTC)
        store.custom_agents.put(agent, "agent_id")
        wanted_agents.add(agent.name)
        counts["agents"] += 1
    for name, agent in existing_agents.items():
        if name not in wanted_agents:
            store.custom_agents.delete("agent_id", agent.agent_id)
            counts["removed"] += 1

    existing_servers = {m.name: m for m in store.list_mcp_servers(workspace_id) if not m.builtin}
    wanted_servers = set()
    for raw in payload.get("tool_servers") or []:
        server = existing_servers.get(raw["name"]) or MCPServerConfig(workspace_id=workspace_id, name=raw["name"])
        for key in ("description", "transport", "command", "args", "url", "required_env", "enabled"):
            if key in raw:
                setattr(server, key, raw[key])
        store.mcp_servers.put(server, "server_id")
        wanted_servers.add(server.name)
        counts["tool_servers"] += 1
    for name, server in existing_servers.items():
        if name not in wanted_servers:
            store.mcp_servers.delete("server_id", server.server_id)
            counts["removed"] += 1

    try:
        from handoff.daemon import sync_schedules

        sync_schedules()
    except Exception:
        pass
    return counts


def bundle(workspace_id: str) -> bytes:
    """A zip: workspace.yml, one Markdown file per skill, one JSON per agent."""
    doc = document(workspace_id)
    store = get_store()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("workspace.yml", to_yaml(workspace_id))
        for skill in store.list_skills(workspace_id):
            if not skill.builtin:
                zf.writestr(f"skills/{skill.name}.md", render_skill(skill))
        for agent in store.list_custom_agents(workspace_id):
            if not agent.builtin:
                zf.writestr(
                    f"agents/{re.sub(r'[^a-z0-9-]+', '-', agent.name.lower()).strip('-')}.json",
                    json.dumps(_clean(agent.model_dump(mode="json"), _AGENT_DROP), indent=2),
                )
        zf.writestr(
            "README.md",
            f"# {doc['workspace']['name']}\n\n{doc['workspace'].get('description', '')}\n\n"
            f"Import with Handoff → Settings → Import, or `handoff workspace import <this zip>`.\n",
        )
    return buf.getvalue()


def import_document(data: bytes | str, filename: str = "") -> dict[str, Any]:
    """Create a new workspace from a YAML/JSON file or a bundle zip."""
    text: str
    if isinstance(data, bytes) and (filename.endswith(".zip") or data[:2] == b"PK"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            main = next((n for n in names if n.endswith("workspace.yml") or n.endswith("workspace.yaml")), None)
            if main is None:
                main = next((n for n in names if n.endswith("workspace.json")), None)
            if main is None:
                raise ValueError("The bundle has no workspace.yml")
            text = zf.read(main).decode("utf-8")
    else:
        text = data.decode("utf-8") if isinstance(data, bytes) else data

    parsed = parse(text)
    if not parsed["valid"]:
        raise ValueError("; ".join(parsed["errors"]))
    payload = parsed["payload"]
    spec = payload.get("workspace") or {}
    workspace = Workspace(
        name=str(spec.get("name", "Imported")),
        description=str(spec.get("description", "") or ""),
        color=str(spec.get("color", "blue") or "blue"),
    )
    store = get_store()
    store.workspaces.put(workspace, "workspace_id")
    from handoff.platform.bootstrap import seed_memory_stores

    seed_memory_stores(workspace.workspace_id)
    counts = apply(workspace.workspace_id, payload)
    return {"workspace_id": workspace.workspace_id, "name": workspace.name, **counts}


def remove(workspace_id: str) -> dict[str, Any]:
    """Delete a workspace and everything scoped to it.

    Workflows are not workspace-scoped in the store, so they stay; the
    workspace's skills, agents, tool servers, chats, memory stores and
    credentials go with it. The default workspace cannot be removed — there
    has to be somewhere to land.
    """
    store = get_store()
    workspace = store.get_workspace(workspace_id)
    if workspace is None:
        raise KeyError(workspace_id)
    if workspace.is_default:
        raise ValueError("The default workspace can't be removed.")

    removed = 0
    for coll, key in (
        (store.skills, "skill_id"),
        (store.custom_agents, "agent_id"),
        (store.mcp_servers, "server_id"),
        (store.memory_stores, "store_id"),
        (store.credentials, "credential_id"),
        (store.schedules, "schedule_id"),
    ):
        for row in coll.all():
            if getattr(row, "workspace_id", "") == workspace_id and not getattr(row, "builtin", False):
                coll.delete(key, getattr(row, key))
                removed += 1
    for chat in store.list_chats(workspace_id):
        store.delete_chat(chat.chat_id)
        removed += 1
    store.workspaces.delete("workspace_id", workspace_id)
    return {"removed": removed, "name": workspace.name}


__all__ = ["apply", "bundle", "document", "import_document", "parse", "remove", "to_yaml"]
