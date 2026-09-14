# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Turn the recorded timelines and the film's real state into cues for Remotion.

Reads ``<clips>/clip-*.json`` (what happened when, on the page), the state
directory the film ran against (the decision's confidence and reasoning, the
rule the learner wrote), and ``hitl.py`` (the lines the gate scene shows).
Writes ``video/src/data/cues.json`` and the decision still, and rewrites the
narration sentence that quotes the numbers so the voice matches the footage.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def events(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def first(evs: list[dict], **cond) -> float | None:
    """Time of the first event whose fields match ``cond`` (truthy checks for True)."""
    for e in evs:
        ok = True
        for k, v in cond.items():
            if v is True:
                ok = ok and bool(e.get(k))
            else:
                ok = ok and e.get(k) == v
        if ok:
            return e["t"]
    return None


def main(clips_dir: str, state_dir: str, audio_dir: str) -> int:
    clips, state, audio = Path(clips_dir), Path(state_dir), Path(audio_dir)
    setup = events(clips / "clip-setup.json")
    decide = events(clips / "clip-decide.json")
    again = events(clips / "clip-again.json")
    lengths = {n: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clips / f"clip-{n}.mp4")], capture_output=True, text=True).stdout.strip()) for n in ("setup", "decide", "again")}

    ls = first(setup, event="listen_start")
    lstop = first(setup, event="listen_stop")
    tool1 = first(setup, event="change", tools=1)
    card = first(setup, event="change", card=True)
    graph = first(setup, event="change", graph=True)
    needs = first(setup, event="change", run_status="NEEDS YOU") or first(setup, event="done")
    end_setup = min(lengths["setup"], (needs or 0) + 4.0)

    # "say": the sentence as it is heard, then the tools and the card.
    say = [
        {"kind": "play", "from": max(0, ls - 1.2), "to": lstop + 0.8, "rate": 1.0},
        {"kind": "play", "from": max(lstop + 0.8, tool1 - 1.0), "to": card + 1.6, "rate": 1.0},
    ]
    # Scene lengths the narration wants, so footage is sped up to fit rather
    # than the scene stretched into silence.
    spoken = {s["id"]: s["seconds"] + 0.32 * (len(s["sentences"]) - 1) + 0.8 for s in json.loads((audio / "narration.json").read_text())["scenes"]}

    def fit(seconds: float, want: float, cap: float = 1.8) -> float:
        return round(min(cap, max(1.0, seconds / max(want, 1))), 2)

    # "run": the graph filling in until it asks, sped up to the narration.
    run_from, run_to = card + 1.6, end_setup
    run = [{"kind": "play", "from": run_from, "to": run_to, "rate": fit(run_to - run_from, spoken["run"])}]

    dls = first(decide, event="listen_start")
    decided = first(decide, event="change", decided=1) or first(decide, event="done")
    dec_from, dec_to = max(0, dls - 1.0), min(lengths["decide"], (decided or dls + 8) + 3.5)
    dec = [{"kind": "play", "from": dec_from, "to": dec_to, "rate": fit(dec_to - dec_from, spoken["decision"] - 15.0)}]

    als = first(again, event="listen_start")
    agraph = None
    for e in again:
        if e.get("event") == "change" and e.get("new_graph"):
            agraph = e["t"]
            break
    adone = first(again, event="done")
    ag_from, ag_to = max(0, als - 1.0), min(lengths["again"], (adone or lengths["again"]) + 0.5)
    ag = [{"kind": "play", "from": ag_from, "to": ag_to, "rate": fit(ag_to - ag_from, spoken["quieter"] - 3.5, cap=2.0)}]

    # The decision, from the state: the pending interrupt this film stopped on.
    interrupts = json.loads((state / "interrupts.json").read_text())
    rows = interrupts if isinstance(interrupts, list) else list(interrupts.values())
    # The one the voice answered: resolved, least confident of the first run's batch.
    answered = [r for r in rows if r.get("resolved")]
    pick = sorted(answered or rows, key=lambda r: (r.get("timestamp", ""), r.get("agent_analysis", {}).get("confidence", 1)))[0] if rows else {}
    first_run = pick.get("run_id", "")
    set_aside = sum(1 for r in rows if r.get("run_id") == first_run) or 1
    analysis = pick.get("agent_analysis", {})
    workflow_id = pick.get("workflow_id", "")
    workflows = json.loads((state / "workflows.json").read_text())
    wrows = workflows if isinstance(workflows, list) else list(workflows.values())
    threshold = next((w.get("confidence_threshold") for w in wrows if w.get("workflow_id") == workflow_id and w.get("confidence_threshold")), None) or 0.7
    decision = {
        "confidence": float(analysis.get("confidence", 0)),
        "threshold": float(threshold),
        "reasoning": analysis.get("reasoning") or pick.get("reason", ""),
        "subject": pick.get("item", {}).get("subject", ""),
        "sender": pick.get("item", {}).get("sender", ""),
        "stillSeconds": 15.0,
    }

    prefs_path = state / "preferences.json"
    rule = {"pattern": "", "action": "", "match": "", "holdSeconds": 3.5}
    if prefs_path.exists():
        prefs = json.loads(prefs_path.read_text())
        prow = (prefs if isinstance(prefs, list) else list(prefs.values()))
        if prow:
            r = prow[-1]
            rule.update(pattern=r.get("pattern", ""), action=r.get("action", ""), match=r.get("match_sender") or r.get("match_domain") or ", ".join(r.get("match_keywords", []) or []))

    # The gate's lines, from the file itself.
    src = (ROOT / "src/handoff/graph/hooks/hitl.py").read_text().splitlines()
    idx = next(i for i, line in enumerate(src) if "event.interrupt(" in line and "``" not in line and line.lstrip().startswith(("response", "result", "answer")))
    start = max(0, idx - 4)
    picked = src[start: idx + 7]
    indent = min((len(line) - len(line.lstrip()) for line in picked if line.strip()), default=0)
    lines = [{"text": line[indent:][:84], "key": "event.interrupt(" in line} for line in picked]

    # A still of the decision, from the footage, after the page scrolled to it.
    stills = ROOT / "video/public/stills"
    stills.mkdir(parents=True, exist_ok=True)
    scroll = first(setup, event="scroll", to="decisions") or needs
    # The page's clock can run past the footage (the recorder settles after the
    # last event), so clamp to the clip or ffmpeg writes nothing and an old
    # still from a previous take survives.
    at_s = min((scroll or 0) + 1.6, lengths["setup"] - 0.5)
    still = stills / "decision.png"
    still.unlink(missing_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at_s:.2f}", "-i", str(clips / "clip-setup.mp4"), "-frames:v", "1", str(still)], check=True)
    if not still.exists():
        raise SystemExit(f"no decision still at {at_s:.2f}s of clip-setup.mp4")

    cues = {
        "say": {"file": "clips/clip-setup.mp4", "segments": say},
        "run": {"file": "clips/clip-setup.mp4", "segments": run},
        "decide": {"file": "clips/clip-decide.mp4", "segments": dec},
        "again": {"file": "clips/clip-again.mp4", "segments": ag, "graphAt": agraph},
        "decision": decision,
        "rule": rule,
        "gate": {"lines": lines},
        "timeline": {"setup": {"listen_start": ls, "listen_stop": lstop, "first_tool": tool1, "card": card, "graph": graph, "needs": needs}, "decide": {"listen_start": dls, "decided": decided}, "again": {"listen_start": als, "graph": agraph, "done": adone}},
    }
    out = ROOT / "video/src/data/cues.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cues, indent=1))

    # The narration quotes the numbers; make it quote these.
    words = {40: "Forty", 45: "Forty-five", 50: "Fifty", 55: "Fifty-five", 60: "Sixty", 65: "Sixty-five", 70: "Seventy", 75: "Seventy-five", 80: "Eighty"}
    pct, thr = round(decision["confidence"] * 100), round(decision["threshold"] * 100)
    sentence = f"{words.get(pct, str(pct))} percent sure. It needs {words.get(thr, str(thr)).lower()} to act alone. That gap is the product."
    spec_path = ROOT / "scripts/video/narration.json"
    spec = json.loads(spec_path.read_text())
    clips_meta = json.loads((clips / "clips.json").read_text()) if (clips / "clips.json").exists() else {}
    cold = clips_meta.get("answer", {}).get("line", "user_decide") == "user_decide"
    reasoning = (decision["reasoning"] or "").rstrip(".")
    counts = {1: "one", 2: "two", 3: "three"}
    wanted = {
        ("run", 2): f"Memory checks for rules. Gmail reads the inbox. The executor judges every message, acts on the clear ones, and sets {counts.get(set_aside, str(set_aside))} aside.",
        ("decision", 1): f"Here is why it stopped, in the agent's own words: {reasoning}.",
        ("decision", 2): sentence,
        ("decision", 3): ("I say: archive it, it is cold outreach. " if cold else "I say: archive it. ") + "Matched locally, no model round trip, and the run resumes exactly where it stopped.",
        ("quieter", 1): "Same inbox, next run: handled alone, the rest from rules, zero questions.",
    }
    for scene in spec["scenes"]:
        for i, text in enumerate(scene["sentences"]):
            new_text = wanted.get((scene["id"], i))
            if new_text and new_text != text:
                scene["sentences"][i] = new_text
                (audio / f"n-{scene['id']}-{i}.mp3").unlink(missing_ok=True)
                print(f"{scene['id']}[{i}] ->", new_text[:90])
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    print(json.dumps(cues["timeline"]))
    print(f"say {sum((s['to']-s['from'])/s['rate'] for s in say):.1f}s · run {sum((s['to']-s['from'])/s['rate'] for s in run):.1f}s · decide {sum((s['to']-s['from'])/s['rate'] for s in dec):.1f}s · again {sum((s['to']-s['from'])/s['rate'] for s in ag):.1f}s")
    print(f"decision: {pct}% vs {thr}% · rule: {rule['pattern'][:60]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
