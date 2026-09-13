# Handoff v3 — voice orb, real CLI, themed UI, public site

*Design spec, 2026-09-13. Decisions here were made without a live review;
every one of them is overridable. The order of sections is the order of
implementation.*

## What is being built

Four things, in one sentence each:

1. **A voice orb.** A page where you speak to Handoff, it speaks back, and the
   work it does — the workflow it builds, the run it starts, the tools it
   calls, the decision it needs — appears on the same page as it happens.
2. **A real CLI.** Every feature of the product usable from a terminal, with
   `--json` for scripts.
3. **The kelbro theme.** Its fonts, palette and surfaces applied across every
   page of the app, and a landing site in the same design.
4. **A public site on Cloudflare Pages.** Landing page plus docs, deployed
   with wrangler. The app itself stays where a Python runtime is: your
   machine, the desktop window, or AgentCore.

Plus: the desktop app opens on the orb and can record from the microphone
natively, and a docs section exists both on the site and inside the app.

## What is explicitly not being built

- No wake-word model in the browser. DORA's ONNX wake word needs a native
  audio loop; the orb uses tap-to-talk, hold-Space, or a hands-free mode
  driven by silence detection.
- No hosting of the FastAPI app on Cloudflare. Workers cannot run Strands.
- No copy of kelbro or DORA source into the repo. The shader is re-typed and
  adapted; the CSS is re-expressed against Handoff's own tokens. Both clones
  are gitignored.

## 1. Theme

**Source:** kelbro's `globals.css`. MIT.

**Fonts.** Instrument Sans for everything, Comfortaa for the wordmark only,
JetBrains Mono for code and ids. Loaded from Google Fonts in `base.html` and
on the site; the existing system stacks remain as fallbacks.

**Palette.** kelbro's oklch cream, mapped onto Handoff's existing semantic
tokens so no template needs to change:

| Handoff token | Light | Dark |
|---|---|---|
| `--surface-dark` (page ground) | `oklch(0.965 0.008 85)` | `oklch(0.16 0.006 85)` |
| `--surface` (content sheet, cards) | `oklch(0.98 0.005 85)` | `oklch(0.20 0.005 85)` |
| `--surface-2`, `--highlight` | `oklch(0.92 0.006 85)` | `oklch(0.22 0.006 85)` |
| `--text-bright` | `oklch(0.19 0 0)` | `oklch(0.93 0.005 85)` |
| `--text` | 78 % of bright | 78 % of bright |
| `--text-faded` | 55 % of bright | 50 % of bright |
| `--border` | `oklch(0.19 0 0 / 0.1)` | `oklch(0.93 0 0 / 0.12)` |
| `--accent` / `--accent-ink` (new) | ink / white | champagne `oklch(0.9 0.035 70)` / `oklch(0.25 0.01 40)` |
| `--wash` (new, for glass) | `oklch(0.19 0 0)` | `oklch(0.99 0 0)` |

Amber stays reserved for "waiting on you". Green = agent, blue = human.

**Surfaces.** `.button.accent` becomes kelbro's solid accent button (inset
specular top line, inset bottom shadow, scale 0.975 on hover). `.button.secondary`
becomes the frosted glass pill. `.card` gets the raised panel treatment
(22 px radius on page-level cards, layered shadow). The active sidebar item
gets the nav-pill look. The theme toggle wipes the new theme out from the
button as a circle via the View Transitions API; browsers without it switch
instantly.

**Brand.** Sidebar shows an accent square with a rotated inner square and
"handoff" in Comfortaa, exactly as kelbro renders "agent.md".

## 2. Speech on AWS

New package `src/handoff/speech/`:

- `__init__.py` — the facade. `transcribe(wav_bytes) -> {"text": ...}` and
  `speak(text) -> (bytes, mime) | (None, reason)`, `status()`, and provider
  selection. `HANDOFF_SPEECH_PROVIDER=auto|aws|groq|browser`; `auto` picks AWS
  when boto3 can resolve credentials, else Groq when a key exists, else browser.
- `aws.py` — Amazon Transcribe **streaming** (`amazon-transcribe` SDK, 16 kHz
  PCM, one session per utterance, ~1 s latency, no S3) and Amazon Polly
  (`POLLY_VOICE`, default Matthew; `POLLY_ENGINE`, default neural; MP3 out).
  An LRU cache keyed on text keeps repeated short phrases free.
