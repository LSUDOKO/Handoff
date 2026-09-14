# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Record the live footage for the demo film — nothing staged.

Chromium is launched with a fake microphone fed by a WAV of the sentence a
person would say. The script clicks the real orb; the page streams the audio
to Amazon Transcribe over its WebSocket, the agent runs the turn on Bedrock,
the workspace card lands, the run graph fills in, the decision card appears.
Playwright records the page the whole time, and this script logs when each
thing happened so the narration can be cut against it.

Three clips: the spoken set-up and run, the spoken decision, the second run.

    python scripts/video/record_live.py <audio_dir> <out_dir> [base_url]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

SENTENCE_WAIT = 0.9  # seconds after the WAV ends before "stopping" the mic


def milestones(page) -> dict:
    """What is on the page right now, as flags a timeline can diff."""
    return page.evaluate(
        """() => ({
            caption: (document.querySelector('#orb-caption')?.textContent || '').trim(),
            mode: document.querySelector('#orb-caption')?.dataset.mode || '',
            state: document.querySelector('#orb-button')?.dataset.state || '',
            transcript: (document.querySelector('#orb-transcript')?.textContent || '').trim(),
            tools: document.querySelectorAll('.ot-line.tool').length,
            reply: [...document.querySelectorAll('.ot-line.handoff .ot-text')].map(e => e.textContent).pop() || '',
            card: !!document.querySelector('.work-card'),
            graph: !!document.querySelector('.run-graph'),
            nodes: document.querySelectorAll('.rg-node').length,
            done_nodes: document.querySelectorAll('.rg-node[data-status="done"]').length,
            run_status: (document.querySelector('.run-graph .rg-status')?.textContent || '').trim(),
            decisions: document.querySelectorAll('.waiting-card.needs').length,
            decided: document.querySelectorAll('.waiting-card .decided').length,
            webgl: !(document.querySelector('#orb')?.hidden ?? true),
        })"""
    )


def record(p, base, wav: Path, seconds: float, out_dir: Path, name: str, done_when, max_wait: float, settle: float = 3.0) -> dict:
    """One clip: open the orb, speak the WAV through the fake mic, wait for ``done_when``."""
    browser = p.chromium.launch(args=[
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={wav}%noloop", "--autoplay-policy=no-user-gesture-required",
    ])
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080}, device_scale_factor=1, color_scheme="light",
        permissions=["microphone"], record_video_dir=str(out_dir / "raw"), record_video_size={"width": 1920, "height": 1080},
    )
    t0 = time.time()
    page = ctx.new_page()
    log: list[dict] = []
    last = None

    def mark(event: str, **extra) -> None:
        log.append({"t": round(time.time() - t0, 2), "event": event, **extra})

    page.goto(f"{base}/orb", wait_until="networkidle")
    first = milestones(page)
    mark("page_loaded", **first)
    initial_graph = page.evaluate("document.querySelector('.run-graph')?.id || ''")
    # A page that reopens on a waiting decision reads it aloud first; tapping
    # the orb then only stops the speech. Wait for it to fall quiet.
    for _ in range(60):
        if milestones(page)["mode"] not in ("speaking", "thinking", "acting"):
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1800)
    page.click("#orb-button")
    for _ in range(12):
        page.wait_for_timeout(250)
        if milestones(page)["state"] == "listening":
            break
    else:
        page.click("#orb-button")
    mark("listen_start")
    stop_at = time.time() + seconds + SENTENCE_WAIT
    deadline = time.time() + max_wait
    stopped = False
    while time.time() < deadline:
        now = milestones(page)
        now["new_graph"] = page.evaluate("document.querySelector('.run-graph')?.id || ''") != initial_graph
        if not stopped and time.time() >= stop_at:
            page.click("#orb-button")
            mark("listen_stop", transcript=now["transcript"])
            stopped = True
        if now != last:
            changed = {k: v for k, v in now.items() if last is None or last.get(k) != v}
            mark("change", **changed)
            # Follow the work down the page: the card, then the graph, then the decision.
            for key, selector in (("card", ".work-card"), ("graph", ".run-graph"), ("decisions", ".waiting-card.needs"), ("decided", ".waiting-card .decided")):
                if key in changed and changed[key]:
                    page.evaluate(f"document.querySelector('{selector}')?.scrollIntoView({{behavior: 'smooth', block: 'center'}})")
                    mark("scroll", to=key)
            last = now
        if stopped and done_when(now):
            mark("done", **now)
            break
        page.wait_for_timeout(250)
    else:
        mark("timeout", **(last or {}))
    page.wait_for_timeout(int(settle * 1000))
    mark("end")
    video = page.video
    ctx.close()
    browser.close()
    raw = Path(video.path())
    mp4 = out_dir / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(mp4)], check=True)
    raw.unlink(missing_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(log, indent=1))
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True).stdout.strip() or 0)
    print(f"{name}: {dur:.1f}s, {len(log)} events, last: {log[-2]['event'] if len(log) > 1 else '?'}")
    return {"file": mp4.name, "seconds": dur, "events": log}


