# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Synthesise the demo narration with Amazon Polly, one file per sentence.

Generative voices give no word timings, so each sentence is its own clip and
the caption for it starts exactly where the clip does. Writes ``<out>/n-<scene>-<i>.mp3``
plus ``<out>/narration.json`` with durations, and the three "spoken by the
user" lines as 16 kHz WAVs for the fake microphone.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import boto3

from handoff import config

SRC = Path(__file__).resolve().parent / "narration.json"


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def main(out_dir: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads(SRC.read_text())
    polly = boto3.Session().client("polly", region_name=config.AWS_REGION)

    def synth(text: str, voice: str, engine: str, path: Path) -> None:
        if path.exists():
            return
        r = polly.synthesize_speech(Text=text, VoiceId=voice, Engine=engine, OutputFormat="mp3", SampleRate="24000")
        path.write_bytes(r["AudioStream"].read())

    result = {"scenes": []}
    chars = 0
    for scene in spec["scenes"]:
        entries = []
        for i, sentence in enumerate(scene["sentences"]):
            path = out / f"n-{scene['id']}-{i}.mp3"
            synth(sentence, spec["voice"], spec["engine"], path)
            chars += len(sentence)
            entries.append({"text": sentence, "file": path.name, "seconds": round(duration(path), 3)})
        result["scenes"].append({"id": scene["id"], "sentences": entries, "seconds": round(sum(e["seconds"] for e in entries), 3)})

    user = spec["spoken_by_user"]
    for key in ("setup", "decide", "decide_generic", "again"):
        mp3 = out / f"user-{key}.mp3"
        synth(user[key], user["voice"], "generative", mp3)
        chars += len(user[key])
        wav = out / f"user-{key}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(wav)], check=True)
        result[f"user_{key}"] = {"text": user[key], "wav": wav.name, "seconds": round(duration(wav), 3)}

    (out / "narration.json").write_text(json.dumps(result, indent=1))
    total = sum(s["seconds"] for s in result["scenes"])
    print(f"narration: {total:.1f}s of speech, {chars} characters synthesised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "video/public/audio"))
