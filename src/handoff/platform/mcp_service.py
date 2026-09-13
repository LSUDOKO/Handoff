# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Tool servers as a catalogue you can inspect and poke.

A server row in the store describes how to reach it; this module turns that
into a live connection, lists what it offers with schemas, calls one tool on
demand so you can see what an agent would see, and reports which workflows
lean on it.
"""

from __future__ import annotations

import json
import os
from typing import Any

from handoff.mcp import servers as registry
from handoff.platform.models import MCPServerConfig
from handoff.store import get_store

_CLIENTS: dict[str, Any] = {}


def is_ready(server: MCPServerConfig) -> bool:
    return all(os.getenv(var) for var in server.required_env) if server.required_env else True


def client_for(server: MCPServerConfig):
    """A Strands MCPClient for a stored server, cached per server id.

    Built-ins go through the registry so they share its clients; a server you
    added by hand is built from its own row, the same two transports.
    """
    if server.builtin and server.name in registry.MCP_SERVERS:
        return registry.get_client(server.name)
    if server.server_id in _CLIENTS:
        return _CLIENTS[server.server_id]

    from strands.tools.mcp import MCPClient

    if server.transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        headers: dict[str, str] = {}
        for var in server.required_env:
            token = os.getenv(var)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                break
        client = MCPClient(lambda: streamablehttp_client(server.url, headers=headers or None))
    else:
        from mcp import StdioServerParameters, stdio_client

        params = StdioServerParameters(command=server.command, args=list(server.args), env=dict(os.environ))
        client = MCPClient(lambda: stdio_client(params))
    client.start()
    _CLIENTS[server.server_id] = client
    return client


def describe_tools(server: MCPServerConfig) -> list[dict[str, Any]]:
    """Every tool the server offers, with its description and input schema."""
    client = client_for(server)
    rows = []
    for tool in client.list_tools_sync():
        spec = getattr(tool, "tool_spec", None) or {}
        schema = spec.get("inputSchema", {}) if isinstance(spec, dict) else {}
        if isinstance(schema, dict) and "json" in schema:
            schema = schema["json"]
        rows.append(
            {
                "name": getattr(tool, "tool_name", spec.get("name", "tool")),
                "description": spec.get("description", "") if isinstance(spec, dict) else "",
                "schema": schema,
                "schema_pretty": json.dumps(schema, indent=2) if schema else "",
                "example": json.dumps(_example(schema), indent=2) if schema else "{}",
            }
        )
    return rows


def _example(schema: dict[str, Any]) -> dict[str, Any]:
    """A starter argument object from a JSON schema, so the form isn't blank."""
    out: dict[str, Any] = {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = set(schema.get("required", []) or [])
    for key, prop in props.items():
        if key not in required and len(props) > 3:
            continue
        kind = prop.get("type", "string") if isinstance(prop, dict) else "string"
        out[key] = {"string": "", "integer": 0, "number": 0, "boolean": False, "array": [], "object": {}}.get(kind, "")
    return out


def probe(server: MCPServerConfig) -> MCPServerConfig:
    """Connect, list tools, and record the outcome on the row."""
    store = get_store()
    try:
        server.tool_names = [t["name"] for t in describe_tools(server)]
        server.last_error = ""
    except Exception as exc:
        server.last_error = str(exc)[:200]
    store.mcp_servers.put(server, "server_id")
    return server


def invoke(server: MCPServerConfig, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call one tool and return what came back, unwrapped for a person."""
    client = client_for(server)
    result = client.call_tool_sync(
        tool_use_id=f"handoff-ui-{server.name}-{tool}", name=tool, arguments=arguments
    )
    texts: list[str] = []
    for block in (result.get("content", []) if isinstance(result, dict) else []) or []:
        if isinstance(block, dict) and "text" in block:
            texts.append(block["text"])
        elif isinstance(block, dict) and "json" in block:
            texts.append(json.dumps(block["json"], indent=2))
    status = result.get("status", "success") if isinstance(result, dict) else "success"
    return {"status": status, "text": "\n".join(texts) or json.dumps(result, indent=2, default=str)}


def usage_of(server: MCPServerConfig) -> list[dict[str, Any]]:
    """Workflows that name this server in their tools."""
    return [
        {"workflow_id": w.workflow_id, "name": w.name, "schedule": w.trigger.schedule}
        for w in get_store().list_workflows()
        if server.name in (w.mcp_tools or [])
    ]


def registry_catalogue() -> list[dict[str, Any]]:
    """The built-in registry, marked with what's already installed."""
    installed = {s.name for s in get_store().mcp_servers.all()}
    return [{**row, "installed": row["name"] in installed} for row in registry.registry_snapshot()]


def install_from_registry(name: str, workspace_id: str = "") -> MCPServerConfig:
    spec = registry.MCP_SERVERS.get(name)
    if spec is None:
        raise KeyError(name)
    server = MCPServerConfig(
        workspace_id=workspace_id,
        name=spec.name,
        description=spec.description,
        transport=spec.transport,
        command=spec.command,
        args=list(spec.args),
        url=spec.url,
        required_env=list(spec.required_env),
        builtin=True,
    )
    get_store().mcp_servers.put(server, "server_id")
    return server
