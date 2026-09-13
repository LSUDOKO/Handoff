# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""RIFF/WAVE framing, with no dependencies.

The browser records raw 16 kHz mono PCM through an AudioWorklet and wraps it
in a WAV header before uploading; Transcribe wants the PCM back out. Neither
direction needs anything beyond ``struct``.
"""

from __future__ import annotations

import struct


def pcm_to_wav(pcm: bytes, rate: int = 16000, channels: int = 1) -> bytes:
    """Wrap 16-bit little-endian PCM in a canonical 44-byte WAV header."""
    byte_rate = rate * channels * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, channels, rate, byte_rate, channels * 2, 16,
        b"data", len(pcm),
    )
    return header + pcm


def is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def wav_to_pcm(data: bytes) -> tuple[bytes, int, int]:
    """Return ``(pcm16_mono, rate, channels=1)`` from a WAV file.

    Walks the chunk list rather than assuming a 44-byte header, so files
    written by other tools (with ``LIST`` or ``fact`` chunks) still parse.
    8-bit audio is widened to 16-bit; stereo is averaged down to mono.
    """
    if not is_wav(data):
        raise ValueError("not a WAV file")
    pos = 12
    rate, channels, bits = 16000, 1, 16
    pcm = b""
    while pos + 8 <= len(data):
        chunk_id, size = struct.unpack("<4sI", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + size]
        if chunk_id == b"fmt ":
            _fmt, channels, rate, _byte_rate, _align, bits = struct.unpack("<HHIIHH", body[:16])
        elif chunk_id == b"data":
            pcm = body
            break
        pos += 8 + size + (size & 1)

    if bits == 8:
        pcm = struct.pack(f"<{len(pcm)}h", *((b - 128) << 8 for b in pcm))
    elif bits != 16:
        raise ValueError(f"unsupported bit depth {bits}")

    if channels > 1:
        frames = len(pcm) // (2 * channels)
        samples = struct.unpack(f"<{frames * channels}h", pcm[: frames * channels * 2])
        mono = [
            int(sum(samples[i : i + channels]) / channels)
            for i in range(0, len(samples), channels)
        ]
        pcm = struct.pack(f"<{len(mono)}h", *mono)
    return pcm, rate, 1
