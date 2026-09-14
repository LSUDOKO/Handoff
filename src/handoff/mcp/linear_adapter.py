# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Filing a ticket through Linear's own MCP server.

Linear's remote server (``https://mcp.linear.app/mcp``) has no ``create_issue``;
creating and updating are one verb, ``save_issue``, which needs a title and a
team. The team is looked up once from the workspace, and the ticket body is
written from what the run already knows about the item — sender, subject,
preview, the agent's reasoning — so a ticket filed at 08:00 reads like a
person wrote it, and links back to the mail it came from.
"""

from __future__ import annotations

import os
from typing import Any

from handoff.mcp.servers import call_mcp_tool
from handoff.runtime import current_run

_TEAM: dict[str, str] = {}


def default_team() -> str:
    """``LINEAR_TEAM`` if set, else the workspace's first team."""
    if "team" in _TEAM:
        return _TEAM["team"]
    team = os.environ.get("LINEAR_TEAM", "").strip()
    if not team:
        result = call_mcp_tool("linear", "list_teams", {"limit": 5})
        teams = result.get("teams", []) if isinstance(result, dict) else []
        team = (teams[0].get("name") or teams[0].get("id")) if teams else ""
    _TEAM["team"] = team
    return team


def create_issue(item_id: str, params: dict[str, Any]) -> Any:
    ctx = current_run()
    known = ctx.item(item_id) if ctx is not None else {}
    subject = known.get("subject") or params.get("subject") or ""
    sender = known.get("sender") or params.get("sender") or ""
    name = known.get("sender_name") or ""
    preview = known.get("snippet") or params.get("snippet") or ""
    reasoning = params.get("reasoning") or ""
    title = str(params.get("title") or params.get("summary") or subject or f"Follow up: {sender}")[:200]
    who = f"{name} <{sender}>" if name else sender
    description = "\n".join(
        line for line in (
            f"**From:** {who}" if who else "",
            f"**Subject:** {subject}" if subject else "",
            "",
            f"> {preview}" if preview else "",
            "",
            f"**Why it became a ticket:** {reasoning}" if reasoning else "",
            "",
            f"_Filed by Handoff from Gmail message `{item_id}`._",
        )
    ).strip()
    payload: dict[str, Any] = {"title": title, "description": description, "team": default_team()}
    if params.get("priority") in (1, 2, 3, 4):
        payload["priority"] = params["priority"]
    return call_mcp_tool("linear", "save_issue", payload)
