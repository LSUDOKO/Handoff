# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The desktop window's native microphone bridge, with a fake sound device."""

from __future__ import annotations

import base64


class FakeStream:
    """Stands in for sounddevice.RawInputStream: delivers a few frames of silence."""

    instances: list = []

    def __init__(self, samplerate, channels, dtype, callback, blocksize=0):
        assert (samplerate, channels, dtype) == (16000, 1, "int16")
        self.callback = callback
        self.started = self.stopped = self.closed = False
        FakeStream.instances.append(self)

    def start(self):
        self.started = True
        for _ in range(3):
            self.callback(bytes(1600 * 2), 1600, None, None)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


def test_bridge_records_and_returns_wav():
    from handoff.desktop import DesktopBridge
    from handoff.speech import wav

    bridge = DesktopBridge(stream_factory=FakeStream)
    assert bridge.start_listening() == {"ok": True}
    out = bridge.stop_listening()
    assert out["ok"] is True
    data = base64.b64decode(out["wav_b64"])
    pcm, rate, channels = wav.wav_to_pcm(data)
    assert rate == 16000 and channels == 1 and len(pcm) == 3 * 1600 * 2
    assert abs(out["seconds"] - 0.3) < 0.01
    assert FakeStream.instances[-1].stopped and FakeStream.instances[-1].closed


def test_bridge_reports_missing_microphone():
    from handoff.desktop import DesktopBridge

    def broken(**kwargs):
        raise OSError("no input device")

    bridge = DesktopBridge(stream_factory=broken)
    out = bridge.start_listening()
    assert out["ok"] is False and "no input device" in out["error"]
    assert bridge.stop_listening()["ok"] is False


def test_status_names_the_backend():
    from handoff.desktop import DesktopBridge

    status = DesktopBridge(stream_factory=FakeStream).status()
    assert status["mic"] is True and status["backend"] == "sounddevice"


def test_stale_page_falls_back_to_the_orb(monkeypatch):
    """A chat deleted since last launch must not open as a raw 404 body."""
    from handoff import desktop

    def gone(port, path):
        return False

    monkeypatch.setattr(desktop, "_page_still_there", gone)
    assert desktop._page_still_there(8000, "/chat/chat_missing") is False


def test_live_page_is_kept(monkeypatch):
    from handoff import desktop

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response())
    assert desktop._page_still_there(8000, "/chat/chat_live") is True
