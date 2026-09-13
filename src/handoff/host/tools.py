# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Exposing a host runtime's authenticated tools to a Strands agent.

Handoff can run embedded in another agent runtime — one that already holds the
user's OAuth tokens and exposes them as MCP tools. When it does, it should not
be managing credentials itself: the host already did that when the person
clicked **Connect** on Gmail, and it refreshes the token when it expires.

This module adapts those tools to ``strands.types.tools.AgentTool`` so the
executor calls them exactly as it calls its own ``@tool`` functions. The
alternative — Handoff keeping a second copy of every credential in its own
``.env`` — means two places to rotate a token and two places to get it wrong.

    ctx.tools.list()  ──▶  HostTool(AgentTool)  ──▶  Agent(tools=[…])
    ctx.tools.call()  ◀──  tool_use from the model

A host context needs only two things, which is the whole protocol:

    ctx.tools.list()            -> objects with .name, .description, .input_schema
    ctx.tools.call(name, args)  -> dict (MCP-shaped content, or plain)

Tool names are filtered before they reach the model. A host may expose dozens
across every connected integration, and an executor that can see all of them
will wander; it only needs the ones its workflow declared.
"""

from __future__ import annotations

import json
from typing import Any

from strands.types._events import ToolResultEvent
from strands.types.tools import AgentTool, ToolResult, ToolSpec, ToolUse

#: The host's own human-input tool. Handoff drives this through the HITL gate
#: rather than letting the model call it directly — an agent that can ask
#: arbitrary questions whenever it likes is precisely what the gate is there to
#: prevent.
RESERVED_TOOLS = {"request_human_input"}

#: Which host tools each declared integration should contribute. Matched as
#: prefixes and substrings against the tool names the host reports, because
#: naming differs between MCP servers (`gmail_search` vs `search_messages`).
INTEGRATION_HINTS: dict[str, tuple[str, ...]] = {
    "gmail": ("gmail", "message", "thread", "draft", "email", "label"),
    "linear": ("linear", "issue", "ticket", "project", "team"),
    "slack": ("slack", "channel", "post_message"),
    "github": ("github", "pull", "pr_", "repo", "issue"),
    "notion": ("notion", "page", "database"),
    "browser": ("browse", "navigate", "fetch_page", "screenshot"),
}


def _unwrap(result: Any) -> str:
    """Flatten an MCP-shaped result into text the model can read."""
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if parts:
                return "\n".join(parts)
        return json.dumps(result, default=str)
    return str(result)


def _is_error(result: Any) -> bool:
    return isinstance(result, dict) and bool(result.get("isError"))


class HostTool(AgentTool):
    """One host tool, callable by a Strands agent."""

    def __init__(self, tools: Any, name: str, description: str, input_schema: dict) -> None:
        super().__init__()
        self._tools = tools
        self._name = name
        self._description = description or f"Call the {name} tool."
        self._input_schema = input_schema or {"type": "object", "properties": {}}

    @property
    def tool_name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> str:
        return "handoff_host"

    @property
    def tool_spec(self) -> ToolSpec:
        return {
            "name": self._name,
            "description": self._description,
            "inputSchema": {"json": self._input_schema},
        }

    async def stream(self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any):
        tool_use_id = tool_use["toolUseId"]
        try:
            raw = self._tools.call(self._name, tool_use.get("input", {}) or {})
        except Exception as exc:
            # Surface the failure to the model as a tool error rather than
            # raising: a dead integration should make the agent report that it
            # could not act, not crash the whole run mid-inbox.
            yield ToolResultEvent(
                ToolResult(
                    toolUseId=tool_use_id,
                    status="error",
                    content=[{"text": f"{self._name} failed: {exc}"}],
                )
            )
            return

        yield ToolResultEvent(
            ToolResult(
                toolUseId=tool_use_id,
                status="error" if _is_error(raw) else "success",
                content=[{"text": _unwrap(raw)}],
            )
        )


def _wanted(name: str, integrations: list[str]) -> bool:
    """Does this host tool belong to one of the declared integrations?"""
    if not integrations:
        return True
    lowered = name.lower()
    for integration in integrations:
        for hint in INTEGRATION_HINTS.get(integration, (integration,)):
            if hint in lowered:
                return True
    return False


def load_host_tools(ctx: Any, integrations: list[str] | None = None) -> list[HostTool]:
    """Adapt the host's tools for one workflow's declared integrations.

    Args:
        ctx: The host's agent context (see the protocol above).
        integrations: The workflow's ``mcp_tools`` list. Empty means "everything
            the host offers", which is rarely what you want.

    Returns:
        Strands tools, ready for ``Agent(tools=…)``. Returns an empty list —
        never raises — if the host has nothing connected, so a workflow with
        no integrations still runs and reports that it could not act.
    """
    try:
        available = ctx.tools.list()
    except Exception as exc:
        print(f"[handoff] could not list host tools: {exc}")
        return []

    adapted: list[HostTool] = []
    for definition in available:
        name = getattr(definition, "name", "")
        if not name or name in RESERVED_TOOLS:
            continue
        if not _wanted(name, integrations or []):
            continue
        adapted.append(
            HostTool(
                ctx.tools,
                name,
                getattr(definition, "description", ""),
                getattr(definition, "input_schema", None) or {},
            )
        )
    return adapted


def describe(tools: list[HostTool]) -> str:
    """A line for the executor's prompt, so it knows what it actually has."""
    if not tools:
        return (
            "No integrations are connected. You cannot take real actions this "
            "run — classify the items, then say plainly what you would have "
            "done and that nothing was carried out."
        )
    names = ", ".join(t.tool_name for t in tools)
    return f"Connected tools you may call directly: {names}"
