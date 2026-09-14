# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Gmail through the MCP server a person actually signs into.

The executor speaks in Handoff's own verbs — search, archive, draft, label —
and the Gmail server it reaches is ``@gongrzhe/server-gmail-autoauth-mcp``,
whose tools are ``search_emails``, ``modify_email``, ``draft_email`` and
friends, and whose results are plain text blocks rather than JSON::

    ID: 1a0a162b1b1a9e9b
    Subject: Thank you for joining the hackathon
    From: Jerry Zhang <jerry@example.com>
    Date: Mon, 14 Sep 2026 12:19:11 -0700

This module is the translation. Everything the graph knows about a message
(``email_id``, ``sender``, ``sender_name``, ``subject``, ``snippet``) is
built here, so the executor's tool signatures do not change between the
synthetic inbox and a real one.
"""

from __future__ import annotations

import re
from typing import Any

from handoff.mcp.servers import call_mcp_tool

_ADDR = re.compile(r"^\s*(?:\"?([^\"<]*)\"?\s*)?<([^>]+)>\s*$")
_BLOCK_KEY = re.compile(r"^([A-Za-z][A-Za-z ]{1,20}):\s*(.*)$")
#: How much of a body the classifier sees. Enough to judge, cheap enough to
#: carry through every subsequent turn (tool arguments are re-typed by the
#: model on each call, and free tiers meter tokens).
PREVIEW_CHARS = 280
#: When "unread in the last 12 hours" is empty, triage the recent inbox
#: instead of reporting an empty morning — the person asked for a pass, not
#: a filter.
FALLBACK_QUERY = "in:inbox newer_than:3d"


def _text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("text") or "")
    if isinstance(result, list):
        return "\n".join(_text(r) for r in result)
    return str(result or "")


def _split_address(value: str) -> tuple[str, str]:
    """``'Jerry Zhang <jerry@x.io>'`` → ``('jerry@x.io', 'Jerry Zhang')``."""
    m = _ADDR.match(value or "")
    if m:
        return m.group(2).strip(), (m.group(1) or "").strip()
    return (value or "").strip(), ""


def parse_blocks(text: str) -> list[dict[str, str]]:
    """Parse the server's ``Key: value`` blocks, one message per blank line."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        m = _BLOCK_KEY.match(line)
        if m:
            current[m.group(1).strip().lower()] = m.group(2).strip()
    if current:
        blocks.append(current)
    return [b for b in blocks if b.get("id") or b.get("thread id")]


def _message(block: dict[str, str]) -> dict[str, Any]:
    sender, name = _split_address(block.get("from", ""))
    return {
        "email_id": block.get("id") or block.get("thread id", ""),
        "sender": sender,
        "sender_name": name,
        "subject": block.get("subject", ""),
        "date": block.get("date", ""),
        "snippet": "",
        "labels": [],
    }


def read_message(message_id: str) -> dict[str, Any]:
    """One message with its body, split from the header block."""
    raw = _text(call_mcp_tool("gmail", "read_email", {"messageId": message_id}))
    head, _, body = raw.partition("\n\n")
    block = parse_blocks(head + "\n")
    msg = _message(block[0]) if block else {"email_id": message_id, "sender": "", "sender_name": "", "subject": "", "date": "", "snippet": "", "labels": []}
    msg["email_id"] = msg["email_id"] or message_id
    body = body.replace("\r\n", "\n").strip()
    msg["body"] = body
    msg["snippet"] = " ".join(body.split())[:PREVIEW_CHARS]
    return msg


def search_messages(query: str, max_results: int = 20) -> tuple[list[dict[str, Any]], str]:
    """Messages matching ``query`` with a short preview each.

    Returns the messages and the query that actually produced them, so the
    run can say when it widened its search.
    """
    used = query
    text = _text(call_mcp_tool("gmail", "search_emails", {"query": query, "maxResults": max_results}))
    blocks = parse_blocks(text)
    if not blocks and "unread" in query:
        used = FALLBACK_QUERY
        text = _text(call_mcp_tool("gmail", "search_emails", {"query": used, "maxResults": max_results}))
        blocks = parse_blocks(text)
    messages = [_message(b) for b in blocks[:max_results]]
    # A preview per message: the search result carries headers only, and
    # "Re: invoice" from an unknown sender is not enough to judge.
    for m in messages:
        try:
            m["snippet"] = read_message(m["email_id"])["snippet"]
        except Exception:  # a preview is a nicety; the header still gets triaged
            pass
    return messages, used


def archive(message_id: str) -> Any:
    return call_mcp_tool("gmail", "modify_email", {"messageId": message_id, "removeLabelIds": ["INBOX"]})


def create_draft(message_id: str, body: str = "", subject: str = "") -> Any:
    """A reply draft in the message's own thread, addressed to its sender."""
    original = read_message(message_id)
    to = original.get("sender") or ""
    subj = subject or original.get("subject") or ""
    if subj and not subj.lower().startswith("re:"):
        subj = f"Re: {subj}"
    text = body or "Thanks for this — I'll come back to you shortly.\n\n(Draft written by Handoff; review before sending.)"
    return call_mcp_tool("gmail", "draft_email", {"to": [to] if to else [], "subject": subj, "body": text, "threadId": original.get("email_id", message_id)})


def add_label(message_id: str, label: str) -> Any:
    created = _text(call_mcp_tool("gmail", "get_or_create_label", {"name": label}))
    m = re.search(r"\b(?:ID|id)\s*[:=]\s*([A-Za-z0-9_\-]+)", created)
    label_id = m.group(1) if m else label
    return call_mcp_tool("gmail", "modify_email", {"messageId": message_id, "addLabelIds": [label_id]})


def act(operation: str, message_id: str, params: dict[str, Any]) -> Any:
    """Route one of the gate's Gmail operations to the server's tools."""
    if operation == "archive":
        return archive(message_id)
    if operation == "create_draft":
        return create_draft(message_id, body=str(params.get("body") or params.get("draft") or params.get("text") or ""), subject=str(params.get("subject") or ""))
    if operation == "add_label":
        return add_label(message_id, str(params.get("label") or params.get("name") or "Handoff"))
    return call_mcp_tool("gmail", operation, {"messageId": message_id, **params})
