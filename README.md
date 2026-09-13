<p align="center">
  <img src="docs/assets/header.png" alt="Handoff — Describe it. Hand it off. It runs." width="100%">
</p>

<p align="center">
  <a href="https://handoff-eya.pages.dev"><img alt="Site" src="https://img.shields.io/badge/site-handoff--eya.pages.dev-1e1e1e?style=flat-square"></a>
  <a href="https://handoff-eya.pages.dev/docs"><img alt="Docs" src="https://img.shields.io/badge/docs-8%20guides-1e1e1e?style=flat-square"></a>
  <img alt="Tests" src="https://img.shields.io/badge/tests-255%20passing-2f855a?style=flat-square">
  <img alt="Strands" src="https://img.shields.io/badge/Strands%20Agents%20SDK-1.55-1e1e1e?style=flat-square">
  <img alt="AWS" src="https://img.shields.io/badge/AWS-Bedrock%20%C2%B7%20AgentCore%20%C2%B7%20Transcribe%20%C2%B7%20Polly-ff9900?style=flat-square&logoColor=white">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-1e1e1e?style=flat-square"></a>
</p>

# Handoff

**Describe it. Hand it off. It runs.**

Handoff turns a sentence — spoken or typed — into an autonomous workflow on the
[Strands Agents SDK](https://strandsagents.com), runs it on a schedule on AWS,
handles what it can judge confidently, and stops to ask you only about the
things it genuinely can't call. Your answer becomes a rule, so it asks less
every week.

> Built for the [Agents for Humans Hackathon](https://agentsforhumans.devpost.com/),
> **Professional Agents track**. The brief asked for an agent that *runs
> autonomously and only surfaces when there's a real decision to make.*
> This repository is that sentence, with the receipts.

| | |
|---|---|
| **Live site and guides** | <https://handoff-eya.pages.dev> · [docs](https://handoff-eya.pages.dev/docs) |
| **Pitch** | [deck (PDF)](docs/pitch/deck.pdf) · [deck (PPTX)](docs/pitch/deck.pptx) · [speaker script](docs/pitch/script.md) |
| **Architecture** | [diagram](docs/architecture.png) · [editable Excalidraw](docs/architecture.excalidraw) · [ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **Demo video** | `ADD BEFORE SUBMITTING` · storyboard in [docs/DEMO.md](docs/DEMO.md) |

---

## Contents

1. [The sixty-second tour](#the-sixty-second-tour)
2. [What the hackathon asked for, and where it is](#what-the-hackathon-asked-for-and-where-it-is)
3. [Say it, watch it run](#say-it-watch-it-run)
4. [The gate](#the-gate)
5. [Architecture](#architecture)
6. [Built on Strands — with proof](#built-on-strands--with-proof)
7. [On AWS — with proof](#on-aws--with-proof)
8. [Three surfaces: Talk, terminal, browser](#three-surfaces-talk-terminal-browser)
9. [Run it yourself](#run-it-yourself)
10. [Verification and cost](#verification-and-cost)
11. [Layout](#layout)
12. [Licence](#licence)

---

## The sixty-second tour

Tap the orb and say: *"Every weekday at eight, triage my inbox. Real asks from
teammates become Linear tickets, newsletters get archived, ask me about
anything unsure. Set it up and run it now."*

| | |
|---|---|
| ![Talk](docs/screens/orb.png) | ![The run graph](docs/screens/ui/orb-graph.png) |
| **1 · Say it.** The caption fills in while you speak (Amazon Transcribe, streaming). Four tool calls later the workflow is saved, switched on, and started. | **2 · Watch it run.** The Strands Graph, drawn live from its own hook events: memory applied a rule, Gmail read eight, the executor handled seven and set one aside. |
| ![Decision](docs/screens/decision.png) | ![Terminal](docs/screens/terminal/run-watch.png) |
| **3 · One question.** Why it stopped, in the agent's words; how sure it was; four buttons — or say *"archive it"*. | **4 · Or from the terminal.** `handoff run --watch` streams the same events; every command takes `--json`. |

Every screenshot in this README was taken from the running product on
2026‑09‑13 — the web UI through Playwright, the terminal through
[freeze](https://github.com/charmbracelet/freeze), the AWS console state
through the AWS CLI. Nothing is mocked up.

---

## What the hackathon asked for, and where it is

| Requirement | How Handoff meets it | Proof |
|---|---|---|
| Runs autonomously | A Strands `Graph` (trigger → executor → completer) runs on a cron schedule — in-process on the desktop, EventBridge → Lambda → **AgentCore Runtime** in the cloud | [run graph](docs/screens/ui/orb-graph.png) · [`aws scheduler` / `lambda`](docs/screens/aws/scheduler-lambda.png) |
| Surfaces only for real decisions | A `BeforeToolCallEvent` hook gates the one tool that changes anything; below the confidence threshold it defers, then asks **once** for the whole batch | [decision screen](docs/screens/decision.png) · [`hitl.py`](src/handoff/graph/hooks/hitl.py) |
| Built on the Strands Agents SDK | `Agent`, `Graph`, hooks, `event.interrupt()`, `SessionRepository`, `MCPClient`, 16 `@tool`s | [imports proof](docs/screens/terminal/strands.png) · [table below](#built-on-strands--with-proof) |
| Uses AWS | Bedrock (Nova), AgentCore Runtime + Memory, Transcribe, Polly, DynamoDB, EventBridge, Lambda, ECR — all live in `ap-northeast-2` | [`handoff doctor`](docs/screens/terminal/doctor.png) · [AgentCore](docs/screens/aws/agentcore.png) · [DynamoDB](docs/screens/aws/dynamodb.png) |
| Professional use | Inbox triage, PR review triage, competitor pricing watch, Slack digest, meeting follow-up — shipped as templates; anything else described in a sentence | [workflows](docs/screens/terminal/workflows.png) · [discover](docs/screens/ui/discover.png) |
| Learns the person | Each decision becomes a narrow rule (sender, domain, or two keywords); AgentCore Memory in the cloud, JSON locally; the next run asks less | [decide → rule](docs/screens/terminal/decide.png) · [memory](docs/screens/ui/memory.png) |
| Real, not scripted | Verified end-to-end on Bedrock Nova: a spoken sentence ends as an active, running workflow; 8 items, 7 handled alone, 1 escalated | [ask](docs/screens/terminal/ask.png) · [inspect](docs/screens/terminal/inspect.png) · [usage](docs/screens/terminal/usage.png) |

---

## Say it, watch it run

**Talk** is the first page in the sidebar. The orb is a WebGL sphere whose
colour follows the agent — blue idle, teal listening, violet thinking, green
while a tool runs, and **amber only when it is waiting on you**. Tap it, hold
`Space`, or switch on hands-free and it ends each utterance on silence and
listens again after it answers. `Ctrl+Space` opens it from any page.

<p align="center"><img src="docs/screens/ui/orb-card.png" width="100%" alt="The workspace card a sentence became"></p>

What a spoken turn produces is drawn on the page from the agent's own events:

- the **workspace card** when a workflow is saved — *Signals* (the cron and its
  plain-English reading), *Jobs* (what runs, where the line sits, where it
  reports), *Agents* (each MCP tool, the executor LLM, the completer SEND);
- the **run graph** when a run starts — the real Graph, a node per tool call,
  with milliseconds, until it lands on DONE or NEEDS YOU;
- the **decision card** when it stops — answerable with a click or a phrase.

<p align="center"><img src="docs/screens/ui/orb-work-panel.png" width="100%" alt="The work panel: run graph and decision cards"></p>

Spoken decisions — *archive it, file a ticket, draft a reply, leave it* — are
matched locally with no model round-trip. Speech streams to **Amazon
Transcribe** over a WebSocket while you are still talking; **Amazon Polly**
answers; Groq's Whisper and Orpheus are the second choice and the browser's
own engines the floor, so nothing goes mute over a missing key.

---

## The gate

The whole product is one file:
[`src/handoff/graph/hooks/hitl.py`](src/handoff/graph/hooks/hitl.py).

```python
response = event.interrupt(
    interrupt_name,
    reason=payload.model_dump(mode="json"),
)
```

A `BeforeToolCallEvent` hook sits in front of the only tool that changes
anything in the outside world. On the first pass, below the confidence
threshold, that line raises `InterruptException` and unwinds the agent loop
**before the tool body runs** — nothing has happened to your mail. When a
human answers, the same line *returns their answer*, and the tool carries out
what they chose.

Unsure items are **deferred, not interrupted**: the executor finishes its
pass, then `finish_batch` raises a single interrupt carrying all of them. You
get one screen, not one interruption per question. The Graph state is
serialised, so a run paused at 08:04 and answered at 11:30 is the same run —
it survives a restart.

What it is not: an approval prompt on every action. An agent that interrupts
on everything is just a worse inbox.

---

## Architecture

<p align="center"><img src="docs/architecture.png" width="100%" alt="Handoff architecture"></p>

The diagram is generated from
[`scripts/make_architecture.py`](scripts/make_architecture.py) into an
editable [Excalidraw file](docs/architecture.excalidraw); the long-form
walkthrough is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Three agents, because the jobs are different:

| Agent | Does | Lives in |
|---|---|---|
| **Builder / voice assistant** | Turns a description into a workflow config; the spoken variant saves and starts it in one turn | [`agents/builder.py`](src/handoff/agents/builder.py), [`chat/service.py`](src/handoff/chat/service.py), [`chat/voice_tools.py`](src/handoff/chat/voice_tools.py) |
| **Executor** | Runs the workflow as a Graph; decides what it may do alone | [`graph/factory.py`](src/handoff/graph/factory.py), [`graph/hooks/hitl.py`](src/handoff/graph/hooks/hitl.py) |
| **Learner** | Turns each human decision into a narrow, reusable rule | [`agents/learner.py`](src/handoff/agents/learner.py) |

Why `Graph` and not `Swarm`: a workflow is a fixed, auditable sequence — wake
up, do the work, stop at anything unclear, close out. `Graph` models exactly
that. `Swarm` models open-ended collaboration, which would make every run take
a different path through the same job. For something filing tickets in your
name at 8am, "different every time" is a bug.

---

## Built on Strands — with proof

<p align="center"><img src="docs/screens/terminal/strands.png" width="100%" alt="Strands versions and every import"></p>

| SDK feature | Where it earns its place |
|---|---|
| `Agent` | the Builder, the voice assistant, the executor, the completer, the Learner, the chat |
| `@tool` decorator | 16 custom tools, from `fetch_unread_emails` to `activate_workflow` |
| `BeforeToolCallEvent` hook + `event.interrupt()` | the gate — [`graph/hooks/hitl.py`](src/handoff/graph/hooks/hitl.py); resume returns the human's answer |
| Batch interrupt | `finish_batch` — one question for a whole pass |
| `Graph` + `GraphBuilder` + conditional edges | [`graph/factory.py`](src/handoff/graph/factory.py); an empty webhook never costs a model call |
| `Graph.serialize_state` | a paused run survives a process restart |
| `BeforeInvocationEvent` / `AfterInvocationEvent` / `AfterToolCallEvent` | [`graph/hooks/narrator.py`](src/handoff/graph/hooks/narrator.py) — one narrator per node; the orb draws the Graph from these |
| `SessionRepository` + `RepositorySessionManager` | [`chat/repository.py`](src/handoff/chat/repository.py) — chats persisted in the same store as everything else; the terminal and the browser share a session |
| Context variables into tools | [`chat/voice_tools.py`](src/handoff/chat/voice_tools.py) — `activate_workflow` and `start_run` emit on the page's channel |
| `MCPClient` (stdio + HTTP) | [`mcp/servers.py`](src/handoff/mcp/servers.py) — Gmail, Linear, Slack, GitHub, web |
| `AgentTool` subclass | [`host/tools.py`](src/handoff/host/tools.py) — a host runtime's tools as Strands tools |
| `OpenAIModel` subclass | [`providers.py`](src/handoff/providers.py) — repairs malformed tool-call JSON |
| OpenTelemetry tracing | `config.configure_observability()` |

Built and verified against **`strands-agents` 1.55.1** on real models
(Bedrock Nova Pro and Nova Lite, Groq `qwen/qwen3.8-27b`). The interrupt API
is version-sensitive — `event.interrupt(name, reason=…)` returns the human's
answer on resume — so pin the version before changing the gate.

<details>
<summary><b>The tests that matter</b> (255 passing, lint clean)</summary>
<p align="center"><img src="docs/screens/terminal/tests.png" width="100%" alt="make test"></p>

[`tests/test_hitl_gate.py`](tests/test_hitl_gate.py) drives the gate inside a
real Strands agent and asserts the things that actually matter: an unsure call
stops the loop **and the tool never runs**; resuming executes what the human
chose, not what the agent suggested; "leave it" cancels the tool; a malformed
confidence score fails toward asking, never toward acting.
[`tests/test_orb.py`](tests/test_orb.py) runs a whole spoken turn on the
scripted model and asserts it ends active and running.
</details>

---

## On AWS — with proof

Everything below is live in `ap-northeast-2`, captured with the AWS CLI on
2026‑09‑13 (account id masked).

| Service | Purpose | Proof |
|---|---|---|
| **Amazon Bedrock** — Nova Pro / Nova Lite | reasoning for every agent, through cross-region inference profiles | [inference profiles + doctor](docs/screens/aws/bedrock-speech.png) |
| **AgentCore Runtime** | serverless background execution, arm64 container, session per run, long-running invocations | [`list-agent-runtimes` → READY](docs/screens/aws/agentcore.png) |
| **AgentCore Memory** | learned preferences across runs | [`list-memories` → ACTIVE](docs/screens/aws/agentcore.png) |
| **Amazon Transcribe** (streaming) | hears you — partial results while you speak | [Polly voices + `doctor speech`](docs/screens/aws/bedrock-speech.png) |
| **Amazon Polly** (neural) | speaks back | same |
| **DynamoDB** | one table, `pk` = collection, `sk` = id — configs, runs, interrupts, sessions, usage, audit | [`describe-table`](docs/screens/aws/dynamodb.png) |
| **EventBridge Scheduler → Lambda** | cron triggers; Scheduler cannot target AgentCore directly, so a twelve-line function forwards the tick | [schedules, function, ECR repo](docs/screens/aws/scheduler-lambda.png) |
| **ECR** | the runtime's image | same |
| **IAM** | one execution role for the runtime, one for the scheduler with a single permission | [`infra/iam_setup.py`](infra/iam_setup.py) |

<p align="center"><img src="docs/screens/terminal/doctor.png" width="100%" alt="handoff doctor: every check is a real call"></p>

<details>
<summary><b>More AWS proofs</b></summary>

| | |
|---|---|
| ![identity](docs/screens/aws/identity.png) | ![agentcore](docs/screens/aws/agentcore.png) |
| ![dynamodb](docs/screens/aws/dynamodb.png) | ![scheduler + lambda + ecr](docs/screens/aws/scheduler-lambda.png) |
| ![bedrock + speech](docs/screens/aws/bedrock-speech.png) | ![cloudflare](docs/screens/aws/cloudflare.png) |
</details>

Deploying is a handful of boto3 scripts, no console clicking:

```bash
python infra/deploy_agentcore.py --check     # says exactly what is missing
python infra/deploy_agentcore.py             # build (arm64) → ECR → AgentCore Runtime
python infra/memory_setup.py                 # AgentCore Memory store
python infra/dynamodb_setup.py               # the single table
python infra/iam_setup.py                    # the role EventBridge Scheduler assumes
python infra/lambda_setup.py --runtime-arn … # the bridge
python infra/eventbridge_setup.py --target-arn <lambda> --role-arn <role>
```

Every store has a local JSON backend, so none of this is required to run,
test or demo the project — only to deploy it. The site is the one thing not on
AWS: static files on Cloudflare Pages.

**Two things Bedrock tells you confusingly.** Model ids are reached through a
cross-region inference profile prefixed by geography (`us.`, `apac.`, `eu.`),
and the prefix must match the calling region — Handoff resolves a bare id
against `AWS_REGION`. And Anthropic models on Bedrock are sold through AWS
Marketplace while Amazon's own are not, so an account that cannot complete a
Marketplace agreement gets `INVALID_PAYMENT_INSTRUMENT` on Claude in every
region and works on Nova. That is why the default is Nova Pro.

---

## Three surfaces: Talk, terminal, browser

### Talk and the desktop window

`handoff desktop` opens a native window (WebKitGTK, WebKit or WebView2 —
no Electron) on the orb, remembers its size and page, records the microphone
itself if the webview will not, and attaches to an already-running instance
instead of starting a second scheduler.

### The terminal

Every feature is a command. `handoff chat` streams the same assistant into
your terminal and the conversation continues in the browser (one session
repository); `handoff build "<sentence>" --activate --run` turns a sentence
into an active workflow; `handoff talk --mic` is the orb without the orb.

<p align="center"><img src="docs/screens/terminal/help.png" width="100%" alt="handoff --help"></p>

<details>
<summary><b>Terminal proofs</b> — a real run on Bedrock Nova, start to finish</summary>

| | |
|---|---|
| ![run --watch](docs/screens/terminal/run-watch.png) | ![pending](docs/screens/terminal/pending.png) |
| ![decide → rule](docs/screens/terminal/decide.png) | ![inspect](docs/screens/terminal/inspect.png) |
| ![ask](docs/screens/terminal/ask.png) | ![usage](docs/screens/terminal/usage.png) |
| ![workflows](docs/screens/terminal/workflows.png) | ![agents + skills](docs/screens/terminal/agents-skills.png) |
| ![mcp](docs/screens/terminal/mcp.png) | ![schedules + credentials](docs/screens/terminal/schedules-creds.png) |
| ![git log](docs/screens/terminal/gitlog.png) | |
</details>

### The browser

| | |
|---|---|
| ![Overview](docs/screens/overview.png) | ![Activity](docs/screens/activity.png) |
| **Workspace overview** — latest runs, workflows, triggers, agents | **Activity** — the few things it needs you for, answerable inline |
| ![Chat](docs/screens/chat.png) | ![Run inspector](docs/screens/run-inspector.png) |
| **Chat** — a persisted Strands session; every tool call is a card | **Runs** — a waterfall of every model turn and tool call, with cost |
| ![Agents](docs/screens/agent-workbench.png) | ![Tool servers](docs/screens/tool-servers.png) |
| **Agents** — run any agent on a prompt; result, tool calls, trace | **Tool servers** — the MCP catalogue with a live invoker |

<details>
<summary><b>Every page</b> (light and dark)</summary>

| | |
|---|---|
| ![skills](docs/screens/ui/skills.png) | ![memory](docs/screens/ui/memory.png) |
| ![usage](docs/screens/ui/usage.png) | ![settings](docs/screens/ui/settings.png) |
| ![credentials](docs/screens/ui/credentials.png) | ![schedules](docs/screens/ui/schedules.png) |
| ![discover](docs/screens/ui/discover.png) | ![docs](docs/screens/ui/docs.png) |
| ![overview dark](docs/screens/ui/overview-dark.png) | ![activity dark](docs/screens/ui/activity-dark.png) |
| ![settings dark](docs/screens/ui/settings-dark.png) | ![docs dark](docs/screens/ui/docs-dark.png) |
</details>

The platform around the gate — workspaces as `workspace.yml`, chat, activity,
runs and inspector, agents and a workbench, tool servers, skills with version
history, memory, schedules, usage, settings, a welcome wizard — is documented
in the [guides](https://handoff-eya.pages.dev/docs) and in-app at `/docs`.

### The site

<https://handoff-eya.pages.dev> is a framework-free static site — the landing
page with the live orb, and the guides — built by `site/build.py` from
`docs/site/*.md` and published to Cloudflare Pages with `make site-deploy`.

| | |
|---|---|
| ![site](docs/screens/ui/site-hero.png) | ![site docs](docs/screens/ui/site-docs.png) |

---

## Run it yourself

**With nothing at all** — the whole loop on a scripted model, no keys, no
account:

```bash
git clone https://github.com/LSUDOKO/Handoff && cd Handoff
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,bedrock,desktop,web,voice]"
make demo
```

**On AWS** — Bedrock for reasoning, Transcribe and Polly for voice, one
`aws configure` and no other keys:

```bash
cp .env.example .env        # HANDOFF_MODEL_PROVIDER=bedrock, AWS_REGION=ap-northeast-2
make doctor                 # every check makes a real call
make desktop                # native window, opens on the orb — or `make serve`
```

**With one free key** (Groq): set `HANDOFF_MODEL_PROVIDER=groq` and
`GROQ_API_KEY`; Whisper hears and Orpheus speaks.

| Variable | Meaning |
|---|---|
| `HANDOFF_MODEL_PROVIDER` | `bedrock` · `groq` · `anthropic` — identical agent code, different model object |
| `HANDOFF_SPEECH_PROVIDER` | `auto` (AWS, then Groq, then browser) · `aws` · `groq` · `browser` |
| `BEDROCK_MODEL_ID` / `BEDROCK_FALLBACK_MODEL_ID` | bare ids; the geography prefix is added for `AWS_REGION` |
| `CONFIDENCE_THRESHOLD` | below this the gate asks instead of acting (default 0.7) |
| `USE_MOCK_TOOLS` | `true` = the synthetic eight-message inbox; `false` = real MCP servers |
| `USE_DYNAMODB` / `USE_AGENTCORE_MEMORY` | cloud state; `false` = local JSON |

Full credential walkthrough — Gmail's own OAuth sign-in, Linear, Slack, GitHub
— in [docs/SETUP.md](docs/SETUP.md). The CLI's `--state-dir` always means
local storage, so a scratch run can never touch the live table.

---

## Verification and cost

| | |
|---|---|
| Tests | 255 passing · `ruff` clean |
| Doctor | Bedrock, Speech, DynamoDB, AgentCore Memory green; Gmail, Linear, Slack, GitHub skipped until keys exist |
| Real-model check | a spoken set-up on Nova Lite ends active and running in two of two attempts; 8 items, 7 handled alone, 1 escalated |
| Speech round trip | Polly said a sentence, Transcribe returned it word for word |
| Spend | a spoken turn on Nova Lite costs under a tenth of a cent; Transcribe is $0.024/min, Polly $16 per million characters; a full demo take on Nova Pro is cents |

---

## Layout

```
src/handoff/
├── graph/hooks/hitl.py     ⭐ the interrupt gate
├── graph/hooks/narrator.py node and tool timings on the events bus — what the orb draws
├── graph/factory.py        the Strands Graph
├── graph/nodes/            trigger, executor, classifier, gate, completer
├── agents/                 builder, executor runner, learner
├── chat/                   persisted chats, streaming service, voice tools
├── speech/                 Transcribe + Polly, Whisper + Orpheus, WAV framing — one facade
├── cli/                    every feature from the terminal, one module per command group
├── platform/               workspaces, credentials, skills, agents, workbench, MCP, usage, workspace.yml
├── web/                    FastAPI + HTMX + Jinja — the shell and every page; orb.js / talk.js / work-panel.js
├── docs.py                 the guides, rendered for the app and the site
├── host/                   embed Handoff in another agent runtime
├── workflows/              five shipped templates
├── memory/store.py         AgentCore Memory + local preferences
├── mcp/servers.py          MCP registry
├── tools/voice.py          spoken commands, matched without a model
├── providers.py            resilient OpenAI-compatible provider
├── events.py               live run feed (SSE)
├── desktop.py              native window with a microphone bridge
├── doctor.py               real-call credential checks
└── app.py                  AgentCore Runtime entrypoint

docs/       ARCHITECTURE · SETUP · DEMO · SUBMISSION · pitch/ · site/ (guides) · screens/ · architecture.excalidraw
site/       the landing page and docs build, deployed to Cloudflare Pages
infra/      AgentCore, DynamoDB, Memory, IAM, Lambda, EventBridge — boto3, no console
scripts/    architecture generator and exporter, secret guard
tests/      255 tests
```

---

## Licence

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

All of it is original work built on the Strands Agents SDK. No third-party
source is vendored; every dependency is installed from its own distribution
and stays under its own licence. The orb's shader is adapted from
[DORA](https://github.com/Aaditya1273/DORA) (MIT) and the visual language from
[Agent.md](https://github.com/Aaditya1273/Agent.md) (MIT); both are credited
in `NOTICE`.