def main(audio_dir: str, out_dir: str, base: str = "http://127.0.0.1:8765", only: str = "setup,decide,again") -> int:
    audio, out = Path(audio_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads((audio / "narration.json").read_text())
    api = httpx.Client(base_url=base, timeout=30)
    api.post("/welcome/skip")
    wanted = set(only.split(","))
    previous = json.loads((out / "clips.json").read_text()) if (out / "clips.json").exists() else {}
    result = dict(previous)
    with sync_playwright() as p:
        # 1. Say the sentence; the turn saves the workflow and starts the run; the run stops on a decision.
        if "setup" in wanted:
            api.post("/orb/reset")
            result["setup"] = record(
            p, base, audio / spec["user_setup"]["wav"], spec["user_setup"]["seconds"], out, "clip-setup",
            done_when=lambda m: m["run_status"] in ("NEEDS YOU", "DONE", "FAILED") and m["state"] not in ("thinking", "acting"),
            max_wait=240, settle=4.0,
        )
        # 2. Answer it out loud — "cold outreach" only if the vendor pitch is what it asked about.
        if "decide" in wanted:
            pending = sorted(api.get("/api/pending").json(), key=lambda d: d["agent_analysis"]["confidence"])
            first_sender = pending[0]["item"]["sender"] if pending else ""
            line = "user_decide" if "vendor" in first_sender else "user_decide_generic"
            result["answer"] = {"sender": first_sender, "line": line}
            result["decide"] = record(
            p, base, audio / spec[line]["wav"], spec[line]["seconds"], out, "clip-decide",
            done_when=lambda m: m["decided"] >= 1, max_wait=60, settle=4.0,
        )
        # The answer resumes the run and the learner writes a rule; wait for both before the second run.
        if "again" in wanted:
          for _ in range(120):
            status = api.get("/api/status").json()
            if not status.get("busy"):
                break
            time.sleep(2)
          time.sleep(3)
          # Anything else it set aside is answered off camera the same way, so the
          # second run has a rule for every item the first one asked about.
          for other in api.get("/api/pending").json():
              api.post(f"/api/decisions/{other['interrupt_id']}", json={"action": "archive", "note": "answered for the film"})
              for _ in range(60):
                  if not api.get("/api/status").json().get("busy"):
                      break
                  time.sleep(2)
          result["pending_after_decision"] = len(api.get("/api/pending").json())
          # 3. Run it again: the rule fires, nothing is set aside.
          result["again"] = record(
            p, base, audio / spec["user_again"]["wav"], spec["user_again"]["seconds"], out, "clip-again",
            done_when=lambda m: m["new_graph"] and m["run_status"] in ("DONE", "NEEDS YOU", "FAILED") and m["state"] not in ("thinking", "acting"),
            max_wait=240, settle=4.0,
        )
    (out / "clips.json").write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
