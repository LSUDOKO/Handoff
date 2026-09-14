"""The Gmail adapter's parsing: the real server answers in text blocks, not JSON."""

from handoff.mcp import gmail_adapter as g

SEARCH = """ID: 1a0a162b1b1a9e9b
Subject: Thank you for joining the hackathon!
From: Jerry Zhang <jerry@example.io>
Date: Mon, 14 Sep 2026 12:19:11 -0700

ID: 1a0a12e9b89fbfd4
Subject: [meshery-dev] Meshery v1.0.70 Release Notes
From: no-reply@meshery.io
Date: Mon, 14 Sep 2026 18:24:16 +0000
"""

READ = """Thread ID: 1a0a162b1b1a9e9b
Subject: Thank you for joining the hackathon!
From: Jerry Zhang <jerry@example.io>
To: events@example.io
Date: Mon, 14 Sep 2026 12:19:11 -0700

Hi everyone,\r
\r
Thank you again for joining us. Seeing what people shipped in a single day\r
was the best part of our weekend.
"""


def test_search_blocks_become_messages():
    msgs = [g._message(b) for b in g.parse_blocks(SEARCH)]
    assert [m["email_id"] for m in msgs] == ["1a0a162b1b1a9e9b", "1a0a12e9b89fbfd4"]
    assert msgs[0]["sender"] == "jerry@example.io"
    assert msgs[0]["sender_name"] == "Jerry Zhang"
    assert msgs[0]["subject"].startswith("Thank you")
    # A bare address has no display name and must not be mangled.
    assert msgs[1]["sender"] == "no-reply@meshery.io"
    assert msgs[1]["sender_name"] == ""


def test_read_email_splits_headers_from_body(monkeypatch):
    monkeypatch.setattr(g, "call_mcp_tool", lambda server, op, params: {"text": READ})
    msg = g.read_message("1a0a162b1b1a9e9b")
    assert msg["email_id"] == "1a0a162b1b1a9e9b"
    assert msg["sender"] == "jerry@example.io"
    assert msg["body"].startswith("Hi everyone,")
    assert "\r" not in msg["body"]
    assert msg["snippet"].startswith("Hi everyone, Thank you again")
    assert len(msg["snippet"]) <= g.PREVIEW_CHARS


def test_search_widens_when_nothing_is_unread(monkeypatch):
    calls: list[dict] = []

    def fake(server, op, params):
        calls.append(params)
        if op == "read_email":
            return {"text": READ}
        return {"text": "" if "unread" in params["query"] else SEARCH}

    monkeypatch.setattr(g, "call_mcp_tool", fake)
    msgs, used = g.search_messages("is:unread newer_than:12h", 5)
    assert used == g.FALLBACK_QUERY
    assert len(msgs) == 2 and msgs[0]["snippet"]
    assert calls[0]["query"] == "is:unread newer_than:12h"


def test_archive_removes_the_inbox_label(monkeypatch):
    seen = {}
    monkeypatch.setattr(g, "call_mcp_tool", lambda server, op, params: seen.update({"op": op, **params}) or {"text": "ok"})
    g.act("archive", "abc", {})
    assert seen["op"] == "modify_email"
    assert seen["messageId"] == "abc" and seen["removeLabelIds"] == ["INBOX"]


def test_draft_replies_in_thread_to_the_sender(monkeypatch):
    seen = {}

    def fake(server, op, params):
        if op == "read_email":
            return {"text": READ}
        seen.update({"op": op, **params})
        return {"text": "ok"}

    monkeypatch.setattr(g, "call_mcp_tool", fake)
    g.act("create_draft", "1a0a162b1b1a9e9b", {"body": "Thanks Jerry."})
    assert seen["op"] == "draft_email"
    assert seen["to"] == ["jerry@example.io"]
    assert seen["subject"] == "Re: Thank you for joining the hackathon!"
    assert seen["body"] == "Thanks Jerry."
