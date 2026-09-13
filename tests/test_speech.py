# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The speech facade: WAV framing and provider selection, all offline."""

from __future__ import annotations

import struct


def test_pcm_wav_round_trip():
    from handoff.speech import wav

    pcm = struct.pack("<8h", *range(8))
    data = wav.pcm_to_wav(pcm, 16000, 1)
    assert wav.is_wav(data) and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    back, rate, channels = wav.wav_to_pcm(data)
    assert (back, rate, channels) == (pcm, 16000, 1)


def test_wav_to_pcm_downmixes_stereo():
    from handoff.speech import wav

    left_right = struct.pack("<4h", 100, 300, -200, 0)  # two frames of L,R
    data = wav.pcm_to_wav(left_right, 16000, 2)
    back, rate, channels = wav.wav_to_pcm(data)
    assert channels == 1 and rate == 16000
    assert struct.unpack("<2h", back) == (200, -100)


def test_is_wav_rejects_other_containers():
    from handoff.speech import wav

    assert not wav.is_wav(b"\x1aE\xdf\xa3webm...")
    assert not wav.is_wav(b"")


def test_provider_selection_prefers_aws_then_groq_then_browser(monkeypatch):
    import handoff.speech as speech
    from handoff import config

    monkeypatch.setattr(config, "SPEECH_PROVIDER", "auto")
    monkeypatch.setattr(speech, "_aws_ready", lambda: True)
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    assert speech.provider() == "aws"

    monkeypatch.setattr(speech, "_aws_ready", lambda: False)
    monkeypatch.setattr(config, "GROQ_API_KEY", "gsk_test")
    assert speech.provider() == "groq"

    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    assert speech.provider() == "browser"

    # An explicit choice wins over what happens to be available.
    monkeypatch.setattr(config, "SPEECH_PROVIDER", "browser")
    monkeypatch.setattr(speech, "_aws_ready", lambda: True)
    assert speech.provider() == "browser"


def test_speak_and_transcribe_hand_back_to_the_browser(monkeypatch):
    import handoff.speech as speech
    from handoff import config

    monkeypatch.setattr(config, "SPEECH_PROVIDER", "browser")
    audio, mime, reason = speech.speak("hello")
    assert audio is None and mime == "" and reason == "browser"
    assert speech.transcribe(b"RIFF....WAVE") == {"text": "", "error": "browser"}


def test_status_reports_the_active_provider(monkeypatch):
    import handoff.speech as speech
    from handoff import config

    monkeypatch.setattr(config, "SPEECH_PROVIDER", "auto")
    monkeypatch.setattr(speech, "_aws_ready", lambda: True)
    s = speech.status()
    assert s["provider"] == "aws" and s["stt"] is True and s["tts"] is True
    assert s["voice"] == config.POLLY_VOICE and s["region"] == config.AWS_REGION


def test_aws_transcribe_converts_wav_to_pcm(monkeypatch):
    """The facade unwraps the WAV so AWS gets raw 16 kHz PCM."""
    import handoff.speech as speech
    from handoff import config
    from handoff.speech import aws, wav

    monkeypatch.setattr(config, "SPEECH_PROVIDER", "aws")
    seen: dict = {}

    def fake(pcm: bytes, rate: int, language: str) -> str:
        seen.update(pcm=pcm, rate=rate, language=language)
        return "  archive it  "

    monkeypatch.setattr(aws, "transcribe_pcm", fake)
    pcm = struct.pack("<4h", 1, 2, 3, 4)
    assert speech.transcribe(wav.pcm_to_wav(pcm, 16000, 1)) == {"text": "archive it"}
    assert seen == {"pcm": pcm, "rate": 16000, "language": config.TRANSCRIBE_LANGUAGE}


def test_aws_speak_returns_mp3(monkeypatch):
    import handoff.speech as speech
    from handoff import config
    from handoff.speech import aws

    monkeypatch.setattr(config, "SPEECH_PROVIDER", "aws")
    monkeypatch.setattr(aws, "synthesize", lambda text, voice, engine: b"ID3mp3bytes")
    audio, mime, reason = speech.speak("Ready.")
    assert audio == b"ID3mp3bytes" and mime == "audio/mpeg" and reason == ""
