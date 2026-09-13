# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Slack, over the Web API.

There is no maintained Slack MCP server — ``@modelcontextprotocol/server-slack``
is deprecated upstream ("Package no longer supported"). Rather than ship a dead
dependency, Handoff calls the two Slack endpoints it actually needs directly.

Two credentials work, and they are not equivalent:

* ``SLACK_WEBHOOK_URL`` — an incoming webhook. Five minutes to set up, posts to
  exactly one channel, cannot read anything. Fine for "a decision is waiting".
* ``SLACK_BOT_TOKEN`` — a bot token (``xoxb-…``). Posts to any channel the bot
  is in, and can read. Needed if a workflow should *react* to Slack rather than
  just announce into it.

A bot token is preferred when both are present, because it reports real
delivery errors; a webhook returns 200 for a channel that has since been
archived.
"""

from __future__ import annotations

from typing import Any

from handoff import config

SLACK_API = "https://slack.com/api"


class SlackError(RuntimeError):
    """Slack accepted the request but refused the operation."""


def _client():
    import httpx

    return httpx.Client(timeout=15.0)


def configured() -> bool:
    return bool(config.SLACK_BOT_TOKEN or config.SLACK_WEBHOOK_URL.startswith("http"))


def post_via_webhook(text: str, webhook: str = "") -> dict[str, Any]:
    """Post through an incoming webhook. Channel is fixed by the webhook."""
    url = webhook if webhook.startswith("http") else config.SLACK_WEBHOOK_URL
    if not url.startswith("http"):
        return {"ok": False, "error": "no webhook configured"}

    with _client() as http:
        response = http.post(url, json={"text": text})

    if response.status_code >= 300:
        return {"ok": False, "error": f"{response.status_code}: {response.text[:200]}"}
    return {"ok": True, "via": "webhook"}


def post_via_bot(text: str, channel: str) -> dict[str, Any]:
    """Post with a bot token. Reports Slack's own error codes honestly."""
    if not config.SLACK_BOT_TOKEN:
        return {"ok": False, "error": "no bot token configured"}
    if not channel:
        return {"ok": False, "error": "a channel is required when using a bot token"}

    with _client() as http:
        response = http.post(
            f"{SLACK_API}/chat.postMessage",
            headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"},
            json={"channel": channel, "text": text, "unfurl_links": False},
        )

    payload = response.json()
    if not payload.get("ok"):
        # Slack's errors are specific and actionable — surface them verbatim
        # rather than collapsing them into "failed". `not_in_channel` and
        # `channel_not_found` need different fixes.
        return {"ok": False, "error": payload.get("error", "unknown"), "via": "bot"}

    return {"ok": True, "via": "bot", "ts": payload.get("ts"), "channel": payload.get("channel")}


def post(text: str, channel: str = "", webhook: str = "") -> dict[str, Any]:
    """Post one message, preferring the bot token when it can be used."""
    if config.SLACK_BOT_TOKEN and channel:
        result = post_via_bot(text, channel)
        if result["ok"]:
            return result
        # Fall through to the webhook only if one exists; otherwise report the
        # real Slack error rather than a vaguer webhook one.
        if not (webhook or config.SLACK_WEBHOOK_URL).startswith("http"):
            return result

    return post_via_webhook(text, webhook)


def check() -> dict[str, Any]:
    """Verify the credentials actually work. Used by ``handoff doctor``."""
    if config.SLACK_BOT_TOKEN:
        with _client() as http:
            response = http.post(
                f"{SLACK_API}/auth.test",
                headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"},
            )
        payload = response.json()
        if payload.get("ok"):
            return {
                "ok": True,
                "via": "bot",
                "team": payload.get("team"),
                "user": payload.get("user"),
            }
        return {"ok": False, "via": "bot", "error": payload.get("error")}

    if config.SLACK_WEBHOOK_URL.startswith("http"):
        # A webhook cannot be verified without posting, so report it as
        # present-but-unverified rather than claiming it works.
        return {"ok": True, "via": "webhook", "note": "not verified — posting is the only test"}

    return {"ok": False, "error": "neither SLACK_BOT_TOKEN nor SLACK_WEBHOOK_URL is set"}
