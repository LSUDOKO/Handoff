# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""First-run setup.

A fresh install should be usable immediately, not a set of empty screens with
"create your first…" in the middle of each. So on first start Handoff creates
a default workspace, loads the shipped workflows and skills, registers the
MCP servers it knows about, adopts any credentials already in the
environment, and gives every cron workflow a live schedule.

Everything is idempotent — this runs on every start, and does nothing the
second time.
"""

from __future__ import annotations

from typing import Any

from handoff.platform import credentials as creds
from handoff.platform.agents_registry import seed_builtin_agents
from handoff.platform.models import MCPServerConfig, MemoryStore
from handoff.platform.skills import seed_builtin_skills
from handoff.store import get_store


def seed_mcp_servers(workspace_id: str = "") -> list[MCPServerConfig]:
    """Register the built-in MCP registry as editable server entries."""
    from handoff.mcp.servers import MCP_SERVERS

    store = get_store()
    existing = {s.name for s in store.mcp_servers.all()}
    created: list[MCPServerConfig] = []

    for name, spec in MCP_SERVERS.items():
        if name in existing:
            continue
        server = MCPServerConfig(
            workspace_id=workspace_id,
            name=name,
            description=spec.description,
            transport=spec.transport,
            command=spec.command,
            args=list(spec.args),
            url=spec.url,
            required_env=list(spec.required_env),
            tool_names=list(spec.actions),
            enabled=True,
            builtin=True,
        )
        store.mcp_servers.put(server, "server_id")
        created.append(server)
    return created


def seed_memory_stores(workspace_id: str) -> list[MemoryStore]:
    """The two stores every workspace starts with.

    Short-term is one run's working notes. Long-term is what the agent is
    allowed to carry into the next run — which is where learned rules live,
    and why it is the one worth looking at.
    """
    store = get_store()
    existing = {m.name for m in store.list_memory_stores(workspace_id)}
    created: list[MemoryStore] = []
    for name, kind, description in (
        ("notes", "short_term", "Working notes within a single run."),
        ("preferences", "long_term", "Rules learned from your decisions."),
    ):
        if name in existing:
            continue
        memory = MemoryStore(
            workspace_id=workspace_id,
            name=name,
            kind=kind,
            description=description,
        )
        store.memory_stores.put(memory, "store_id")
        created.append(memory)
    return created


def bootstrap() -> dict[str, Any]:
    """Bring a fresh install up to a usable state. Safe on every start."""
    from handoff.daemon import sync_schedules
    from handoff.tools.workflow_store import seed_examples

    store = get_store()
    workspace = store.default_workspace()

    result = {
        "workspace": workspace.name,
        "workspace_id": workspace.workspace_id,
        "workflows": [w.workflow_id for w in seed_examples()],
        "skills": [s.name for s in seed_builtin_skills()],
        "agents": [a.name for a in seed_builtin_agents(workspace.workspace_id)],
        "mcp_servers": [s.name for s in seed_mcp_servers(workspace.workspace_id)],
        "memory_stores": [m.name for m in seed_memory_stores(workspace.workspace_id)],
        "credentials": [c.provider for c in creds.adopt_environment(workspace.workspace_id)],
        "schedules": [s.workflow_id for s in sync_schedules()],
    }
    creds.apply_credentials()
    return result
