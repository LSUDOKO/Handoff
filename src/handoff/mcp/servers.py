# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""MCP server registry.

Handoff's tools are MCP servers rather than hard-coded API clients, which is
what lets a workflow the Builder wrote on one machine run on another with a
different set of integrations. Adding Notion support should be a registry
entry and a credential, not a code change in the executor.

Connections are opened lazily and cached for the life of the process; an MCP
stdio server costs a subprocess, so a run that touches Gmail three times should
not spawn three of them.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any

from handoff import config


@dataclass
class MCPServerSpec:
    """Everything needed to describe, launch and reason about one MCP server."""

    name: str
    description: str
    actions: list[str]
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    #: Environment variables that must be present for this server to work.
    required_env: list[str] = field(default_factory=list)

    #: A Python module that must be importable for this server to launch.
    python_module: str = ""

    @property
    def configured(self) -> bool:
        if self.python_module:
            return importlib.util.find_spec(self.python_module) is not None
        if self.transport == "stdio" and self.command:
            if shutil.which(self.command) is None:
                return False
        return all(os.getenv(var) for var in self.required_env)


MCP_SERVERS: dict[str, MCPServerSpec] = {
    "gmail": MCPServerSpec(
        name="gmail",
        description="Read, search, archive, draft and send email",
        actions=["search_threads", "get_message", "archive", "create_draft", "send", "add_label"],
        command="npx",
        args=["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
        required_env=["GMAIL_OAUTH_TOKEN"],
    ),
    "linear": MCPServerSpec(
        name="linear",
        # Linear's own remote MCP server. The path is /mcp, not /sse —
        # verified against Linear's published endpoint rather than guessed.
        description="Create, update and search Linear issues and projects",
        actions=["create_issue", "update_issue", "search_issues", "list_teams"],
        transport="http",
        url="https://mcp.linear.app/mcp",
        required_env=["LINEAR_API_KEY"],
    ),
    "slack": MCPServerSpec(
        name="slack",
        # Slack has no maintained MCP server — @modelcontextprotocol/server-slack
        # was deprecated upstream ("no longer supported"). Handoff talks to the
        # Slack Web API directly instead, in handoff.tools.slack.
        description="Post messages and read channels in Slack",
        actions=["post_message", "read_channel", "list_channels"],
        transport="builtin",
        required_env=["SLACK_BOT_TOKEN"],
    ),
    "github": MCPServerSpec(
        name="github",
        # GitHub's official remote MCP server. The old npm package
        # @modelcontextprotocol/server-github is deprecated upstream.
        description="Manage pull requests, issues and code review on GitHub",
        actions=["list_prs", "create_issue", "review_pr", "get_file"],
        transport="http",
        url="https://api.githubcopilot.com/mcp/",
        required_env=["GITHUB_TOKEN"],
    ),
    "web": MCPServerSpec(
        name="web",
        # The reference MCP fetch server, run in-process from this Python
        # environment. Needs no credentials, which makes it the one
        # integration a fresh clone can exercise for real: the competitor
        # pricing workflow reads a live page through it.
        description="Fetch a web page as readable text (no credentials needed)",
        actions=["fetch"],
        command=sys.executable,
        args=["-m", "mcp_server_fetch"],
        python_module="mcp_server_fetch",
    ),
    "browser": MCPServerSpec(
        name="browser",
        description="Browse web pages, extract text and take screenshots (AgentCore Browser)",
        actions=["navigate", "extract_text", "screenshot"],
        transport="builtin",
    ),
    "code_interpreter": MCPServerSpec(
        name="code_interpreter",
        description="Run Python for data processing and report generation (AgentCore Code Interpreter)",
        actions=["run_python", "read_file", "write_file"],
        transport="builtin",
    ),
}


_CLIENTS: dict[str, Any] = {}


def get_client(server: str):
    """Open (or reuse) a Strands ``MCPClient`` for one registered server."""
    if server in _CLIENTS:
        return _CLIENTS[server]

    spec = MCP_SERVERS.get(server)
    if spec is None:
        raise KeyError(f"Unknown MCP server '{server}'")
    if spec.transport == "builtin":
        raise ValueError(
            f"'{server}' is an AgentCore capability, not an MCP server; "
            "call it through its dedicated tool instead"
        )

    from strands.tools.mcp import MCPClient

    if spec.transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        # Remote MCP servers authenticate with a bearer token. Which env var
        # holds it is part of the spec, so adding a server is a registry entry
        # rather than a branch here.
        headers: dict[str, str] = {}
        for var in spec.required_env:
            token = os.getenv(var)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                break

        client = MCPClient(lambda: streamablehttp_client(spec.url, headers=headers or None))
    else:
        from mcp import StdioServerParameters, stdio_client

        params = StdioServerParameters(command=spec.command, args=spec.args, env=dict(os.environ))
        client = MCPClient(lambda: stdio_client(params))

    client.start()
    _CLIENTS[server] = client
    return client


def call_mcp_tool(server: str, operation: str, params: dict[str, Any]) -> Any:
    """Call one operation on one MCP server and unwrap the result content."""
    client = get_client(server)
    result = client.call_tool_sync(
        tool_use_id=f"handoff-{server}-{operation}", name=operation, arguments=params
    )

    texts: list[str] = []
    for block in result.get("content", []) if isinstance(result, dict) else []:
        if isinstance(block, dict) and "text" in block:
            texts.append(block["text"])
    if not texts:
        return result

    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return {"text": joined}


def load_agent_tools(servers: list[str]) -> list[Any]:
    """Return Strands tool objects for the given servers, for ``Agent(tools=…)``.

    Servers that are not configured are skipped rather than raising: a
    workflow that names four integrations should still run with the two the
    user has actually connected, and say so.
    """
    tools: list[Any] = []
    for name in servers:
        spec = MCP_SERVERS.get(name)
        if spec is None or spec.transport == "builtin" or not spec.configured:
            continue
        # In mock mode, only credential-free servers are opened. A demo on
        # synthetic mail can still read a real web page.
        if config.USE_MOCK_TOOLS and spec.required_env:
            continue
        try:
            tools.extend(get_client(name).list_tools_sync())
        except Exception as exc:
            print(f"[handoff] MCP server '{name}' unavailable: {exc}")
    return tools


def shutdown() -> None:
    """Close every open MCP connection. Called on process exit."""
    for name, client in list(_CLIENTS.items()):
        try:
            client.stop(None, None, None)
        except Exception:
            pass
        _CLIENTS.pop(name, None)


def registry_snapshot() -> list[dict[str, Any]]:
    """The registry as plain data — for the Builder agent and the dashboard."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "actions": spec.actions,
            "transport": spec.transport,
            "configured": spec.configured,
            "requires": spec.required_env,
        }
        for spec in MCP_SERVERS.values()
    ]
