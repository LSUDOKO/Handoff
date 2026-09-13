# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Hearing and speaking, on real speech models.

Groq serves Whisper (speech → text) and Orpheus (text → speech) behind the
same key that runs the agents, so voice here is not a browser trick: what you
say is transcribed by a real model, and what Handoff says back is synthesised
by one. The browser's built-in Web Speech API is the fallback for both
directions — always available, noticeably worse — so the interface never goes
silent because a key is missing or a quota ran out.

Two things worth knowing:

* Orpheus needs a one-time terms acceptance in the Groq console playground
  before it will answer. Until then ``speak()`` returns ``None`` with a reason,
  and the page falls back to browser synthesis.
* Voice *commands* on the decision screen are parsed here, not by the LLM.
  "archive it", "file a ticket", "leave it" — a dozen phrasings map to the four
  actions. Sending "archive it" through a language model to get "archive" back
  would be slower, cost tokens, and could be wrong.
"""

from __future__ import annotations

import re
from typing import Any

from handoff import config

#: What a person might say on the decision screen, mapped to an action. Order
#: matters: more specific phrasings first so "don't file" isn't read as "file".
COMMANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(leave|skip|ignore|nothing|don'?t|do not|no action|pass)\b", re.I), "skip"),
    (re.compile(r"\b(archive|bin|trash|dismiss|clear it)\b", re.I), "archive"),
    (re.compile(r"\b(ticket|linear|file it|file that|track|issue)\b", re.I), "file_ticket"),
    (re.compile(r"\b(draft|reply|respond|answer|write back)\b", re.I), "draft_reply"),
    (re.compile(r"\b(go ahead|approve|yes|do it|sounds good|your call|suggested)\b", re.I), "approve_suggested"),
    (re.compile(r"\b(slack|post it|share)\b", re.I), "post_to_slack"),
]


def parse_command(text: str, options: list[str] | None = None) -> str | None:
    """Map a spoken phrase to one of the decision actions, or ``None``."""
    text = (text or "").strip()
    if not text:
        return None
    allowed = set(options or [])
    for pattern, action in COMMANDS:
        if pattern.search(text):
            if not allowed or action in allowed:
                return action
            if action == "approve_suggested" and allowed:
                return action
    return None


def stt_available() -> bool:
    return bool(config.GROQ_API_KEY)


def transcribe(audio: bytes, filename: str = "speech.webm", language: str = "en") -> dict[str, Any]:
    """Speech to text through Groq Whisper. Returns ``{"text": ...}`` or ``{"error": ...}``."""
    if not config.GROQ_API_KEY:
        return {"error": "no_groq_key", "text": ""}
    try:
        import httpx

        response = httpx.post(
            f"{config.GROQ_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            data={
                "model": config.GROQ_STT_MODEL,
                "language": language,
                "response_format": "json",
                "temperature": "0",
            },
            files={"file": (filename, audio)},
            timeout=30.0,
        )
        if response.status_code != 200:
            return {"error": f"{response.status_code}: {response.text[:120]}", "text": ""}
        return {"text": (response.json().get("text") or "").strip()}
    except Exception as exc:
        return {"error": str(exc)[:120], "text": ""}


def speak(text: str, voice: str | None = None) -> tuple[bytes | None, str]:
    """Text to speech through Groq Orpheus.

    Returns ``(wav_bytes, "")`` on success, or ``(None, reason)`` when the
    page should fall back to the browser's own synthesis.
    """
    if not config.GROQ_API_KEY:
        return None, "no_groq_key"
    text = (text or "").strip()
    if not text:
        return None, "empty"
    try:
        import httpx

        response = httpx.post(
            f"{config.GROQ_BASE_URL}/audio/speech",
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            json={
                "model": config.GROQ_TTS_MODEL,
                "input": text[:1200],
                "voice": voice or config.GROQ_TTS_VOICE,
                "response_format": "wav",
            },
            timeout=45.0,
        )
        if response.status_code == 200 and response.headers.get("content-type", "").startswith("audio"):
            return response.content, ""
        body = response.text[:200]
        if "model_terms_required" in body:
            return None, "terms_required"
        return None, f"{response.status_code}: {body}"
    except Exception as exc:
        return None, str(exc)[:120]


def decision_prompt(payload: Any) -> str:
    """What Handoff says out loud when it needs a call — short enough to
    answer from across the room, specific enough to answer without looking."""
    item = payload.item
    analysis = payload.agent_analysis
    who = item.sender.split("@")[-1] if item.sender else "an unknown sender"
    suggestion = (analysis.suggested_action or "").replace("_", " ")
    lines = [f"I need your call on one from {who}: {item.subject or item.summary}."]
    if analysis.reasoning:
        lines.append(analysis.reasoning)
    if suggestion:
        lines.append(f"My best guess is {suggestion}, at {analysis.confidence:.0%}.")
    lines.append("You can say archive, file a ticket, draft a reply, or leave it.")
    return " ".join(lines)
