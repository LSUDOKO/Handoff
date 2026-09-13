# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Voice commands, and the speech facade re-exported for the web layer.

Hearing and speaking live in ``handoff.speech`` (AWS Transcribe + Polly,
Groq Whisper + Orpheus, or the browser). What stays here is the part that
must never go through a model: voice *commands* on the decision screen.
"archive it", "file a ticket", "leave it" — a dozen phrasings map to the
four actions. Sending "archive it" through a language model to get "archive"
back would be slower, cost tokens, and could be wrong.
"""

from __future__ import annotations

import re
from typing import Any

from handoff import speech

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
    """A server-side engine exists — AWS or Groq. Otherwise the browser hears."""
    return bool(speech.status()["stt"])


def transcribe(audio: bytes, filename: str = "speech.wav", language: str | None = None) -> dict[str, Any]:
    return speech.transcribe(audio, filename, language)


def speak(text: str, voice: str | None = None) -> tuple[bytes | None, str, str]:
    return speech.speak(text, voice)


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