- `groq.py` — what `tools/voice.py` does today, moved. `tools/voice.py` keeps
  `parse_command` and `decision_prompt` and re-exports the facade so nothing
  that imports it breaks.

**The browser records PCM, not webm.** `static/pcm-worklet.js` is an
AudioWorklet that downsamples the mic to 16 kHz mono Int16; the page wraps it
in a WAV header. This removes the ffmpeg dependency and gives Transcribe what
it wants directly. Groq's Whisper accepts the same WAV.

**Doctor.** `check_speech()` synthesises one word with Polly and opens one
Transcribe stream with 0.5 s of silence. Both are real calls, both cost
under a hundredth of a cent.

**Cost.** Transcribe streaming is $0.024 per minute; Polly neural is $16 per
million characters. A full demo rehearsal is cents.

## 3. The orb page

**Route** `/orb`, first item in the sidebar as "Talk". Also the desktop
window's default page once onboarding is done.

**Layout** (the video, translated): a quiet header (wordmark · workspace
name), the orb centred in the top third, a one-line caption under it
("Tap to talk" / "Listening…" / "Thinking…" / the transcript as it lands),
a compact transcript of the last few turns, and below that the **work panel**
where three kinds of card mount as events arrive:

1. **Workspace card** — when a turn saves a workflow. Three panels:
   *Signals* (the trigger: cron, its readable form, timezone),
   *Jobs* (the workflow: which tools run, that unsure items stop for you,
   where completion notifies), *Agents* (one row per MCP tool marked MCP,
   the executor marked LLM, the notifier marked SEND). Header: name ·
   "generated from voice · just now".
2. **Run graph** — when a run starts. The Strands Graph drawn as it is:
   `trigger → executor → completer`, with a tool node under the executor for
   every tool call, each showing QUEUED / RUNNING / DONE and milliseconds,
   SVG edges between them. This is a direct visualisation of the SDK's graph
   plus its hook events, not a mock-up.
3. **Decision card** — when the run asks. The existing activity item,
   answerable by voice through the existing `parse_command` path.

**Orb rendering.** `static/orb.js`: a WebGL2 port of DORA's volumetric
shader (MIT) with alpha over the page instead of a chroma-key background,
and a CSS radial-gradient fallback. States: `idle`, `wake`, `listening`,
`thinking`, `speaking`, `acting` (a tool is running), `needs` (a decision is
waiting — amber). Two audio uniforms: mic level while listening, output
level while speaking, both from `AnalyserNode`s.

**Interaction.** Tap the orb to start and stop; hold Space to talk; a
"Hands-free" toggle arms silence detection (1.1 s below threshold ends the
utterance) and re-arms after Handoff finishes speaking, so a conversation
flows without touching anything.

**Agent.** One persisted chat per workspace titled "Voice" (a `Chat` with
`kind="voice"`), driven by the existing `ChatService` so history, tools and
the Narrator hook are shared. Differences from the typed chat:

- A spoken-style system prompt: at most two sentences, no markdown, no fenced
  config. When asked to set something up: build it, save it, switch it on,
  and say so in one sentence; ask only when the schedule or destination is
  genuinely ambiguous.
