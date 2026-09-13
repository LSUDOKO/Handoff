# Voice Orb, CLI, Theme and Site — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speak to Handoff and watch it work on the same page; use every feature from a terminal; give the whole product the kelbro theme; publish a landing site and docs on Cloudflare Pages.

**Architecture:** The orb page is a thin client over the existing `ChatService` (one Strands `Agent` per chat, persisted through `StoreSessionRepository`) plus a `RunNarrator` hook on the workflow `Graph` that emits tool timings on the events bus. Speech is a new `handoff.speech` package with AWS (Transcribe streaming + Polly) first, Groq second, browser last. The CLI is a package of argparse subcommand modules sharing one `rich` console. The site is static HTML built by a Python script and deployed with wrangler.

**Tech Stack:** Python 3.12 (`.venv-strands`), Strands Agents SDK 1.55, FastAPI + HTMX + Jinja2, `amazon-transcribe`, boto3 (Polly), `rich`, `markdown`, `sounddevice` (optional), WebGL2, wrangler 4.

**Spec:** `docs/superpowers/specs/2026-09-13-voice-orb-cli-site-design.md`

## Global Constraints

- Python is `.venv-strands/bin/python`; run tests with `HANDOFF_FAKE_MODEL=true .venv-strands/bin/python -m pytest tests -q`; lint with `.venv-strands/bin/python -m ruff check src tests scripts infra site`.
- Every new Python file starts with the two-line copyright / SPDX header used across `src/handoff`.
- No secrets in git. Before every commit: `git diff --cached --name-only | grep -Ei '\.env|\.png|friday-studio|kelbro|DORA'` must be empty and `git diff --cached | grep -E 'gsk_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}'` must be empty.
- Commit messages are one line, followed by a blank line and `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Amber (`--needs-you`) means only "waiting on you". Never use it for anything else.
- AWS spend: test speech on short phrases; run real-model tests on Nova Lite (`apac.amazon.nova-lite-v1:0`), never Nova Pro, until the demo take.
- Do not copy files from `kelbro/` or `DORA/` into the repo. Re-express CSS against Handoff tokens; re-type the shader.
- New nav item label is exactly `Talk`, href `/orb`, icon `i-mic`.

---

## File map

**Created**
- `src/handoff/speech/__init__.py` — facade: `provider()`, `transcribe()`, `speak()`, `status()`
- `src/handoff/speech/aws.py` — Transcribe streaming + Polly
- `src/handoff/speech/groq.py` — moved from `tools/voice.py`
- `src/handoff/speech/wav.py` — `pcm_to_wav()`, `wav_to_pcm()`, `is_wav()`
- `src/handoff/graph/hooks/narrator.py` — `RunNarrator(HookProvider)`
- `src/handoff/chat/voice_tools.py` — `activate_workflow`, `start_run`, `current_channel` contextvar
- `src/handoff/web/static/orb.js`, `orb.css`, `pcm-worklet.js`, `work-panel.js`
- `src/handoff/web/templates/orb.html`, `_work_card.html`
- `src/handoff/cli/` package (14 modules, see Task C1)
- `src/handoff/docs.py` — markdown → HTML for `/docs` and the site
- `src/handoff/web/templates/docs.html`
- `docs/site/*.md` — user-facing docs (8 files)
- `site/build.py`, `site/index.html`, `site/assets/site.css`, `site/assets/site.js`, `site/templates/doc.html`
- `tests/test_speech.py`, `tests/test_orb.py`, `tests/test_cli.py`, `tests/test_site_build.py`, `tests/test_docs.py`

**Modified**
- `src/handoff/web/static/tokens.css`, `ui.css`, `app.js` — theme
- `src/handoff/web/templates/base.html` — fonts, brand, docs link
- `src/handoff/web/nav.py` — `Talk` item
- `src/handoff/web/server.py` — orb routes, docs routes, voice routes on the facade
- `src/handoff/config.py` — speech settings
- `src/handoff/doctor.py` — `check_speech`
- `src/handoff/platform/credentials.py` — AWS speech row in `catalogue()`
- `src/handoff/graph/factory.py` — bind `RunNarrator`
- `src/handoff/chat/service.py` — `Narrator` moves to the shared hook; voice prompt; `kind`
- `src/handoff/platform/models.py` — `Chat.kind`
- `src/handoff/tools/voice.py` — keep `parse_command`, `decision_prompt`; re-export facade
- `src/handoff/desktop.py` — orb default, js bridge, hotkey
- `pyproject.toml` — `rich`, `markdown` deps; `voice` extra
- `Makefile` — `site`, `site-deploy`
- `.env.example` — speech block
- `README.md`, `docs/SUBMISSION.md`, `docs/DEMO.md`

---

## Phase A — Foundations

### Task A1: kelbro theme on every page

**Files:**
- Modify: `src/handoff/web/static/tokens.css` (palette + fonts + new tokens)
- Modify: `src/handoff/web/static/ui.css` (`.button.accent`, `.button.secondary`, `.card`, `.nav-item[aria-current]`, brand)
- Modify: `src/handoff/web/static/app.js` (theme toggle with View Transitions)
- Modify: `src/handoff/web/templates/base.html` (font links, wordmark)
- Test: `tests/test_theme.py`

**Produces:** tokens `--accent`, `--accent-ink`, `--wash`, `--ease-out-expo`, `--ease-spring`; class `.wordmark` (Comfortaa).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_theme.py
from pathlib import Path
STATIC = Path("src/handoff/web/static")
TPL = Path("src/handoff/web/templates")

def test_tokens_define_kelbro_palette_and_fonts():
    css = (STATIC / "tokens.css").read_text()
    assert "Instrument Sans" in css and "JetBrains Mono" in css
    assert "--accent:" in css and "--accent-ink:" in css and "--wash:" in css
    assert "oklch(0.965 0.008 85)" in css          # light ground
    assert "oklch(0.16 0.006 85)" in css           # dark ground
    assert "oklch(0.9 0.035 70)" in css            # champagne accent

def test_base_loads_google_fonts_and_wordmark():
    html = (TPL / "base.html").read_text()
    assert "fonts.googleapis.com/css2?family=Instrument+Sans" in html
    assert "Comfortaa" in html
    assert 'class="wordmark"' in html
```

- [ ] **Step 2: Run, expect FAIL** — `pytest tests/test_theme.py -q`
- [ ] **Step 3: Implement.** In `tokens.css` replace the primitive palette block with the oklch values from the spec table; set `--font-sans: "Instrument Sans", ...` and `--font-mono: "JetBrains Mono", ...`; add `--font-brand: "Comfortaa", var(--font-sans)`; add `--accent`, `--accent-ink`, `--wash` as `light-dark()` pairs; add easing tokens. In `ui.css` restyle `.button.accent` (background `var(--accent)`, color `var(--accent-ink)`, the three-layer box-shadow, `transform: scale(0.975)` on hover), `.button.secondary` (glass: gradient of `--wash` at 4/14/4 %, 1 px border at 16 %, backdrop blur 14 px), `.card` (`border-radius: 22px` when `.card.panel`, layered shadow), `.nav-item[aria-current="page"]` (pill: `background: color-mix(in oklab, var(--wash) 92%, var(--surface-dark))`, `color: var(--surface-dark)`, radius 9999px). In `base.html` add the preconnect + stylesheet links for `Instrument+Sans:wght@400;500;600;700`, `Comfortaa:wght@600;700`, `JetBrains+Mono:wght@400;500`; replace the brand `<h1>Handoff</h1>` with `<span class="wordmark">handoff</span>` and the accent square mark. In `app.js` wrap the theme switch in `document.startViewTransition` with a `clipPath` circle animation from the click point (900 ms, `cubic-bezier(0.16,1,0.3,1)`), skipping when `prefers-reduced-motion`.
- [ ] **Step 4: Run test + full suite, expect PASS.** Open `/activity`, `/chat`, `/settings` in a browser and confirm fonts and palette in both themes.
- [ ] **Step 5: Commit** — `Kelbro theme: Instrument Sans, oklch cream palette, glass and accent surfaces on every page`

### Task A2: Speech package on AWS

**Files:**
- Create: `src/handoff/speech/__init__.py`, `aws.py`, `groq.py`, `wav.py`
- Modify: `src/handoff/config.py`, `src/handoff/tools/voice.py`, `src/handoff/doctor.py`, `src/handoff/platform/credentials.py`, `src/handoff/web/server.py` (voice routes), `.env.example`, `pyproject.toml`
- Create: `src/handoff/web/static/pcm-worklet.js`
- Test: `tests/test_speech.py`

**Produces (exact signatures):**

```python
# handoff/speech/__init__.py
def provider() -> str                       # "aws" | "groq" | "browser"
def transcribe(audio: bytes, filename: str = "speech.wav", language: str | None = None) -> dict  # {"text": str} or {"text": "", "error": str}
def speak(text: str, voice: str | None = None) -> tuple[bytes | None, str, str]  # (audio, mime, reason)
def status() -> dict  # {"provider", "stt", "tts", "voice", "region", "engine"}
# handoff/speech/wav.py
def pcm_to_wav(pcm: bytes, rate: int = 16000, channels: int = 1) -> bytes
def wav_to_pcm(wav: bytes) -> tuple[bytes, int, int]   # (pcm16, rate, channels)
def is_wav(data: bytes) -> bool
```

Config additions in `config.py`:

```python
SPEECH_PROVIDER = os.getenv("HANDOFF_SPEECH_PROVIDER", "auto").lower()
POLLY_VOICE = os.getenv("POLLY_VOICE", "Matthew")
POLLY_ENGINE = os.getenv("POLLY_ENGINE", "neural")
TRANSCRIBE_LANGUAGE = os.getenv("TRANSCRIBE_LANGUAGE", "en-US")
```

- [ ] **Step 1: Failing tests**

```python
# tests/test_speech.py
import struct
from handoff.speech import wav

def test_pcm_wav_round_trip():
    pcm = struct.pack("<8h", *range(8))
    data = wav.pcm_to_wav(pcm, 16000, 1)
    assert wav.is_wav(data) and data[:4] == b"RIFF"
    back, rate, ch = wav.wav_to_pcm(data)
    assert (back, rate, ch) == (pcm, 16000, 1)

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
    monkeypatch.setattr(config, "SPEECH_PROVIDER", "browser")
    monkeypatch.setattr(speech, "_aws_ready", lambda: True)
    assert speech.provider() == "browser"

def test_speak_returns_reason_when_browser():
    import handoff.speech as speech
    from handoff import config
    config.SPEECH_PROVIDER = "browser"
    audio, mime, reason = speech.speak("hello")
    assert audio is None and reason == "browser"
```

- [ ] **Step 2: Run, expect FAIL** (no module `handoff.speech`).
- [ ] **Step 3: Implement.**
  - `wav.py`: pure `struct` RIFF writer/reader; `wav_to_pcm` handles 8/16-bit and stereo → mono downmix by averaging, resamples nothing (the browser already sends 16 kHz).
  - `aws.py`: `def transcribe_pcm(pcm: bytes, rate: int, language: str) -> str` runs `asyncio.run(_stream(...))` using `TranscribeStreamingClient(region=config.AWS_REGION)`; sends 3200-byte chunks with `await asyncio.sleep(0)` between them, `end_stream()`, collects final (`not result.is_partial`) transcripts from a `TranscriptResultStreamHandler`. `def synthesize(text, voice, engine) -> bytes` calls `boto3.client("polly").synthesize_speech(Text=text[:2900], VoiceId=voice, Engine=engine, OutputFormat="mp3")` with an `functools.lru_cache(maxsize=64)` on `(text, voice, engine)`. `def ready() -> bool` returns True when `boto3.Session().get_credentials()` is not None and `config.AWS_REGION` is set.
  - `groq.py`: `transcribe(audio, filename, language)` and `speak(text, voice)` moved verbatim from `tools/voice.py`.
  - `__init__.py`: `_aws_ready = aws.ready` (module attr so tests can patch); `provider()`; `transcribe()` converts WAV → PCM for AWS, passes bytes through for Groq, returns `{"text": "", "error": "browser"}` for browser; `speak()` returns `(mp3, "audio/mpeg", "")` for AWS, `(wav, "audio/wav", "")` for Groq, `(None, "", "browser")` otherwise; `status()`.
  - `tools/voice.py`: delete `transcribe`, `speak`, `stt_available`; add `from handoff.speech import transcribe, speak, status` and `def stt_available(): return status()["stt"]`.
  - `server.py` voice routes: `/api/voice/speak` returns `Response(content=audio, media_type=mime)`; `/api/voice/status` returns `speech.status()`.
  - `doctor.py`: `check_speech()` — Polly `synthesize_speech(Text="Ready.")` then a Transcribe stream fed 0.5 s of zeros; returns the same dict shape the other checks use; add `"speech": check_speech` to `CHECKS`.
  - `credentials.py` `catalogue()`: append a non-secret row `{"provider": "aws_speech", "label": "AWS speech (Transcribe + Polly)", "category": "voice", "connected": aws.ready(), "hint": f"{POLLY_VOICE} · {AWS_REGION}", ...}`. Template `_credentials_list.html` shows it read-only (`{% if c.category == 'voice' %}` → no form, a "Test" button posting to `/credentials/speech/check` that runs `check_speech`).
  - `pcm-worklet.js`: `class PCMWorklet extends AudioWorkletProcessor` accumulating Float32 input, downsampling from `sampleRate` to 16000 by linear interpolation, posting `Int16Array` buffers of 4096 samples via `this.port.postMessage`.
  - `.env.example`: a `# --- Speech ---` block with the four variables and one line each explaining `auto`.
  - `pyproject.toml`: add `"amazon-transcribe>=0.6.0"` to `bedrock` extra, `voice = ["sounddevice>=0.5"]` extra.
- [ ] **Step 4: Run tests, expect PASS.** Then a real check: `.venv-strands/bin/python -m handoff.cli doctor speech` → both lines green in ap-northeast-2.
- [ ] **Step 5: Commit** — `Speech on AWS: Transcribe streaming and Polly behind one facade, Groq and browser as fallbacks`

### Task A3: RunNarrator on the workflow graph

**Files:**
- Create: `src/handoff/graph/hooks/narrator.py`
- Modify: `src/handoff/chat/service.py` (import `Narrator` from the new module, delete the local class), `src/handoff/graph/factory.py` (bind to all three nodes), `src/handoff/agents/executor.py` (pass `run.run_id` as channel)
- Test: `tests/test_orb.py::TestRunNarrator`

**Produces:**

```python
class Narrator(HookProvider):
    def __init__(self, channel: str, turn: int = 0, node: str = "") -> None
    # events emitted on `channel`:
    #   tool_start {turn, node, tool_id, name, input}
    #   tool_end   {turn, node, tool_id, name, output, status, ms}
    #   node_start {node}  /  node_end {node, ms}   (from BeforeInvocationEvent / AfterInvocationEvent)
    steps: list[dict]
def bind_graph_narrator(channel: str, agents: dict[str, Agent]) -> list[Narrator]
```

- [ ] **Step 1: Failing test**

```python
class TestRunNarrator:
    def test_tool_events_carry_node_and_timing(self):
        from strands import Agent, tool
        from handoff import events
        from handoff.graph.hooks.narrator import Narrator
        from handoff.testing.fake_model import FakeModel

        @tool
        def ping() -> str:
            return "pong"
        n = Narrator("run:test", node="executor")
        agent = Agent(model=FakeModel(), tools=[ping], hooks=[n], callback_handler=None)
        agent("call ping")            # FakeModel is scripted to call the first tool once
        kinds = [e["kind"] for e in events.history("run:test")]
        assert "tool_start" in kinds and "tool_end" in kinds
        end = next(e for e in events.history("run:test") if e["kind"] == "tool_end")
        assert end["node"] == "executor" and end["name"] == "ping" and end["ms"] >= 0
```

  Check `src/handoff/testing/fake_model.py` for how to script one tool call; adapt the prompt or use its API.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** by moving the class out of `chat/service.py`, adding the `node` field and `BeforeInvocationEvent`/`AfterInvocationEvent` callbacks (both exist in `strands.hooks`). In `factory.py`, after building the three agents: `if run_channel: for name, a in (("trigger", trigger_agent), ("executor", executor_agent), ("completer", completer_agent)): a.hooks.add_hook(Narrator(run_channel, node=name))` — add a `run_channel: str = ""` parameter to `build_workflow_graph` and pass `run.run_id` from `WorkflowRunner._start_existing` and `resume`.
- [ ] **Step 4: Run full suite, expect PASS.**
- [ ] **Step 5: Commit** — `Narrate every graph node: tool and node timings stream on the run's event channel`

---

## Phase B — The orb

### Task B1: Voice chat, tools and routes

**Files:**
- Modify: `src/handoff/platform/models.py` (`Chat.kind: str = "chat"`)
- Create: `src/handoff/chat/voice_tools.py`
- Modify: `src/handoff/chat/service.py` (`VOICE_PROMPT`, `voice_chat(workspace_id)`, `_agent` picks tools/prompt by `chat.kind`, sets `current_channel` for the turn)
- Modify: `src/handoff/web/nav.py`, `src/handoff/web/server.py`
- Test: `tests/test_orb.py::TestVoiceTools`, `::TestOrbRoutes`

**Produces:**

```python
# voice_tools.py
current_channel: ContextVar[str]          # set by ChatService._run_turn
@tool
def activate_workflow(config_json: str) -> dict   # validates, saves status=active, emits workflow_saved {config: dict, workflow_id}
@tool
def start_run(workflow_id: str) -> dict           # starts background run, emits run_started {run_id, workflow_id}; returns {"run_id", "events": "/events/<id>"}
# service.py
VOICE_PROMPT: str
def voice_chat(self, workspace_id: str) -> Chat   # get-or-create the Chat with kind="voice"
```

Routes:

```
GET  /orb                      -> orb.html (context: chat, history blocks, speech status, workflows count)
POST /orb/{chat_id}/send       -> {"turn": n}  (JSON, message from form field `message`)
GET  /orb/{chat_id}/events?turn=n   -> same SSE as /chat/{id}/events (reuse the generator)
GET  /orb/card/{workflow_id}   -> _work_card.html rendered for that workflow (Signals / Jobs / Agents)
```

`VOICE_PROMPT` = `ASSISTANT_PROMPT` with this prepended:

```
You are speaking, not writing. Reply in at most two short sentences of plain
speech: no markdown, no lists, no code, never a fenced config. When someone
asks you to set up a chore, do the whole thing in this turn — design it,
call activate_workflow with the JSON, and if they said to run it call
start_run — then tell them in one sentence what you did and when it will run.
Ask a question only when the schedule or the destination is genuinely unclear.
```

- [ ] **Step 1: Failing tests**

```python
class TestVoiceTools:
    def test_activate_workflow_saves_and_emits(self):
        import json
        from handoff import events
        from handoff.chat.voice_tools import activate_workflow, current_channel
        from handoff.store import get_store
        cfg = {"workflow_id": "voice-test", "name": "Voice test", "trigger": {"type": "cron", "schedule": "0 8 * * 1-5"}, "mcp_tools": ["gmail"], "steps": []}
        token = current_channel.set("chat:t1")
        try:
            out = activate_workflow(json.dumps(cfg))
        finally:
            current_channel.reset(token)
        assert out["workflow_id"] == "voice-test"
        assert get_store().get_workflow("voice-test").status.value == "active"
        ev = [e for e in events.history("chat:t1") if e["kind"] == "workflow_saved"]
        assert ev and ev[0]["config"]["name"] == "Voice test"

    def test_activate_workflow_rejects_bad_json(self):
        from handoff.chat.voice_tools import activate_workflow
        assert "error" in activate_workflow("{not json")

class TestOrbRoutes:
    def test_orb_page_and_nav(self):
        from fastapi.testclient import TestClient
        from handoff.web import nav
        from handoff.web.server import app
        assert any(t.label == "Talk" and t.href == "/orb" for t in nav.TOOLS)
        c = TestClient(app)
        c.post("/welcome/skip")
        r = c.get("/orb")
        assert r.status_code == 200 and 'id="orb"' in r.text and "orb.js" in r.text
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** per the interfaces above. `_run_turn` wraps the agent call in `token = current_channel.set(channel)` / `reset`. `voice_chat` searches `svc.list(workspace_id)` for `kind == "voice"` before creating one titled "Voice". The `/orb` context includes `blocks` (last 6 turns from `svc.history`), `speech=speech.status()`, `voice_chat_id`.
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit** — `Voice chat: a spoken-style assistant that activates and starts workflows in one turn`

### Task B2: Orb rendering, speech loop and the work panel

**Files:**
- Create: `src/handoff/web/static/orb.js`, `orb.css`, `work-panel.js`
- Create: `src/handoff/web/templates/orb.html`, `_work_card.html`
- Modify: `src/handoff/web/static/handoff.js` (export `transcribeBlob` and the PCM recorder as `window.handoffMic`)
- Test: `tests/test_orb.py::TestWorkCard` (template renders Signals/Jobs/Agents for a saved workflow)

**orb.js contract:**

```js
window.HandoffOrb = { mount(canvas, {fallbackEl}) -> orb, orb.setState(name), orb.setLevel(0..1), orb.destroy() }
// states: idle | wake | listening | thinking | speaking | acting | needs
// hue per state: idle 0.62, wake 0.50, listening 0.45, thinking 0.72, speaking 0.58, acting 0.38, needs 0.10 (amber)
```

The shader is DORA's `orb_3d.py` fragment program re-typed with these changes: background pixels return `vec4(0.0)` (transparent), `uAudio` added to the noise amplitude (`N *= uNoise + uAudio * 0.6`), canvas `alpha: true, premultipliedAlpha: true`. Device-pixel-ratio aware sizing; `requestAnimationFrame` pauses when `document.hidden`.

**Speech loop (in orb.html's inline module, ~150 lines):**

1. `startListening()`: `getUserMedia({audio:{channelCount:1, echoCancellation:true, noiseSuppression:true}})` → `AudioContext` → `audioWorklet.addModule('/static/pcm-worklet.js')` → collect Int16 chunks; an `AnalyserNode` feeds `orb.setLevel`. If `getUserMedia` throws and `window.pywebview?.api?.start_listening` exists, call the bridge instead (Task E1).
2. `stopListening()`: build WAV (`handoffMic.toWav(chunks)`), POST `/api/voice/transcribe`, show transcript, POST `/orb/{chat}/send`, open `EventSource('/orb/{chat}/events?turn=n')`.
3. Event handlers: `delta` → caption; `tool_start` → `acting` + a line in the transcript; `workflow_saved` → `fetch('/orb/card/'+id)` and mount; `run_started` → `WorkPanel.watchRun(run_id)`; `asked` → mount decision cards (fetch `/activity/item/{id}` like chat.js); `done` → `speaking`, `POST /api/voice/speak`, play through an `<audio>` with an `AnalyserNode` for `setLevel`; on `ended` → `idle`, re-arm if hands-free.
4. Hands-free: RMS below 0.012 for 1100 ms after at least 600 ms of speech ends the utterance.
5. Space keydown/keyup = hold to talk; click on the orb toggles.

**work-panel.js contract:**

```js
window.WorkPanel = { mountCard(html), watchRun(runId), mountDecision(html), clear() }
```

`watchRun` opens `EventSource('/events/'+runId)`; on `node_start` marks the node RUNNING; `tool_start` adds a tool node under that node (label = tool name, badge MCP when the name contains a dot or is in the workflow's `mcp_tools`, else LLM); `tool_end` sets DONE + ms; `node_end` sets DONE; `completed`/`asked`/`failed` set the run badge. Nodes are absolutely positioned in three columns (trigger | executor + tools stacked | completer); edges are `<line>`s in an SVG overlay recomputed on resize.

**_work_card.html** takes `workflow` and `readable` (from `describe_schedule`):

- Signals: `{{ workflow.trigger.type }}` badge, cron in mono, `readable`, timezone.
- Jobs: name, description, sentence: "Runs {{ tools joined }}, stops for you on anything below {{ threshold }}% confidence, then {{ completion.notify }} {{ completion.channel }}."
- Agents: one row per `mcp_tools` entry (MCP), `executor` (LLM), `completer` + notify channel (SEND).

- [ ] **Step 1: Failing test**

```python
class TestWorkCard:
    def test_card_lists_signals_jobs_agents(self, triage_workflow):
        from fastapi.testclient import TestClient
        from handoff.web.server import app
        c = TestClient(app); c.post("/welcome/skip")
        r = c.get(f"/orb/card/{triage_workflow.workflow_id}")
        assert r.status_code == 200
        for word in ("Signals", "Jobs", "Agents", "MCP", "LLM", "SEND", triage_workflow.trigger.schedule):
            assert word in r.text
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the four static files and two templates. Keep the orb page outside the sidebar chrome? No — it uses the normal shell (`{% extends "base.html" %}`) so Talk stays one click from everything; the page body is `min-block-size: 100%` with the orb in the top third.
- [ ] **Step 4: Tests pass; then a real run** in the browser on Nova Lite: say the inbox sentence, see the card, say "run it now", see the graph fill, answer a decision by voice.
- [ ] **Step 5: Commit** — `The orb: speak, watch the workflow appear, watch the run's graph fill in, answer by voice`

---

## Phase C — The CLI (independent of B; can run in parallel)

### Task C1: Package, console helpers and read-only commands

**Files:**
- Delete: `src/handoff/cli.py`
- Create: `src/handoff/cli/__init__.py`, `_ui.py`, `workflows.py`, `runs.py`, `settings.py`, `workspace.py`, `ops.py`
- Modify: `pyproject.toml` (`rich>=13` dependency; script stays `handoff = "handoff.cli:main"`)
- Test: `tests/test_cli.py`

**Produces:**

```python
# _ui.py
console: rich.console.Console
def json_mode() -> bool                              # set by --json
def emit(data: Any, table: Callable[[], Table] | None = None) -> None  # prints JSON in json mode, else the table/panel
def table(title: str, columns: list[str], rows: list[list[str]]) -> Table
def ok(msg), warn(msg), fail(msg)                    # coloured one-liners
# __init__.py
def main(argv: list[str] | None = None) -> int
def build_parser() -> argparse.ArgumentParser        # every module exposes register(subparsers) and handle(args) -> int
```

Global flags: `--json`, `--workspace <id>`, `--state-dir <path>` (sets `HANDOFF_STATE_DIR` before config import).

Commands in this task (all read-only, all `--json`-able):
`workflows list|show <id>`, `runs [--limit N]`, `inspect <run_id>` (session steps table: index, node, kind, name, status, ms), `pending`, `activity [--limit]` (audit log), `settings show`, `usage [--days N]`, `workspace list`, `doctor [checks…]`, `serve`, `desktop`, `version`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_cli.py
import json
from handoff.cli import main

def run(capsys, *argv):
    code = main(list(argv)); out = capsys.readouterr().out; return code, out

def test_workflows_list_json(capsys, triage_workflow):
    code, out = run(capsys, "--json", "workflows", "list")
    assert code == 0
    rows = json.loads(out)
    assert any(r["workflow_id"] == triage_workflow.workflow_id for r in rows)

def test_workflows_show_human(capsys, triage_workflow):
    code, out = run(capsys, "workflows", "show", triage_workflow.workflow_id)
    assert code == 0 and triage_workflow.name in out and triage_workflow.trigger.schedule in out

def test_unknown_workflow_is_exit_2(capsys):
    code, out = run(capsys, "workflows", "show", "nope")
    assert code == 2

def test_settings_show_never_prints_secrets(capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_supersecretvalue1234567890")
    code, out = run(capsys, "settings", "show")
    assert "gsk_supersecret" not in out

def test_version(capsys):
    code, out = run(capsys, "version")
    assert code == 0 and "handoff" in out.lower()
```

- [ ] **Step 2: Run, expect FAIL** (import error once `cli.py` is replaced by the package).
- [ ] **Step 3: Implement.** Keep every existing behaviour of the old `cli.py` (`run`, `pending`, `decide`, `serve`, `desktop`, `workflows`, `rules`, `workspace export|import|list`, `doctor`). Exit codes: 0 ok, 1 failure, 2 not found / bad argument.
- [ ] **Step 4: Tests pass.** Also `handoff --help` renders and lists every group.
- [ ] **Step 5: Commit** — `CLI as a package: rich tables, --json everywhere, workflows, runs, inspect, activity, usage, settings`

### Task C2: Chat, ask, build, run --watch, decide

**Files:**
- Create: `src/handoff/cli/chat.py`
- Modify: `src/handoff/cli/runs.py`
- Test: `tests/test_cli.py::test_ask_streams_on_fake_model`, `::test_run_watch_prints_events`

**Behaviour:**
- `ask "<text>"` — one turn on the workspace's latest chat via `ChatService.send`, subscribes to `events.subscribe(f"chat:{id}")`, prints `delta` text as it arrives, a dim `→ tool_name (ms)` line per `tool_end`, and the config as a syntax-highlighted panel if `done.config` is set. `--json` prints the final `done` event.
- `chat` — the same in a loop (`rich.prompt.Prompt.ask("you")`), `/quit` to exit, `/new` for a new chat; the session persists in the store, so the browser shows the same conversation.
- `build "<sentence>" [--activate] [--run]` — sends the sentence with the suffix "Show the config." then, if `done.config` and `--activate`, saves via `handoff.chat.voice_tools.activate_workflow` (from Task B1; if B1 is not merged yet, save through `tools.workflow_store.save_workflow` with `status="active"`), and with `--run` starts it through `server._run_in_background`-equivalent: `WorkflowRunner(workflow).start("manual")` on a thread while `--watch` output streams.
- `run <id> [--watch]` — `--watch` prints every event kind on the run channel as `HH:MM:SS kind text` until `completed|failed|asked`, then prints the outcome; without `--watch` prints the outcome JSON as today.
- `decide <interrupt_id> <action> [--note]` — unchanged; `decide --all <action>` answers every pending item.

- [ ] **Step 1: Failing tests**

```python
def test_ask_streams_on_fake_model(capsys):
    code, out = run(capsys, "ask", "what is waiting on me")
    assert code == 0 and out.strip()

def test_run_watch_prints_events(capsys, triage_workflow):
    code, out = run(capsys, "run", triage_workflow.workflow_id, "--watch")
    assert code == 0 and "started" in out and ("completed" in out or "asked" in out)
```

- [ ] **Step 2–5:** as before. Commit — `CLI: chat and ask stream the assistant, build turns a sentence into an active workflow, run --watch follows the run live`

### Task C3: Agents, MCP, skills, memory, credentials, schedules, speech, ops

**Files:**
- Create: `src/handoff/cli/agents.py`, `mcp.py`, `skills.py`, `memory.py`, `creds.py`, `schedules.py`, `speech.py`
- Modify: `src/handoff/cli/ops.py` (`share`, `docs`, `deploy`, `completion`), `settings.py` (`model`, `threshold`)
- Test: `tests/test_cli.py` additions

**Commands (service functions to call are in parentheses):**
- `agents list` (`store.custom_agents.all()`), `agents show <id>`, `agents run <id> "<prompt>"` (`platform.workbench.run` + follow `workbench.channel(run_id)` events).
- `mcp list` (`platform.mcp_service.registry_catalogue` + `store.mcp_servers.all()`), `mcp tools <server>` (`mcp_service.describe_tools`), `mcp call <server> <tool> [--args '{json}']` (`mcp_service.invoke`), `mcp probe <server>`, `mcp add <name> --command … --args …`, `mcp remove <id>`.
- `skills list|show <id>|enable|disable|import <files…>` (`platform.skills`).
- `memory rules` (`memory.store.list_preferences`), `memory entries [--workspace]`, `memory add "<text>"`, `memory forget <id>`.
- `credentials list` (`platform.credentials.catalogue`, masked only), `credentials set <provider>` (reads the secret with `getpass`, or `--from-env VAR`; never echoes; calls `credentials.connect` then `verify`), `credentials check [provider]`, `credentials forget <provider>`, `credentials gmail` (runs `run_gmail_auth`).
- `schedules list|toggle <id>|run <id>` (`daemon.get_scheduler()`, store schedules), `scheduler` (foreground: `get_scheduler().start()` then sleep loop until Ctrl-C).
- `settings model <provider> <primary> [fallback]` (`platform.settings.save`), `settings threshold <0..1>` (`settings.write_env({"CONFIDENCE_THRESHOLD": …})`).
- `say "<text>" [--out file.mp3]` (`speech.speak`; plays with `ffplay`/`aplay`/`afplay` if found, else writes the file), `listen <file.wav>` (`speech.transcribe`), `talk [--mic]` (loop: record push-to-talk via `sounddevice` at 16 kHz Int16 until Enter, transcribe, send through `ChatService`, speak the reply; without `--mic` or without `sounddevice`, typed input, spoken reply).
- `share [--port]` — if `shutil.which("cloudflared")`: start `cloudflared tunnel --url http://127.0.0.1:<port>` and print the `https://*.trycloudflare.com` URL parsed from its stderr; else print `Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/` and exit 1.
- `docs [--open]` — prints the docs index (`handoff.docs.index()`), `--open` opens `http://127.0.0.1:<port>/docs`.
- `deploy site` (runs `python site/build.py` then `wrangler pages deploy site/dist --project-name handoff`), `deploy agentcore` (runs `infra/agentcore_runtime.py`).
- `completion bash|zsh|fish` — prints a static completion script listing every subcommand from the parser.

- [ ] **Step 1: Failing tests** — one per group, on the isolated store: `agents list --json` returns the seeded builtin agents; `mcp list --json` includes `gmail`; `skills list --json` non-empty; `memory rules --json` returns `[]`; `credentials list` output contains no `secret` key and masks values; `schedules list --json` is a list; `completion bash` contains `workflows`.
- [ ] **Step 2–5:** as before. Commit — `CLI: agents, tool servers, skills, memory, credentials, schedules, say/listen/talk, share, docs, deploy, completion`

---

## Phase D — Site and docs (independent of B and C)

### Task D1: Markdown docs and the renderer

**Files:**
- Create: `docs/site/getting-started.md`, `talk.md`, `workflows.md`, `the-gate.md`, `integrations.md`, `cli.md`, `deploy.md`, `architecture.md`
- Create: `src/handoff/docs.py`
- Test: `tests/test_docs.py`

**Produces:**

```python
# handoff/docs.py
DOCS_DIR: Path                                   # <repo>/docs/site, resolved from the package with a fallback to cwd
def index() -> list[dict]                        # [{"slug", "title", "summary"}] in the order of ORDER
def render(slug: str) -> dict                    # {"slug","title","html","outline":[{"id","text","depth"}], "raw"}
ORDER = ["getting-started","talk","workflows","the-gate","integrations","cli","deploy","architecture"]
```

Each markdown file starts with a `# Title` line and a one-paragraph summary. `render` uses `markdown.markdown(text, extensions=["fenced_code","tables","toc","attr_list"])` with `toc` producing GitHub-style ids; `outline` is built from `md.toc_tokens` (h2 and h3 only). `cli.md` is generated: `render("cli")` calls `handoff.cli.build_parser()` and appends a reference section listing every subcommand with its help string, so the doc never drifts.

Content requirements per file (write real prose, not stubs — 60–150 lines each): getting-started (install with pip, `.env`, `handoff doctor`, first run offline, desktop); talk (the orb, tap / hold Space / hands-free, what appears, AWS speech setup, Groq and browser fallbacks, cost); workflows (the config schema with every field explained, templates, workspace.yml export/import); the-gate (confidence threshold, deferred batch interrupt, rules learned, how to tune); integrations (Gmail OAuth flow, Linear key, Slack bot token vs webhook, GitHub fine-grained token, `handoff doctor`); cli (intro + generated reference); deploy (AgentCore runtime via boto3 scripts, EventBridge → Lambda bridge, DynamoDB single table, AgentCore Memory, region prefixes, budget notes); architecture (the Graph, the three agents, hooks, the events bus, storage).

- [ ] **Step 1: Failing test**

```python
def test_index_and_render():
    from handoff import docs
    slugs = [d["slug"] for d in docs.index()]
    assert slugs == docs.ORDER
    page = docs.render("the-gate")
    assert page["title"] and "<h2" in page["html"] and page["outline"]

def test_cli_doc_includes_every_subcommand():
    from handoff import docs
    html = docs.render("cli")["html"]
    for name in ("workflows", "run", "decide", "credentials", "talk"):
        assert f"<code>handoff {name}" in html or f"handoff {name}" in html
```

- [ ] **Step 2–5.** Commit — `Docs: eight user guides in docs/site and a renderer with outline and a generated CLI reference`

### Task D2: Landing page and site build

**Files:**
- Create: `site/build.py`, `site/index.html`, `site/templates/doc.html`, `site/assets/site.css`, `site/assets/site.js`
- Modify: `Makefile` (`site`, `site-deploy`), `.gitignore` already has `site/dist/`
- Test: `tests/test_site_build.py`

**build.py contract:** `python site/build.py [--out site/dist]` → copies `site/index.html` and `site/assets/*`, copies `src/handoff/web/static/orb.js` to `dist/assets/orb.js` (if B2 is not merged yet, copy `site/assets/orb-fallback.js` — a CSS-only orb — and note it), renders every doc through `handoff.docs.render` into `site/templates/doc.html` (placeholders `{{title}}`, `{{content}}`, `{{outline}}`, `{{nav}}` replaced with `str.replace`, no Jinja), copies `docs/screens/*.png` into `dist/screens/`, writes `dist/_headers` with `Cache-Control` for assets and `dist/_redirects` with `/docs /docs/getting-started 302`. Prints the file count. Exit 1 if any doc fails to render.

**index.html sections** (kelbro's structure, Handoff's copy; all CSS in `site.css` against the same oklch tokens as `tokens.css`; fonts from Google Fonts):
1. Sticky glass nav: accent square + `handoff` in Comfortaa; tabs Product / Docs / GitHub; the "Install" nav-pill with the letter-roll hover (`CLI` → `Install`); theme toggle with the view-transition wipe.
2. Hero: drift wall behind (8 lanes of small tiles named after real templates: Inbox Zero, PR Review Triage, Competitor Pricing Watch, Meeting Follow-up, Slack Digest, plus integration names), the orb canvas centred above the headline, headline `Describe it. Hand it off. It runs.` with the second line rotating `Hand off … Gmail. / Linear. / Slack. / GitHub.`; subline; CTAs `Install` (accent) and `Watch the demo` (glass, links to the video URL placeholder in a `data-video` attribute); pills `Open source · Apache-2.0`, `Strands Agents SDK`, `Runs on AWS Bedrock`, `★ GitHub`.
3. "Set up in one command" panel with tabs pip / desktop / Docker / AgentCore, numbered rows with copyable commands.
4. Sticky accordion "Handoff for": inbox triage, PR review, competitor watch, meeting follow-up, engineering ops, anything on a schedule — each with a screenshot from `screens/`.
5. "A decision. Not a notification." + screen strip of `screens/*.png` in an arc.
6. "Works with" keycap tiles: Gmail, Linear, Slack, GitHub, Amazon Bedrock, AgentCore, Strands, MCP (inline SVG marks, no external images).
7. Final CTA.
8. Champagne footer with links and the clipped giant wordmark.

Everything is responsive to 400 px and honours `prefers-reduced-motion`.

- [ ] **Step 1: Failing test**

```python
def test_build_produces_index_docs_and_assets(tmp_path):
    import subprocess, sys
    r = subprocess.run([sys.executable, "site/build.py", "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "docs" / "getting-started.html").exists()
    assert (tmp_path / "assets" / "site.css").exists() and (tmp_path / "assets" / "orb.js").exists()
    assert "Describe it. Hand it off. It runs." in (tmp_path / "index.html").read_text()
```

- [ ] **Step 2–5.** Commit — `Site: framework-free landing page in the kelbro design with the live orb, and a build that renders the docs`

### Task D3: Docs inside the app

**Files:**
- Create: `src/handoff/web/templates/docs.html`
- Modify: `src/handoff/web/server.py` (`GET /docs`, `GET /docs/{slug}`), `base.html` (footer link → `/docs`)
- Test: `tests/test_docs.py::test_docs_routes`

- [ ] Test: `GET /docs` redirects to `/docs/getting-started`; `GET /docs/the-gate` is 200 and contains the outline `<nav class="doc-outline">`; `GET /docs/nope` is 404.
- [ ] Implement with the same three-column layout as the site (left nav from `docs.index()`, content, right outline). Commit — `Docs page inside the app, same sources as the site`

### Task D4: Deploy to Cloudflare Pages

- [ ] `make site` then `wrangler pages project create handoff --production-branch main` (once) and `wrangler pages deploy site/dist --project-name handoff --commit-dirty=true`.
- [ ] Open the returned `https://handoff-*.pages.dev` URL; check the landing page, `/docs`, the orb animates, both themes.
- [ ] Put the URL in `README.md` and `docs/SUBMISSION.md`. Commit — `Publish the site on Cloudflare Pages`

---

## Phase E — Desktop

### Task E1: Orb by default, native microphone bridge, hotkey

**Files:**
- Modify: `src/handoff/desktop.py`
- Modify: `src/handoff/web/static/orb.js` (bridge path already stubbed in B2)
- Test: `tests/test_desktop.py` (bridge unit test with a fake recorder)

**Produces:**

```python
class DesktopBridge:
    def start_listening(self) -> dict          # {"ok": True} or {"ok": False, "error": str}
    def stop_listening(self) -> dict           # {"ok": True, "wav_b64": str, "seconds": float}
    def status(self) -> dict                   # {"mic": bool, "backend": str}
```

- Records with `sounddevice.InputStream(samplerate=16000, channels=1, dtype="int16")` into a list of frames; `stop_listening` concatenates, wraps with `speech.wav.pcm_to_wav`, base64-encodes.
- `webview.create_window(..., js_api=DesktopBridge())`; default page `/orb` when the saved page is `/` or empty and onboarding is complete.
- Hotkey: `window.evaluate_js` is not needed — `app.js` binds `Ctrl+Space` to navigate to `/orb?listen=1` on any page, and the orb page starts listening when `listen=1` is in the query.

- [ ] Test the bridge with `sounddevice` monkeypatched to a fake stream yielding zeros: `stop_listening()["wav_b64"]` decodes to a valid WAV of the expected length.
- [ ] Implement; then run `handoff desktop`, confirm it opens on the orb and that a spoken sentence is transcribed (either via `getUserMedia` or the bridge).
- [ ] Commit — `Desktop: opens on the orb, records from the microphone natively, Ctrl+Space to talk from any page`

---

## Phase F — Documentation, demo, verification

### Task F1: README, submission, demo storyboard, screenshots

- [ ] `README.md`: new "Talk to it" section at the top (orb screenshot), the site URL, CLI section with the command tree, speech setup, updated screenshot table including `docs/screens/orb.png`, `docs/screens/talk-run.png`, `docs/screens/landing.png` (capture with the running app at 1440×900; the secret guard permits PNGs only under `docs/screens/`, so add `!docs/screens/*.png` to `.gitignore` if needed — check the current rule `/*.png` only blocks root-level PNGs).
- [ ] `docs/SUBMISSION.md`: replace the "needs a Bedrock-enabled account" sentence with the deployed state; add voice on AWS (Transcribe + Polly), the CLI and the site to "How we built it"; keep the two placeholders for video URL and Builder ID.
- [ ] `docs/DEMO.md`: rewrite the 0:25–1:00 and 2:00–3:15 beats around the orb: say the sentence, the card appears, say run, the graph fills, the decision is asked aloud, answer aloud.
- [ ] Commit — `Docs: talk to it, the CLI, the site, refreshed screenshots and submission copy`

### Task F2: Final verification

- [ ] `make test` and `make lint` clean; count of tests recorded in the final report.
- [ ] `handoff doctor` full run; `handoff doctor speech` green.
- [ ] One end-to-end voice run on Nova Lite as described in the spec's verification section; note the spend from `/usage`.
- [ ] `git status` clean, `git log --oneline` shows one commit per feature, `git push`.
