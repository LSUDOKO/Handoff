# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Speech, behind one facade.

Three providers, one interface. AWS (Transcribe streaming and Polly) is the
one the deployment runs on; Groq (Whisper and Orpheus) comes with the free
key that also runs the agents; the browser's own engines are the floor, so
the interface never goes mute over a missing credential.

``HANDOFF_SPEECH_PROVIDER`` picks explicitly. ``auto`` — the default — takes
the first that is ready in that order.
"""

from __future__ import annotations

from typing import Any

from handoff import config
from handoff.speech import aws, groq, wav

PROVIDERS = ("aws", "groq", "browser")

# Module attributes rather than direct calls, so a test can swap them.
_aws_ready = aws.ready
_groq_ready = groq.ready


def provider() -> str:
    """Which engine will hear and speak right now."""
    chosen = (config.SPEECH_PROVIDER or "auto").lower()
    if chosen in PROVIDERS:
        return chosen
    if _aws_ready():
        return "aws"
    if _groq_ready():
        return "groq"
    return "browser"


def transcribe(audio: bytes, filename: str = "speech.wav", language: str | None = None) -> dict[str, Any]:
    """Speech → text. ``{"text": ...}`` on success, ``{"text": "", "error": ...}`` otherwise.

    ``error == "browser"`` means: no server-side engine; the page should use
    the Web Speech API itself.
    """
    which = provider()
    if which == "aws":
        try:
            if wav.is_wav(audio):
                pcm, rate, _ = wav.wav_to_pcm(audio)
            else:
                return {"text": "", "error": "aws_needs_wav"}
            text = aws.transcribe_pcm(pcm, rate, language or config.TRANSCRIBE_LANGUAGE)
            return {"text": text.strip()}
        except Exception as exc:
            return {"text": "", "error": str(exc)[:160]}
    if which == "groq":
        return groq.transcribe(audio, filename, (language or config.TRANSCRIBE_LANGUAGE).split("-")[0])
    return {"text": "", "error": "browser"}


def speak(text: str, voice: str | None = None) -> tuple[bytes | None, str, str]:
    """Text → audio. Returns ``(audio, mime, "")`` or ``(None, "", reason)``."""
    text = (text or "").strip()
    if not text:
        return None, "", "empty"
    which = provider()
    if which == "aws":
        try:
            return aws.synthesize(text, voice or config.POLLY_VOICE, config.POLLY_ENGINE), "audio/mpeg", ""
        except Exception as exc:
            return None, "", str(exc)[:160]
    if which == "groq":
        audio, reason = groq.speak(text, voice)
        return (audio, "audio/wav", "") if audio else (None, "", reason)
    return None, "", "browser"


def status() -> dict[str, Any]:
    which = provider()
    return {
        "provider": which,
        "stt": which != "browser",
        "tts": which != "browser",
        "voice": config.POLLY_VOICE if which == "aws" else (config.GROQ_TTS_VOICE if which == "groq" else "browser"),
        "engine": config.POLLY_ENGINE if which == "aws" else (config.GROQ_TTS_MODEL if which == "groq" else "web-speech"),
        "region": config.AWS_REGION,
        "language": config.TRANSCRIBE_LANGUAGE,
    }
