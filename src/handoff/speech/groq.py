# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Hearing and speaking on Groq: Whisper in, Orpheus out.

Behind the same key that runs the agents on the Groq provider. Orpheus needs
a one-time terms acceptance in the Groq console playground; until then
``speak`` returns ``None`` with the reason ``terms_required``.
"""

from __future__ import annotations

from typing import Any

from handoff import config


def ready() -> bool:
    return bool(config.GROQ_API_KEY)


def transcribe(audio: bytes, filename: str = "speech.wav", language: str = "en") -> dict[str, Any]:
    """Returns ``{"text": ...}`` or ``{"text": "", "error": ...}``."""
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
    """Returns ``(wav_bytes, "")`` or ``(None, reason)``."""
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
