# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Executor node tools — how the workflow reaches the outside world.

Every function here has two bodies: a synthetic one for the demo and the test
suite, and a real one that routes through an MCP server. The switch is
``USE_MOCK_TOOLS``; the tool signature the model sees is identical either way,
which is the point of putting MCP behind the tool boundary.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from handoff import config, events
from handoff.runtime import current_run
from handoff.tools.mock_data import (
    MOCK_EMAILS,
    MOCK_PRICING_PREVIOUS,
    MOCK_PRICING_SNAPSHOT,
)


@tool
def fetch_unread_emails(
    query: str = "is:unread newer_than:12h", max_results: int = 20
) -> list[dict]:
    """Fetch unread inbox messages to triage.

    Args:
        query: Gmail-style search, e.g. "is:unread newer_than:12h".
        max_results: Cap on messages returned.
    """
    if config.USE_MOCK_TOOLS:
        messages = MOCK_EMAILS[:max_results]
    else:
        from handoff.mcp.servers import call_mcp_tool

        result = call_mcp_tool(
            "gmail", "search_threads", {"query": query, "max_results": max_results}
        )
        messages = list(result.get("messages", result) if isinstance(result, dict) else result)
        messages = messages[:max_results]

    ctx = current_run()
    if ctx is not None:
        ctx.remember_items(messages)
        events.emit(
            ctx.run_id, "fetched",
            f"Fetched {len(messages)} unread message{'s' if len(messages) != 1 else ''}"
            + (" (synthetic inbox)" if config.USE_MOCK_TOOLS else ""),
            count=len(messages),
        )

    # The model sees only what it needs to judge. Timestamps and thread
    # metadata stay in the run context for tools that want them.
    return [
        {
            "email_id": m.get("email_id"),
            "from": m.get("sender"),
            "name": m.get("sender_name", ""),
            "subject": m.get("subject"),
            "preview": m.get("snippet", ""),
            "labels": m.get("labels", []),
        }
        for m in messages
    ]


@tool
def get_email_body(email_id: str) -> dict:
    """Fetch one message's full body when the preview isn't enough.

    Args:
        email_id: Id from fetch_unread_emails.
    """
    if config.USE_MOCK_TOOLS:
        for email in MOCK_EMAILS:
            if email["email_id"] == email_id:
                return {
                    "email_id": email_id,
                    "body": email["snippet"],
                    "truncated": False,
                }
        return {"email_id": email_id, "error": "not found"}

    from handoff.mcp.servers import call_mcp_tool

    return call_mcp_tool("gmail", "get_message", {"id": email_id})


@tool
def check_competitor_pricing(url: str) -> dict:
    """Read a competitor's pricing page and diff it against the last snapshot.

    Used by the competitor-monitor workflow. In production this drives a real
    headless browser (AgentCore Browser); in mock mode it replays a fixture.

    Args:
        url: The pricing page to inspect.

    Returns:
        A dict with the current tiers, whether anything changed, and a
        human-readable diff of what moved.
    """
    if config.USE_MOCK_TOOLS:
        current, previous = MOCK_PRICING_SNAPSHOT, MOCK_PRICING_PREVIOUS
    else:
        from handoff.tools.browser import capture_pricing, load_previous_snapshot

        current = capture_pricing(url)
        previous = load_previous_snapshot(url)

    diffs: list[str] = []
    previous_by_name: dict[str, Any] = {t["name"]: t for t in previous.get("tiers", [])}
    for tier in current.get("tiers", []):
        was = previous_by_name.get(tier["name"])
        if was is None:
            diffs.append(f"New tier '{tier['name']}' at ${tier['price']}/{tier['period']}")
        elif was["price"] != tier["price"]:
            diffs.append(
                f"{tier['name']} moved from ${was['price']} to "
                f"${tier['price']}/{tier['period']}"
            )

    current_names = {t["name"] for t in current.get("tiers", [])}
    for name in previous_by_name:
        if name not in current_names:
            diffs.append(f"Tier '{name}' was removed")

    return {
        "url": url,
        "tiers": current.get("tiers", []),
        "changed": bool(diffs),
        "diff": "; ".join(diffs) if diffs else "No pricing changes detected",
        "captured_at": current.get("captured_at", ""),
    }
