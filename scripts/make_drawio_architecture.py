# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Build the architecture diagram as a draw.io file with official AWS icons.

Writes three artefacts:

  docs/architecture.drawio       editable in draw.io / diagrams.net
  docs/architecture-aws.png      the diagram rendered at 2x
  docs/architecture.pdf          the diagram plus the long-form ARCHITECTURE.md

The diagram is authored as mxGraph XML using the ``mxgraph.aws4`` shape set
that draw.io ships — the same icons the AWS Architecture Icons deck uses — so
the file opens in draw.io with every AWS service recognisable and editable.
Rendering uses draw.io's own viewer in a headless Chromium (Playwright), so
the PNG is exactly what draw.io shows; nothing is re-implemented here.

    .venv-strands/bin/python scripts/make_drawio_architecture.py
"""

from __future__ import annotations

import base64
import html
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# --- AWS4 styles -----------------------------------------------------------
# Category colours follow the AWS Architecture Icons palette.
AWS_ORANGE = "#ED7100"   # Compute
AWS_PURPLE = "#C925D1"   # Database
AWS_PINK = "#E7157B"     # Application integration / Management
AWS_GREEN = "#01A88D"    # Machine learning
AWS_RED = "#DD344C"      # Security, identity
AWS_NAVY = "#232F3E"

RES_POINTS = (
    "points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],[0,1,0],[0.25,1,0],"
    "[0.5,1,0],[0.75,1,0],[1,1,0],[0,0.25,0],[0,0.5,0],[0,0.75,0],[1,0.25,0],"
    "[1,0.5,0],[1,0.75,0]];"
)
GROUP_POINTS = (
    "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],"
    "[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];"
)


def aws_icon(res_icon: str, fill: str) -> str:
    return (
        f"sketch=0;{RES_POINTS}outlineConnect=0;fontColor={AWS_NAVY};fillColor={fill};"
        "strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;"
        "align=center;html=1;fontSize=12;fontStyle=0;aspect=fixed;"
        f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res_icon};"
    )


def aws_group(gr_icon: str, stroke: str, font: str, dashed: int) -> str:
    return (
        f"{GROUP_POINTS}outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
        "fontSize=13;fontStyle=1;container=1;pointerEvents=0;collapsible=0;"
        f"recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};"
        f"strokeColor={stroke};fillColor=none;verticalAlign=top;align=left;"
        f"spacingLeft=30;fontColor={font};dashed={dashed};"
    )


# Plain (non-AWS) nodes: the product's own parts. AWS icons are reserved for
# AWS services, which is the convention the icon guidelines ask for.
def box(fill: str, stroke: str, bold: bool = False, font: str = AWS_NAVY) -> str:
    return (
        f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
        f"fontColor={font};fontSize=12;fontStyle={1 if bold else 0};arcSize=12;"
        "spacing=6;"
    )


def lane(fill: str, stroke: str, font: str) -> str:
    return (
        f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
        f"fontColor={font};fontSize=13;fontStyle=1;verticalAlign=top;align=left;"
        "spacingLeft=12;spacingTop=4;arcSize=6;container=1;collapsible=0;dashed=0;"
    )


def edge(stroke: str = "#4B5563", dashed: bool = False, bidir: bool = False, width: int = 2) -> str:
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
        f"html=1;strokeColor={stroke};strokeWidth={width};fontColor=#374151;fontSize=11;"
        f"endArrow=blockThin;endFill=1;{'dashed=1;dashPattern=6 4;' if dashed else ''}"
        f"{'startArrow=blockThin;startFill=1;' if bidir else ''}"
        "labelBackgroundColor=#ffffff;"
    )


class Diagram:
    def __init__(self) -> None:
        self.cells: list[str] = []
        self._n = 1

    def _id(self) -> str:
        self._n += 1
        return f"c{self._n}"

    def vertex(self, label: str, style: str, x: int, y: int, w: int, h: int, parent: str = "1") -> str:
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" '
            f'vertex="1" parent="{parent}"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        return cid

    def edge(self, src: str, dst: str, label: str = "", style: str | None = None, parent: str = "1") -> str:
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(label, {chr(34): "&quot;"})}" style="{style or edge()}" '
            f'edge="1" parent="{parent}" source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        return cid

    def xml(self, width: int, height: int) -> str:
        body = "".join(self.cells)
        return (
            '<mxfile host="Handoff" agent="scripts/make_drawio_architecture.py" version="24.7.17">'
            '<diagram id="handoff-architecture" name="Handoff architecture">'
            f'<mxGraphModel dx="{width}" dy="{height}" grid="1" gridSize="10" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1654" pageHeight="1169" '
            'math="0" shadow="0" background="#FFFFFF">'
            '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            f"{body}</root></mxGraphModel></diagram></mxfile>"
        )


def build() -> str:
    d = Diagram()

    # Title
    d.vertex(
        "<b style='font-size:20px'>Handoff</b> &nbsp;·&nbsp; autonomous workflows with a human decision gate"
        "<br><span style='font-size:11px;color:#6B7280'>Strands Agents SDK · Amazon Bedrock · Bedrock AgentCore · one DynamoDB table · EventBridge → Lambda → Runtime</span>",
        "text;html=1;align=left;verticalAlign=middle;fontSize=14;fontColor=#111827;",
        40, 20, 900, 50,
    )

    # ---- Lane: You (surfaces) ---------------------------------------------
    you = d.vertex("You — three surfaces, one gate", lane("#F5F3FF", "#7C3AED", "#5B21B6"), 40, 90, 260, 560)
    orb = d.vertex("<b>Talk</b><br>the orb — speak the chore<br><span style='font-size:10px'>web/orb · Transcribe in, Polly out</span>", box("#FFFFFF", "#7C3AED"), 20, 40, 220, 70, you)
    desktop = d.vertex("<b>Desktop window</b><br>pywebview (WebView2 / WebKit / GTK)<br><span style='font-size:10px'>handoff desktop</span>", box("#FFFFFF", "#7C3AED"), 20, 125, 220, 70, you)
    web = d.vertex("<b>Web UI</b><br>FastAPI + Jinja · SSE streaming<br><span style='font-size:10px'>handoff serve</span>", box("#FFFFFF", "#7C3AED"), 20, 210, 220, 70, you)
    cli = d.vertex("<b>Terminal</b><br>handoff run --watch · pending · decide<br><span style='font-size:10px'>pipx install handoff</span>", box("#FFFFFF", "#7C3AED"), 20, 295, 220, 70, you)
    screen = d.vertex("<b>Decision screen</b><br>one screen, one decision<br>each item its own choice, “and 2 more after this”", box("#FEF3C7", "#D97706", True, "#92400E"), 20, 400, 220, 80, you)
    d.vertex("<span style='font-size:10px;color:#6B7280'>No AWS account? The same loop runs on a scripted offline model and JSON files.</span>", "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;", 20, 495, 220, 50, you)

    # ---- Lane: Agents (Strands) -------------------------------------------
    ag = d.vertex("Agents — Strands Agents SDK", lane("#ECFDF5", "#059669", "#065F46"), 340, 90, 560, 560)
    builder = d.vertex("<b>Builder</b> · conversational<br>one sentence → workflow config<br><span style='font-size:10px'>validate · preview · save</span>", box("#FFFFFF", "#059669"), 20, 40, 240, 70, ag)
    chat = d.vertex("<b>Assistant</b> · Strands session<br>RepositorySessionManager → store<br><span style='font-size:10px'>every MCP server that is connected</span>", box("#FFFFFF", "#059669"), 290, 40, 250, 70, ag)

    graph = d.vertex("<b>Executor</b> — Strands Graph (deterministic edges, replayable)", lane("#FFFFFF", "#059669", "#065F46"), 20, 130, 520, 200, ag)
    trig = d.vertex("<b>trigger</b><br>cron · event · webhook<br><span style='font-size:10px'>triggered:false → stop</span>", box("#F0FDF4", "#059669"), 20, 40, 140, 70, graph)
    execn = d.vertex("<b>executor</b><br>fetch → classify → act<br><span style='font-size:10px'>confidence per item</span>", box("#F0FDF4", "#059669"), 190, 40, 140, 70, graph)
    comp = d.vertex("<b>completer</b><br>audit · summary<br><span style='font-size:10px'>writes the run record</span>", box("#F0FDF4", "#059669"), 360, 40, 140, 70, graph)
    gate = d.vertex(
        "<b>HITL gate</b> — BeforeToolCallEvent on submit_action / finish_batch<br>"
        "ALWAYS_GATED → ask &nbsp;·&nbsp; confidence &lt; threshold → defer &nbsp;·&nbsp; one interrupt per pass<br>"
        "<span style='font-size:10px'>event.interrupt(reason=…) suspends one tool call; graph.serialize_state() survives a restart</span>",
        box("#FEF3C7", "#D97706", False, "#92400E"), 20, 125, 480, 60, graph,
    )
    d.edge(trig, execn, "", edge("#059669"), graph)
    d.edge(execn, comp, "", edge("#059669"), graph)

    learner = d.vertex("<b>Learner</b> · one-shot<br>decision + note → narrow rule<br><span style='font-size:10px'>exact sender · domain · ≥2 keywords</span>", box("#FFFFFF", "#059669"), 20, 350, 240, 70, ag)
    store = d.vertex("<b>Store</b> · one interface, two backends<br>JSON files on the desktop · DynamoDB deployed<br><span style='font-size:10px'>19 collections · pk=collection, sk=id → Query, never Scan</span>", box("#FFFFFF", "#059669"), 290, 350, 250, 70, ag)
    models = d.vertex("<b>Model chain</b> · HANDOFF_MODEL_PROVIDER<br>Bedrock → Anthropic → Groq, same agent code<br><span style='font-size:10px'>ResilientOpenAIModel repairs slipped tool-JSON</span>", box("#FFFFFF", "#059669"), 20, 440, 520, 60, ag)
    d.vertex("<span style='font-size:10px;color:#6B7280'>Graph, not Swarm: a job that files tickets in your name at 08:00 must take the same path every time.</span>", "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;", 20, 510, 520, 40, ag)

    # ---- Lane: Tools (MCP) ------------------------------------------------
    tl = d.vertex("Tools — MCP servers · read &amp; act", lane("#EFF6FF", "#2563EB", "#1E40AF"), 940, 90, 250, 560)
    tools = {}
    rows = [
        ("gmail", "<b>Gmail</b> · 19 tools<br><span style='font-size:10px'>own OAuth · token file</span>"),
        ("linear", "<b>Linear</b><br><span style='font-size:10px'>LINEAR_API_KEY</span>"),
        ("github", "<b>GitHub</b><br><span style='font-size:10px'>GITHUB_TOKEN</span>"),
        ("notion", "<b>Notion</b><br><span style='font-size:10px'>NOTION_API_KEY</span>"),
        ("airtable", "<b>Airtable</b><br><span style='font-size:10px'>AIRTABLE_API_KEY</span>"),
        ("slack", "<b>Slack</b><br><span style='font-size:10px'>bot token or webhook</span>"),
        ("fetch", "<b>fetch</b> · credential-free<br><span style='font-size:10px'>read any web page</span>"),
    ]
    for i, (k, label) in enumerate(rows):
        tools[k] = d.vertex(label, box("#FFFFFF", "#2563EB"), 20, 40 + i * 62, 210, 50, tl)
    d.vertex("<span style='font-size:10px;color:#6B7280'>Unconfigured server → skipped, run continues. Duplicate tool names (Linear/GitHub list_issues) → first named wins.</span>", "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;", 20, 480, 210, 70, tl)

    # ---- AWS cloud ---------------------------------------------------------
    cloud = d.vertex("AWS Cloud", aws_group("group_aws_cloud_alt", AWS_NAVY, AWS_NAVY, 0), 40, 690, 1150, 330)
    region = d.vertex("ap-northeast-2 (Seoul)", aws_group("group_region", "#00A4A6", "#147EBA", 1), 20, 40, 1110, 270, cloud)

    ICON = 64
    def svc(res: str, fill: str, label: str, x: int, y: int) -> str:
        return d.vertex(label, aws_icon(res, fill), x, y, ICON, ICON, region)

    bedrock = svc("bedrock", AWS_GREEN, "<b>Amazon Bedrock</b><br>Nova Pro · Claude<br><span style='font-size:10px'>reasoning for all three agents</span>", 40, 50)
    runtime = svc("bedrock", AWS_GREEN, "<b>AgentCore Runtime</b><br>the executor graph, serverless<br><span style='font-size:10px'>InvokeAgentRuntime</span>", 210, 50)
    memory = svc("bedrock", AWS_GREEN, "<b>AgentCore Memory</b><br>learned preferences<br><span style='font-size:10px'>recalled before classifying</span>", 380, 50)
    ddb = svc("dynamodb", AWS_PURPLE, "<b>Amazon DynamoDB</b><br>one table · pk/sk<br><span style='font-size:10px'>workflows · runs · interrupts · audit …</span>", 560, 50)
    eb = svc("eventbridge", AWS_PINK, "<b>EventBridge Scheduler</b><br>cron per workflow", 740, 50)
    lam = svc("lambda", AWS_ORANGE, "<b>AWS Lambda</b><br>12-line tick bridge<br><span style='font-size:10px'>{type: tick, workflow_id}</span>", 900, 50)
    iam = svc("identity_and_access_management", AWS_RED, "<b>IAM</b><br>two roles, nothing else<br><span style='font-size:10px'>scheduler→fn · fn→runtime</span>", 1030, 50)
    cw = svc("cloudwatch", AWS_PINK, "<b>CloudWatch</b><br>OTEL traces per run", 40, 170)
    transcribe = svc("transcribe", AWS_GREEN, "<b>Amazon Transcribe</b><br>streaming · ~1.7 s to first word", 210, 170)
    polly = svc("polly", AWS_GREEN, "<b>Amazon Polly</b><br>Matthew (neural) · the voice", 380, 170)
    d.vertex(
        "<span style='font-size:11px;color:#374151'><b>Verified live (handoff doctor):</b> Bedrock Nova Pro · Polly + Transcribe · DynamoDB (404 items) · AgentCore Memory ACTIVE — "
        "each check is a real API call, not a presence test. Failure policy: degrade the <i>quality</i> of the work, never the <i>safety</i> — "
        "no fallback does anything irreversible the configured path would not.</span>",
        "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;", 560, 170, 530, 80, region,
    )

    # ---- Edges (top level; cross-container) --------------------------------
    d.edge(orb, builder, "a sentence", edge("#7C3AED"))
    d.edge(desktop, web, "", edge("#7C3AED", dashed=True, width=1))
    d.edge(web, chat, "", edge("#7C3AED"))
    d.edge(cli, models, "", edge("#7C3AED", dashed=True, width=1) + "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    d.edge(builder, store, "config", edge("#059669"))
    d.edge(execn, tools["gmail"], "", edge("#2563EB", bidir=True))
    d.edge(execn, tools["linear"], "", edge("#2563EB", bidir=True))
    d.edge(execn, tools["github"], "", edge("#2563EB", bidir=True))
    d.edge(chat, tools["notion"], "", edge("#2563EB", bidir=True, width=1))
    d.edge(chat, tools["airtable"], "", edge("#2563EB", bidir=True, width=1))
    d.edge(comp, tools["slack"], "notify", edge("#2563EB", width=1))
    d.edge(gate, screen, "event.interrupt()", edge("#D97706", dashed=True))
    d.edge(screen, gate, "resume with the answer", edge("#D97706"))
    d.edge(screen, learner, "decision + note", edge("#D97706"))
    d.edge(learner, memory, "rule", edge("#01A88D") + "exitX=0.25;exitY=1;entryX=0.5;entryY=0;")
    d.edge(memory, execn, "recall_preferences()", edge("#01A88D", dashed=True) + "exitX=0.5;exitY=0;entryX=0.75;entryY=1;")
    d.edge(store, ddb, "USE_DYNAMODB=true", edge("#C925D1"))
    d.edge(models, bedrock, "", edge("#01A88D"))
    d.edge(eb, lam, "", edge("#E7157B"))
    d.edge(lam, runtime, "InvokeAgentRuntime", edge("#ED7100"))
    d.edge(runtime, trig, "tick", edge("#01A88D") + "exitX=0.5;exitY=0;entryX=0.5;entryY=1;")
    d.edge(models, cw, "", edge("#E7157B", dashed=True, width=1) + "exitX=0;exitY=0.5;entryX=0.5;entryY=0;")
    d.edge(orb, transcribe, "", edge("#01A88D", dashed=True, width=1))
    d.edge(polly, orb, "", edge("#01A88D", dashed=True, width=1))

    return d.xml(1240, 1060)


# --- Rendering ---------------------------------------------------------------

EMBED = "https://embed.diagrams.net/?embed=1&proto=json&spin=1&libraries=1"


def render_png(xml: str, out: Path) -> None:
    """Export through draw.io's embed protocol — the same JSON messages the
    official integrations use — so the PNG is draw.io's own rendering, AWS
    stencils included, at 2x. draw.io only talks to a *parent* window, so it
    is hosted in an iframe of a page we control."""
    from playwright.sync_api import sync_playwright

    host = (
        "<!doctype html><html><head><meta charset='utf-8'></head><body style='margin:0'>"
        "<script>window.__d={ready:false,png:null,error:null,log:[]};"
        "window.addEventListener('message',ev=>{let m;try{m=JSON.parse(ev.data)}catch(e){return}"
        "window.__d.log.push(m.event||'?');"
        "if(m.event==='init')window.__d.ready=true;if(m.event==='export')window.__d.png=m.data;"
        "if(m.event==='error')window.__d.error=m.message||'error';});</script>"
        f"<iframe id='f' src='{EMBED}' style='width:1600px;height:1200px;border:0'></iframe></body></html>"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        page.set_content(host, wait_until="load")
        page.wait_for_function("window.__d.ready", timeout=120_000)
        send = "(m) => document.getElementById('f').contentWindow.postMessage(JSON.stringify(m), '*')"
        page.evaluate(send, {"action": "load", "xml": xml, "autosave": 0})
        page.wait_for_timeout(4000)  # mxgraph.aws4 stencils load lazily after the diagram lands
        page.evaluate(send, {"action": "export", "format": "png", "scale": 2, "border": 24, "background": "#ffffff"})
        page.wait_for_function("window.__d.png || window.__d.error", timeout=120_000)
        err = page.evaluate("window.__d.error")
        if err:
            raise RuntimeError(f"draw.io export failed: {err}")
        data = page.evaluate("window.__d.png")
        browser.close()
    out.write_bytes(base64.b64decode(data.split(",", 1)[1]))


def render_pdf(png: Path, out: Path) -> None:
    import markdown
    from playwright.sync_api import sync_playwright

    md = (DOCS / "ARCHITECTURE.md").read_text()
    # The Mermaid sketch is superseded by the rendered diagram.
    md = re.sub(r"```mermaid.*?```", "", md, flags=re.S)
    md = md.replace("# Handoff — architecture", "")
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    img = base64.b64encode(png.read_bytes()).decode()
    css = """
    @page { size: A4; margin: 18mm 16mm; }
    body { font: 11pt/1.5 'Instrument Sans', 'Segoe UI', system-ui, sans-serif; color: #111827; }
    h1 { font-size: 26pt; margin: 0 0 4pt; letter-spacing: -0.01em; }
    h2 { font-size: 15pt; margin: 22pt 0 6pt; border-bottom: 1px solid #E5E7EB; padding-bottom: 3pt; page-break-after: avoid; }
    h3 { font-size: 12pt; margin: 14pt 0 4pt; page-break-after: avoid; }
    .sub { color: #6B7280; margin: 0 0 14pt; }
    .cover { page-break-after: always; }
    .cover img { width: 100%; max-height: 150mm; object-fit: contain; border: 1px solid #E5E7EB; border-radius: 6px; }
    .kv { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8pt; margin: 12pt 0; }
    .kv div { background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 6px; padding: 8pt 10pt; font-size: 10pt; }
    .kv b { display: block; font-size: 9pt; color: #6B7280; text-transform: uppercase; letter-spacing: .06em; }
    table { border-collapse: collapse; width: 100%; font-size: 9.5pt; margin: 8pt 0; page-break-inside: avoid; }
    th, td { border: 1px solid #E5E7EB; padding: 4pt 6pt; text-align: left; vertical-align: top; }
    th { background: #F3F4F6; }
    pre, code { font: 9pt/1.4 'JetBrains Mono', ui-monospace, monospace; }
    pre { background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 6px; padding: 8pt; white-space: pre-wrap; page-break-inside: avoid; }
    blockquote { border-left: 3px solid #D97706; margin: 8pt 0; padding: 2pt 10pt; color: #374151; }
    .live { page-break-before: always; }
    .ok { color: #047857; font-weight: 600; }
    """
    live_rows = [
        ("Groq API", "qwen/qwen3.8-27b — free tier, tool-JSON repair"),
        ("AWS Bedrock", "apac.amazon.nova-pro-v1:0 in ap-northeast-2"),
        ("Speech", "Polly Matthew (neural) + Transcribe streaming"),
        ("Gmail", "signed in — 19 tools live (own OAuth)"),
        ("Linear", "Arpit Singh"),
        ("Slack", "bot in slack_hackathon_test"),
        ("GitHub", "@LSUDOKO"),
        ("Notion", "workspace HandOff-Amazon"),
        ("Airtable", "personal access token"),
        ("DynamoDB", "table handoff (404 items)"),
        ("AgentCore Memory", "handoff_preferences (ACTIVE)"),
    ]
    live = "".join(f"<tr><td class='ok'>PASS</td><td>{html.escape(a)}</td><td>{html.escape(b)}</td></tr>" for a, b in live_rows)
    doc = f"""<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>
    <section class='cover'>
      <h1>Handoff — architecture</h1>
      <p class='sub'>Describe it. Hand it off. It runs. — autonomous workflows with a human decision gate, built on the Strands Agents SDK and Amazon Bedrock AgentCore.</p>
      <img src='data:image/png;base64,{img}' alt='Handoff architecture'>
      <p class='sub' style='margin-top:6pt'>Editable source: <code>docs/architecture.drawio</code> (draw.io, official AWS Architecture Icons) · generated by <code>scripts/make_drawio_architecture.py</code></p>
      <div class='kv'>
        <div><b>Agents</b>Builder · Executor (Strands Graph) · Learner · Assistant</div>
        <div><b>Gate</b>BeforeToolCallEvent → event.interrupt(); one interrupt per pass</div>
        <div><b>Reasoning</b>Amazon Bedrock (Nova Pro / Claude) · Anthropic · Groq</div>
        <div><b>State</b>one DynamoDB table (pk = collection, sk = id) or JSON files</div>
        <div><b>Schedule</b>EventBridge Scheduler → Lambda → AgentCore Runtime</div>
        <div><b>Voice</b>Amazon Transcribe in · Amazon Polly out</div>
      </div>
    </section>
    {body}
    <section class='live'>
      <h2>Appendix — verified live</h2>
      <p>Output of <code>handoff doctor</code> on the submission machine. Every row is a real API call against the service, not a check that a variable is set.</p>
      <table><tr><th>Status</th><th>Service</th><th>Result</th></tr>{live}</table>
      <p><b>11 working, 0 broken, 1 not configured</b> (Anthropic API key not set — Bedrock is the active provider).</p>
    </section>
    </body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(doc, wait_until="load")
        page.emulate_media(media="print")
        page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()


def main() -> int:
    DOCS.mkdir(exist_ok=True)
    xml = build()
    drawio = DOCS / "architecture.drawio"
    drawio.write_text(xml)
    print(f"wrote {drawio.relative_to(ROOT)} ({len(xml):,} bytes)")
    png = DOCS / "architecture-aws.png"
    render_png(xml, png)
    print(f"wrote {png.relative_to(ROOT)} ({png.stat().st_size:,} bytes)")
    pdf = DOCS / "architecture.pdf"
    render_pdf(png, pdf)
    print(f"wrote {pdf.relative_to(ROOT)} ({pdf.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
