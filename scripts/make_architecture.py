# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Write docs/architecture.excalidraw — the system, as an editable diagram.

Excalidraw's file format is plain JSON: elements with positions, sizes, text
and bindings. Generating it here makes the diagram data the repo owns; the
layout is a table of boxes and routed arrows rather than something dragged
by hand. Open the file at excalidraw.com or with the VS Code extension;
``scripts/export_architecture.py`` renders the PNG and SVG in the README.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(7)
OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture.excalidraw"

INK = "#1e1e1e"
AMBER = "#b7791f"
#: Excalifont is wide; this is the average glyph width as a fraction of size.
GLYPH = 0.62
elements: list[dict] = []
_counter = 0


def _id() -> str:
    global _counter
    _counter += 1
    return f"el{_counter:04d}"


def _base(kind: str, x: float, y: float, w: float, h: float, **extra) -> dict:
    return {
        "id": _id(), "type": kind, "x": x, "y": y, "width": w, "height": h, "angle": 0,
        "strokeColor": INK, "backgroundColor": "transparent", "fillStyle": "solid",
        "strokeWidth": 1.5, "strokeStyle": "solid", "roughness": 1, "opacity": 100,
        "groupIds": [], "frameId": None, "roundness": {"type": 3} if kind == "rectangle" else None,
        "seed": random.randint(1, 2**31), "version": 1, "versionNonce": random.randint(1, 2**31),
        "isDeleted": False, "boundElements": [], "updated": 1, "link": None, "locked": False, **extra,
    }


def wrap(s: str, size: float, width: float) -> str:
    """Excalidraw stores wrapped text as-is on export, so wrap here."""
    limit = max(8, int(width / (size * GLYPH)))
    out: list[str] = []
    for para in s.split("\n"):
        line = ""
        for word in para.split(" "):
            if line and len(line) + 1 + len(word) > limit:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return "\n".join(out)


def text(x, y, s, size=16, w=None, align="left", color=INK, container=None):
    lines = s.split("\n")
    width = w or max(len(line) for line in lines) * size * GLYPH
    el = _base("text", x, y, width, size * 1.25 * len(lines), text=s, fontSize=size, fontFamily=5,
               textAlign=align, verticalAlign="top", containerId=container, originalText=s,
               lineHeight=1.25, strokeColor=color, autoResize=container is None)
    elements.append(el)
    return el


def box(x, y, w, h, label, fill="#ffffff", sub=None, size=16, sub_size=13, stroke=INK):
    el = _base("rectangle", x, y, w, h, backgroundColor=fill, strokeColor=stroke)
    elements.append(el)
    body = wrap(label, size, w - 24)
    if sub:
        body += "\n" + wrap(sub, sub_size, w - 24)
    label_el = text(x + 12, y, body, size=size, w=w - 24, align="center", container=el["id"])
    label_el["verticalAlign"] = "middle"
    label_el["height"] = h
    el["boundElements"].append({"id": label_el["id"], "type": "text"})
    return el


def region(x, y, w, h, title, fill):
    el = _base("rectangle", x, y, w, h, backgroundColor=fill, strokeStyle="dashed", strokeWidth=1)
    elements.append(el)
    text(x + 16, y + 10, title, size=15, color="#444")
    return el


