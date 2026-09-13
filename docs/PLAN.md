# Handoff v2 — plan

**Goal.** Handoff should feel like a product someone would pay for: the surface
and workflow of Friday Studio's playground, implemented in Python on the Strands
Agents SDK, with the human-decision gate as the thing that sets it apart. This
document is the contract for that work. Each phase lands as one commit.

**What we take from Friday Studio, and what we don't.** We take the *shape*:
the information architecture, the interaction patterns, the layout system, the
tokenised design language (light/dark surfaces, 13px system type, rounded
content canvas inside a dark shell). We write every line ourselves. We do not
copy its source (BUSL-1.1), its name, its logo, or its brand assets; the
`friday-studio/` checkout is a reference only and is gitignored.

---

## 1. Vocabulary

| Friday Studio | Handoff | Notes |
|---|---|---|
| Space / workspace (`workspace.yml`) | **Workspace** (`workspace.yml`) | colour, sub-nav, export/import/bundle |
| Job | **Workflow** | a Strands `Graph`: trigger → executor → completer |
| Signal (http/cron/slack/email/file) | **Trigger** | cron, webhook, manual, event |
| Session / run | **Run** | recorded step-by-step by `SessionRecorder` |
| Elicitation (`request_human_input`) | **Decision** | our interrupt payload; batch = one screen |
| Agent (bundled / workspace / user) | **Agent** (built-in / custom) | every one is a Strands `Agent` |
| Agent Tester | **Agent workbench** | prompt → stream → result / trace |
| Job Inspector | **Run inspector** | waterfall of steps + graph DAG |
| MCP Catalog | **Tool servers** | list-detail, live tool invoker |
| Skills (`SKILL.md` tree) | **Skills** | markdown + frontmatter, folded into prompts |
| Memory (narrative + entries) | **Memory** | learned rules + memory stores |
| Credentials (OAuth / API key) | **Credentials** | API keys with real-call verification |
| Communicators | **Notifiers** | Slack / console |
| Daemon (`atlasd`) | **Scheduler** (in-process) + AgentCore Runtime | cloud path is EventBridge → AgentCore |

## 2. Design system

One stylesheet family, no build step:

- `tokens.css` — spacing scale (`--size-*`), radii, type scale (11–21px, 13px
  base), weights, z-layers, shadows; **colours via `light-dark()`** with a
  primitive palette (grey / slate / cream / accents) and semantic tokens
  (`--surface-dark`, `--surface`, `--highlight`, `--border`, `--text-bright`,
  `--text`, `--text-faded`, `--{yellow,red,blue,green,purple}-primary`).
- `reset.css` — a Tailwind-style preflight.
- `ui.css` — blocks: `.button` (primary/secondary/destructive/none · regular/
  small/icon), `.badge`, `.status-badge`, `.card`, `.section-head`, `.pill`,
  `.field`, `.table`, `.list-detail`, `.dialog`, `.dropdown`, `.tabs`,
  `.tree`, `.step-block`, `.toast`, `.palette`.
- Icons: a single inline SVG sprite (`icons.svg`), 20px stroke-less filled
  glyphs, `currentColor`, used with `<svg><use href="#i-clock"/></svg>`.
- Brand: our own mark — a rounded bar handing a dot across a gap — and the
  name *Handoff*. Amber is reserved for “waiting on you”; nothing else is amber.

Shell: 224px sidebar (`--surface-dark`) · content canvas `--surface` with
`--radius-7` corners in a 6px gutter · sticky, blurred page title with an
optional truncating subtitle · footer with **Docs** pill and an **Online** dot.
`⌘K` opens the command palette (chat to a workspace / switch workspace);
`/` focuses chat when not in a text field.

## 3. Pages

Global (top of sidebar): **Chat · Memory · Activity · Agents · Inspector ·
Schedules · Tool servers · Skills · Usage · Settings**, then **Discover**, then
the collapsible **Workspaces** list with a `+` (Create / Upload) dialog.

Per workspace (`/platform/{ws}`): **Overview · Activity · Chat · Agents ·
Skills · Workflows · Runs · Memory · Settings**, plus `/edit` (YAML).