- Two extra tools: `activate_workflow(config_json)` (validate → save →
  active, emits `workflow_saved` with the config so the page can draw the
  workspace card) and `start_run(workflow_id)` (emits `run_started` with the
  run id so the page can subscribe to the run's events). Both emit on the
  chat's channel through a context variable set for the turn.

**Run events.** A new `RunNarrator` hook (the chat `Narrator`, generalised)
is bound to all three graph nodes in `build_workflow_graph`, emitting
`node_start`/`node_end` and `tool_start`/`tool_end` with timings on the run
channel. The existing `/events/{run_id}` SSE carries them unchanged; the
existing live feed ignores kinds it does not know.

**Speech loop.** Record → `/api/voice/transcribe` → `POST /orb/{chat}/send`
→ SSE `delta`/`tool_*`/`workflow_saved`/`run_started`/`asked`/`done` →
`/api/voice/speak` on `done` → play → (hands-free) re-arm.

## 4. The CLI

`src/handoff/cli.py` becomes the package `src/handoff/cli/`:

```
cli/__init__.py   main(), the parser, --json and --workspace globals
cli/_ui.py        rich console helpers: table(), panel(), spinner(), json_out()
cli/chat.py       chat (REPL), ask (one shot), build (sentence → workflow)
cli/runs.py       run [--watch], runs, inspect, activity, pending, decide
cli/workflows.py  workflows list|show|enable|disable|delete|export
cli/schedules.py  schedules list|toggle|run, scheduler (foreground daemon)
cli/agents.py     agents list|show|run
cli/mcp.py        mcp list|tools|call|probe|add|remove
cli/skills.py     skills list|show|enable|disable|import
cli/memory.py     memory rules|entries|add|forget
cli/creds.py      credentials list|set|check|forget   (secret read hidden)
cli/settings.py   settings show|model|threshold, usage
cli/speech.py     say, listen, talk [--mic]
cli/ops.py        serve, desktop, share, docs, deploy site|agentcore, doctor, completion
cli/workspace.py  workspace list|export|import|remove|switch
```

`rich` becomes a dependency. `chat` streams tokens and paints a line per
tool call, on the same `Agent` and session repository as the web chat, so a
conversation started in the terminal continues in the browser. `talk --mic`
records push-to-talk through `sounddevice` when it is installed and speaks
replies through Polly; without a microphone library it says so and falls
back to typed input with spoken replies. `share` starts a Cloudflare quick
tunnel through `cloudflared` when present and prints the public URL;
otherwise it prints the one-line install and stops.

## 5. The site

`site/` is framework-free: `index.html`, `docs/<slug>.html`, one stylesheet,
one script, plus `orb.js` copied from the app at build time. `site/build.py`
renders `docs/site/*.md` (a new, user-facing doc set) through the
`markdown` package into the doc layout, copies screenshots from
`docs/screens/`, and writes `site/dist/`. `make site` builds; `make
site-deploy` runs `wrangler pages deploy site/dist --project-name handoff`.

Landing sections, in kelbro's structure with Handoff's content: sticky nav
(wordmark, Product / Docs / GitHub, "Install" nav pill), hero over a
drifting wall of workflow tiles with the live orb and the rotating line
"Hand off … Gmail. / Linear. / Slack. / GitHub.", a "Set up in one command"
card with pip / desktop / Docker / AgentCore tabs, the scroll-driven
"Handoff for…" accordion (inbox triage, PR review, competitor watch, meeting
follow-up, engineering ops) with screenshots, a screen strip of real
screenshots under "A decision. Not a notification.", keycap tiles for the
integrations, a final call to action, and the champagne footer with the
clipped wordmark.

Docs pages: left navigation, content column, right outline of h2/h3 that
tracks scroll, copy buttons on code blocks. Sources: getting started,
the orb and voice, workflows, the decision gate, integrations (Gmail, Linear,
Slack, GitHub), the CLI reference (generated from the parser), deploying to
AgentCore, architecture.

## 6. In-app docs

`/docs` and `/docs/{slug}` render the same markdown inside the app shell
with the same doc layout. The sidebar footer's "Docs" link points here.

## 7. Desktop

- Opens on `/orb` after onboarding; remembers the page as before.
- Native microphone: `desktop.py` exposes a `js_api` with
  `start_listening()` / `stop_listening()` that records through
  `sounddevice` and returns WAV bytes base64; `orb.js` tries `getUserMedia`
  first and uses the bridge when the webview refuses. Replies play through
  the page's `<audio>` as usual.
- Ctrl+Space inside the window toggles listening from any page.

## 8. Hygiene

- `.gitignore`: `kelbro/`, `DORA/`, `*.mp4`, `site/dist/`.
- Tests for: provider selection and WAV framing in `speech`, the two orb
  tools and their events, `RunNarrator` event shape, the CLI parser and
  `--json` output for the read-only commands, `site/build.py` output, the
  `/docs` route, and `nav` containing "Talk".
- One-line commit per feature; the secret guard runs before each.

## Verification

- `make test` green, `make lint` clean.
- `handoff doctor speech` shows Polly and Transcribe green in ap-northeast-2.
- On the orb page, on a real model: say "every weekday at eight, triage my
  inbox and ask me about anything unsure" → workspace card appears → say
  "run it now" → run graph fills in → a decision card appears → say
  "archive it" → run completes; total spend under a cent on Nova Lite.
- `wrangler pages deploy` returns a `*.pages.dev` URL that serves the landing
  page and docs.
- `handoff desktop` opens on the orb and can record from the microphone.