def arrow(a, b, label=None, sa="right", sb="left", oa=0, ob=0, dashed=False, color=INK, via=None, label_at=0.5):
    """An arrow from side ``sa`` of ``a`` to side ``sb`` of ``b``.

    ``oa``/``ob`` slide the anchor along that side; ``via`` lists absolute
    corner points the arrow passes through, so routes can avoid text.
    """
    def side(el, s, off):
        x, y, w, h = el["x"], el["y"], el["width"], el["height"]
        return {"right": (x + w, y + h / 2 + off), "left": (x, y + h / 2 + off),
                "top": (x + w / 2 + off, y), "bottom": (x + w / 2 + off, y + h)}[s]
    (x1, y1), (x2, y2) = side(a, sa, oa), side(b, sb, ob)
    corners = [(x1, y1)] + [tuple(v) for v in (via or [])] + [(x2, y2)]
    pts = [[round(cx - x1, 1), round(cy - y1, 1)] for cx, cy in corners]
    el = _base("arrow", x1, y1, abs(pts[-1][0]) or 1, abs(pts[-1][1]) or 1, points=pts, lastCommittedPoint=None,
               startBinding={"elementId": a["id"], "focus": 0, "gap": 4}, endBinding={"elementId": b["id"], "focus": 0, "gap": 4},
               startArrowhead=None, endArrowhead="arrow", strokeColor=color, strokeStyle="dashed" if dashed else "solid", elbowed=False)
    el["roundness"] = {"type": 2}
    elements.append(el)
    a["boundElements"].append({"id": el["id"], "type": "arrow"})
    b["boundElements"].append({"id": el["id"], "type": "arrow"})
    if label:
        # Place the label on the longest segment, nudged off the line.
        segs = [(corners[i], corners[i + 1]) for i in range(len(corners) - 1)]
        (ax, ay), (bx, by) = max(segs, key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
        mx, my = ax + (bx - ax) * label_at, ay + (by - ay) * label_at
        t = text(0, 0, label, size=12, color="#555")
        horizontal = abs(bx - ax) >= abs(by - ay)
        t["x"] = mx - t["width"] / 2 if horizontal else mx + 8
        t["y"] = my - 20 if horizontal else my - t["height"] / 2
    return el


# ---- Layout ---------------------------------------------------------------------
text(40, 20, "Handoff — how a sentence becomes a run that asks once", size=28)
text(40, 60, "Strands Agents SDK 1.55 · Amazon Bedrock · AgentCore Runtime + Memory · Transcribe + Polly · DynamoDB · EventBridge → Lambda", size=14, color="#555")

# You
region(40, 110, 340, 590, "You", "#fff7e6")
talk = box(60, 150, 300, 90, "Talk — the orb", sub="speak · hear it · watch it work")
cli = box(60, 270, 300, 80, "CLI", sub="handoff chat · run --watch · talk")
web = box(60, 380, 300, 80, "Web / Desktop", sub="FastAPI + HTMX · pywebview window")
decide = box(60, 500, 300, 110, "The decision screen", fill="#fff1cc", sub="one item · why it stopped · four buttons · amber = waiting on you", stroke=AMBER)

# Speech
region(420, 110, 660, 130, "Speech (AWS)", "#eef6ff")
transcribe = box(440, 150, 300, 70, "Amazon Transcribe", sub="streaming, over a WebSocket")
polly = box(760, 150, 300, 70, "Amazon Polly", sub="neural voice · cached phrases")

# Agents
region(420, 280, 660, 420, "Agents — Strands Agents SDK", "#f1f5f0")
assistant = box(440, 330, 300, 100, "Assistant / voice agent", sub="Agent + SessionRepository · tools: activate_workflow, start_run")
builder = box(440, 470, 300, 70, "Builder", sub="sentence → workflow config")
graph_box = box(770, 330, 290, 210, "Workflow Graph", sub="trigger → executor → completer · HITL gate: BeforeToolCallEvent → interrupt() · RunNarrator: node + tool timings", size=16, sub_size=13)
learner = box(440, 590, 620, 60, "Learner", sub="each decision → one narrow rule (sender, domain, or two keywords)")

# AWS
region(1120, 110, 440, 590, "AWS (ap-northeast-2)", "#fff4f0")
bedrock = box(1150, 150, 380, 70, "Amazon Bedrock", sub="Nova Pro / Nova Lite · cross-region profiles")
runtime = box(1150, 250, 380, 70, "AgentCore Runtime", sub="arm64 container · session per run")
memory = box(1150, 350, 380, 60, "AgentCore Memory", sub="learned preferences")
dynamo = box(1150, 440, 380, 60, "DynamoDB — one table", sub="pk = collection · sk = id")
sched = box(1150, 530, 180, 70, "EventBridge Scheduler", size=14)
lam = box(1350, 530, 180, 70, "Lambda bridge", sub="12 lines", size=14)
mcp = box(1150, 630, 380, 50, "MCP servers — Gmail · Linear · Slack · GitHub · web", size=13)

site = box(420, 730, 660, 50, "Static site + guides — Cloudflare Pages (handoff-eya.pages.dev)", size=14)

# Arrows
arrow(talk, transcribe, "audio", sa="right", sb="left", oa=-15, ob=-15)
arrow(polly, talk, "reply audio", sa="bottom", sb="right", ob=20, dashed=True, via=[(910, 258), (395, 258)])
arrow(transcribe, assistant, "text", sa="bottom", sb="top", oa=-60, ob=-60)
arrow(assistant, polly, "spoken reply", sa="top", sb="bottom", oa=80, dashed=True, via=[(670, 300), (910, 300)])
arrow(cli, assistant, "one session", sa="right", sb="left", ob=-20, via=[(400, 310), (400, 360)])
arrow(web, graph_box, "Run now", sa="right", sb="left", ob=100, via=[(400, 420), (400, 445), (755, 445)], label_at=0.6)
arrow(assistant, builder, None, sa="bottom", sb="top")
arrow(assistant, graph_box, "start_run", sa="right", sb="left", oa=-20, ob=-20)
arrow(graph_box, decide, "interrupt → one screen", sa="left", sb="bottom", oa=90, via=[(755, 525), (755, 672), (210, 672)], color=AMBER)
arrow(decide, graph_box, "answer → resume", sa="right", sb="left", oa=-30, ob=40, dashed=True, color=AMBER, via=[(405, 525), (405, 475), (755, 475)], label_at=0.6)
arrow(graph_box, learner, "decisions", sa="bottom", sb="top", oa=60, ob=225)
arrow(graph_box, bedrock, "model calls", sa="right", sb="left", oa=-80, via=[(1095, 355), (1095, 185)])
arrow(graph_box, mcp, "tool calls", sa="right", sb="left", oa=90, via=[(1100, 525), (1100, 655)])
arrow(learner, memory, "rules", sa="right", sb="left", dashed=True, via=[(1108, 620), (1108, 380)])
arrow(sched, lam, "tick", sa="right", sb="left")
arrow(lam, runtime, "invoke_agent_runtime", sa="right", sb="right", via=[(1548, 565), (1548, 285)])
arrow(runtime, graph_box, "runs the same Graph", sa="left", sb="right", ob=-40, dashed=True, via=[(1120, 285), (1120, 395)])
arrow(dynamo, graph_box, "state · runs · interrupts · sessions", sa="left", sb="right", ob=10, dashed=True, via=[(1112, 470), (1112, 445)])

doc = {"type": "excalidraw", "version": 2, "source": "https://github.com/LSUDOKO/Handoff", "elements": elements,
       "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"}, "files": {}}
OUT.write_text(json.dumps(doc, indent=1))
print(f"wrote {OUT} ({len(elements)} elements)")