| Page | What it does |
|---|---|
| **Overview** | grid: latest run card + up to 3 older runs · Workflows card (run button, overflow menu) with integration status below a divider · Triggers card · Agents card · an ask box with `@` mentions; title dropdown → Edit YAML, Export, Download bundle, Remove |
| **Activity** | pending + recent decisions; filters by status/workflow; each pending row answers inline with per-item action chips and a comment (the batch interrupt as one card); live badge count in the sidebar |
| **Chat** | persisted chats per workspace (list panel); streaming replies over SSE; tool-call cards; **decision card inline** when a run stops; artifact cards; model pill; mic (Whisper) and read-aloud (Orpheus) |
| **Agents** | catalogue of built-in + custom agents → workbench: prompt, run history (cards with duration / tokens / steps; Result · Stream · Trace tabs), credential preflight, resolved system prompt with skills folded in, IO schema |
| **Workflows** | list + detail (triggers, tools, threshold, learned rules, recent runs, Run now with input form for webhook payload) |
| **Runs** | list; detail = timeline of agent blocks (trigger / executor / completer) with task, input, tool calls (args → result), output, error; sidebar with ids, timing, counters; “Open in Inspector” |
| **Inspector** | workspace / workflow / run picker in the toolbar; no run → graph DAG + recent runs + Run; run → waterfall timeline (mono, ticks, selected row) + block panel below |
| **Schedules** | timers table (workspace, workflow, cron, tz, next, last, paused) + missed firings since last tick; pause / resume / run now |
| **Tool servers** | list-detail: catalogue tree → server sections Overview · Tools · Connections · Usage; probe; **invoke a tool live**; import from registry |
| **Skills** | tree by namespace → file editor with frontmatter validation; import a folder / zip; version compare |
| **Memory** | workspaces tab → per-workspace stores → entry table (learned rules with strength, times applied, forget) |
| **Usage** | per-model and per-run tables, workspace / model filters, cost with “pricing unavailable” where unknown |
| **Settings** | model chain per role (primary → fallbacks; provider marks), credentials, env vars, threshold, voice, updates |
| **Discover** | two-pane: searchable list of templates → README + manifest + **Add to a workspace** |
| **Welcome** | first-run wizard: name, email, timezone (auto-detected — it is what cron means), locale; skippable |
| **Decision** (`/decide/{id}`) | full-screen: the item, why it stopped, the gauge against the threshold, four actions, voice |

## 4. Runtime

- **Chats** are Strands `Agent`s with a store-backed session manager, so a
  conversation survives a restart and lives in DynamoDB when deployed.
- **Runs** are `Graph` executions; `SessionRecorder` hooks every node; the
  HITL gate (`graph/hooks/hitl.py`) is unchanged.
- **Decisions** raised inside a chat surface as a card *in the chat* and in
  Activity at the same time; answering either resumes the same run.
- **Scheduler** stays in-process for the desktop; **EventBridge → AgentCore
  Runtime** for the cloud, with the same `tick` payload.
- **Desktop**: `handoff desktop` — pywebview window with our icon, remembered
  size/position, opens on the last page, one instance.

## 5. Phases (one commit each)

0. AWS: create the AgentCore Runtime with boto3 (the Python `agentcore` CLI is
   deprecated), execution role, smoke invoke, EventBridge schedules wired.
1. Design system + shell: tokens, reset, ui blocks, icon sprite, sidebar with
   workspaces, page layout, palette, toasts; every existing page migrated.
2. Workspaces: colour, per-workspace routes and sub-nav, Overview grid, YAML
   edit, export / bundle / import / remove, create dialog.
3. Activity: global + per-workspace, filters, inline batch answering, live
   badge; `/decide` restyled.
4. Runs + Inspector: list, timeline detail, waterfall, DAG.
5. Chat v2: persisted chats, streaming, tool cards, inline decision card,
   artifacts, model pill, voice.
6. Agents: catalogue, workbench, editor, preflight.
7. Tool servers, Skills, Memory, Usage, Settings, Discover — list-detail
   rebuilds with the missing capabilities (invoke tool, import, version
   compare, model chain).
8. Welcome wizard, hotkeys, dark-mode pass, desktop polish, docs, tests.

## 6. Verification

Every phase: `make test` green, `make lint` clean, every route returns 200 on
both backends (JSON and DynamoDB), and the desktop window renders it. The
real-model check stays on Nova Lite; Nova Pro is for the recording.
