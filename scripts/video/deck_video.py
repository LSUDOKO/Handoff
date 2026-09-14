# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The pitch deck as a narrated video: slides from the PDF, one Polly clip per
slide from the speaker script, stitched with ffmpeg.

    python scripts/video/deck_video.py <work_dir> <out.mp4>

Reads docs/pitch/deck.pdf and docs/pitch/script.md. Each "**Slide N — …**"
paragraph in the script becomes that slide's narration.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import boto3

from handoff import config

ROOT = Path(__file__).resolve().parent.parent.parent
DECK = ROOT / "docs/pitch/deck.pdf"
SCRIPT = ROOT / "docs/pitch/script.md"
VOICE, ENGINE = "Matthew", "generative"


def narration_by_slide() -> dict[int, str]:
    text = SCRIPT.read_text()
    out: dict[int, str] = {}
    for m in re.finditer(r"\*\*Slide (\d+) — [^*]+\*\*\s*(.+?)(?=\n\n\*\*Slide|\n\n---|\Z)", text, re.S):
        body = m.group(2).replace("⏸", "").replace("`", "")
        body = re.sub(r"\*([^*]+)\*", r"\1", body)
        out[int(m.group(1))] = " ".join(body.split())
    return out


def main(work_dir: str, out_path: str) -> int:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-png", "-r", "144", str(DECK), str(work / "slide")], check=True)
    slides = sorted(work.glob("slide-*.png"))
    lines = narration_by_slide()
    polly = boto3.Session().client("polly", region_name=config.AWS_REGION)
    parts: list[Path] = []
    for i, slide in enumerate(slides, start=1):
        text = lines.get(i, "")
        audio = work / f"slide-{i:02d}.mp3"
        if text and not audio.exists():
            r = polly.synthesize_speech(Text=text[:2900], VoiceId=VOICE, Engine=ENGINE, OutputFormat="mp3", SampleRate="24000")
            audio.write_bytes(r["AudioStream"].read())
        part = work / f"part-{i:02d}.mp4"
        if text:
            # Hold the slide for the narration plus a breath either side.
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(slide), "-i", str(audio),
                            "-af", "adelay=600|600,apad=pad_dur=0.9", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2", "-r", "30",
                            "-c:a", "aac", "-b:a", "160k", "-shortest", str(part)], check=True)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(slide), "-t", "4", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-vf", "scale=1920:1080", "-r", "30", "-c:a", "aac", "-shortest", str(part)], check=True)
        parts.append(part)
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", out_path], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out_path], capture_output=True, text=True).stdout.strip()
    print(f"wrote {out_path}: {len(parts)} slides, {float(dur):.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
