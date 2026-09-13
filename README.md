# Handoff

**Describe it. Hand it off. It runs.**

Handoff turns a sentence into an autonomous workflow — and then gets out of your
way. It runs on a schedule, handles what it can judge confidently, and stops to
ask you only about the things it genuinely can't call.

> Built on the [Strands Agents SDK](https://strandsagents.com) for the
> [Agents for Humans Hackathon](https://agentsforhumans.devpost.com/) —
> Professional Agents track.

```
Every weekday at 8am, triage my inbox. Real asks from teammates become
Linear tickets. Newsletters get archived. Mail from my manager gets a
draft reply. Anything you're not sure about, ask me.
```

That sentence becomes a workflow config, a cron trigger, and a running job. The
first morning it asks you about the few things it couldn't call — on one screen,
or out loud. By the second, it has stopped asking.

![Architecture](docs/architecture.png)

## What it looks like

A workspace at a glance — latest runs, workflows, triggers, agents — in a
native desktop window or the browser, light or dark.

![Overview](docs/screens/overview.png)

| | |
|---|---|
| ![Activity](docs/screens/activity.png) | ![Decision](docs/screens/decision.png) |
| **Activity** — the few things it needs you for, answerable inline | **Decision** — the item, why it stopped, the gauge against the threshold |
| ![Chat](docs/screens/chat.png) | ![Run inspector](docs/screens/run-inspector.png) |
| **Chat** — a persisted Strands session that drives the workspace's tools | **Runs** — a waterfall of every model turn and tool call, with cost |
| ![Agent workbench](docs/screens/agent-workbench.png) | ![Tool servers](docs/screens/tool-servers.png) |
| **Agents** — run any agent on a prompt; Result · Tool calls · Trace | **Tool servers** — MCP catalogue with a live tool invoker |

---

## The one thing to look at

The hackathon brief asks for an agent that *"runs autonomously and only surfaces
when there's a real decision to make."* That sentence is implemented in one
file: [`src/handoff/graph/hooks/hitl.py`](src/handoff/graph/hooks/hitl.py).

A `BeforeToolCallEvent` hook sits in front of the only tool that changes
anything in the outside world. Before each call it decides whether the agent has
earned the right to act alone:

```python
response = event.interrupt(
    interrupt_name,
    reason=payload.model_dump(mode="json"),
)
```

On the first pass that raises `InterruptException` and unwinds the agent loop —
**before the tool body runs**, so nothing has happened to your mail. When a
human answers, the same line *returns their answer* instead of raising, and the
tool carries out what they chose.

Unsure items are **deferred, not interrupted**: the executor finishes its pass,
then `finish_batch` raises a single interrupt carrying all of them. You get one
screen, not one interruption per question. The Graph state is serialised, so a
run paused at 08:04 and answered at 11:30 is the same run — it survives a
restart.

**What it is not:** an approval prompt on every action. On a real model, eight
messages: seven handled silently, one escalated. An agent that interrupts on
everything is just a worse inbox.

---

## See it run

**With nothing at all** — the whole loop on a scripted model, no keys, no
account:

```bash
git clone https://github.com/LSUDOKO/Handoff && cd Handoff
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,groq,desktop,web]"
make demo
```

```
RUN 1 — it works the inbox on its own
  handled alone   5
  waiting on you  3

  ── Strategic partnership opportunity — time sensitive
     from partnerships@vendor.com
     30% sure of file_ticket
     Unknown external sender using urgency language. Could be a real business
     development lead or could be cold spam — I can't tell from one message,
     and filing or deleting both have a cost if I'm wrong.

YOU DECIDE — the three it couldn't call
  partnerships@vendor.com      → archive

RUN 2 — same inbox, and now it doesn't ask
  handled alone   5
  from your rules 3
  waiting on you  0
```

**With one free key** (Groq — real reasoning, and real voice):

```bash
cp .env.example .env       # set HANDOFF_MODEL_PROVIDER=groq and GROQ_API_KEY
make doctor                # every check makes a real API call
make desktop               # native window — or `make serve` for the browser
```

Press **Run now**. A live feed appears under the workflow — *fetched 8
messages… filed a ticket for… not sure about this one, setting it aside* — and
ends with what needs you. Turn **Voice on**, open a decision, hold the mic and
say *"archive it"*.

`HANDOFF_MODEL_PROVIDER` switches between `groq`, `anthropic` and `bedrock`. The
agent code is identical; only the model object differs. Bedrock is what the
AgentCore deployment uses. Full credential walkthrough:
[`docs/SETUP.md`](docs/SETUP.md).

---

## How it works

```
         "every weekday at 8am, triage my inbox…"
                          │
                          ▼
         ┌────────────────────────────────┐
         │  BUILDER AGENT                 │  picks the integrations, writes the
         │  conversational                │  cron trigger, and decides where the
         └────────────────┬───────────────┘  human line sits
                          │ workflow config (JSON)
                          ▼
   ┌──────────────────────────────────────────────────┐
   │  WORKFLOW EXECUTOR — a Strands Graph             │
   │                                                  │
   │   trigger ──▶ executor ──▶ completer             │
   │                  │                               │
   │                  └── HITL gate                   │
   │                       confident → act silently   │
   │                       unsure    → defer          │
   │                       end of pass → ask once     │
   └──────────────────────┬───────────────────────────┘
                          │ one screen, every decision
                          ▼
         ┌────────────────────────────────┐
         │  LEARNING AGENT                │  turns that decision into a rule, so
         │  post-decision                 │  the next run doesn't ask again
         └────────────────────────────────┘
```

### Three agents, because the jobs are different

| Agent | Does | Lives in |
|---|---|---|
| **Builder** | Turns a description into a workflow config you can read and version | [`agents/builder.py`](src/handoff/agents/builder.py) |
| **Executor** | Runs the workflow; decides what it may do alone | [`graph/factory.py`](src/handoff/graph/factory.py) |
| **Learner** | Turns each human decision into a narrow, reusable rule | [`agents/learner.py`](src/handoff/agents/learner.py) |

### Why `Graph` and not `Swarm`

A workflow is a fixed, auditable sequence: wake up, do the work, stop at
anything unclear, close out. `Graph` models exactly that — deterministic edges,
one entry point, a replayable execution order. `Swarm` models open-ended
collaboration between peers, which would make every run take a different path
through the same job. For something that files tickets in your name at 8am,
"different every time" is a bug, not a feature.

### Talk to it

Voice is real, not a browser trick: Groq **Whisper** transcribes what you say,
Groq **Orpheus** says things back, and the browser's own speech engines are the
fallback so nothing goes mute over a missing key. Spoken decisions — *archive
it, file a ticket, draft a reply, leave it* — are matched locally, with no model
round-trip. Turn **Voice on** in the header; decisions are read to you when they
open, and runs announce when they finish or set something aside.

### Watch it work

Every run streams what it's doing over server-sent events into a live feed on
the dashboard: what it fetched, what it did and how sure it was, what it set
aside and why. The audit log is the record; the feed is the window.

### Start from a template

Five workflows ship ready to run or adapt: morning inbox triage, weekly
competitor pricing watch (reads a live page through a credential-free MCP fetch
server), PR review triage, Slack channel digest, meeting follow-up.

### Learning that doesn't overreach

The Learning Agent's restraint matters more than its reach. A rule that fires
too eagerly takes actions nobody sanctioned, which is far worse than one extra
question. So `find_matching_preference` requires an exact sender match, a whole
domain, or **at least two distinct keyword hits** — one shared word is a
coincidence, not a rule. Most of the tests in
[`tests/test_learner.py`](tests/test_learner.py) are about rules *not* matching.

---

## The platform around the gate

The gate is one file. Around it is the surface a person needs before a
workflow engine is a product — modelled on the way an agent studio is laid
out, implemented in Python on Strands:

| Surface | What it does |
|---|---|
| **Workspaces** | Separate learned rules, credentials and agents. Each one is a `workspace.yml` you can edit in place, download, bundle with its skills, import elsewhere — the file is the configuration. |
| **Chat** | A Strands `Agent` per chat with a store-backed `SessionRepository`, so the thread survives restarts. It operates the workspace — runs workflows, reads runs, answers decisions — and builds new ones. Replies stream; every tool call is a card; a run that stops mid-chat surfaces its decision inline. |
| **Activity** | Pending and recent decisions across workspaces, answered inline with a note that becomes a rule. |
| **Runs / Inspector** | Every run as a timeline of graph nodes and a waterfall of steps, with inputs, outputs, timings, tokens and cost. |
| **Agents** | Built-in and custom agents (prompt + allow-listed tools + skills), each runnable from a workbench with run history and a credential preflight. |
| **Tool servers** | MCP servers as a catalogue: probe, list tools with schemas, **call one live**, see which workflows use it, add from the registry. |
| **Skills** | Markdown with front matter, grouped by namespace, with version history, a diff view, and import from files or a zip. |
| **Memory** | Learned rules and notes, per workspace, on local JSON or AgentCore Memory. |
| **Schedules** | An in-process cron scheduler for the desktop; EventBridge → Lambda → AgentCore Runtime in the cloud. |
| **Usage** | Tokens and cost per model and per run, attributed to the model that served the call. |
| **Settings** | A primary → fallback model chain per provider, written to `.env`; the gate's threshold; the runtime's facts. |
| **Welcome** | A first-run wizard that captures the one field cron cannot live without: your timezone. |

Keyboard: `⌘K` asks the workspace, `⌘/` switches workspaces, `/` focuses
chat. The desktop app remembers its window and reopens on the page you left.

## Two front ends, one gate

| Surface | The gate's question goes to | Code |
|---|---|---|
| **Web / desktop** | A decision screen; the interrupt escapes and is answered out of band | [`web/server.py`](src/handoff/web/server.py), [`desktop.py`](src/handoff/desktop.py) |
| **Embedded in a host runtime** | The host's `request_human_input` channel; answered inline, the loop never unwinds | [`host/`](src/handoff/host/) |

Handoff can run inside another agent runtime that already holds the user's OAuth
tokens — then it uses *those* credentials rather than keeping a second copy, and
asks through the host's own prompt. The host protocol is two methods:

```python
from handoff.host import run_in_host

result = run_in_host(ctx, "run the morning triage")
# ctx.tools.list() / ctx.tools.call(name, args) — that's the whole contract
```

---

## Strands SDK surface used

| Feature | Where |
|---|---|
| `Agent` class | all three agents |
| `@tool` decorator | 14 custom tools |
| `BeforeToolCallEvent` hook | [`graph/hooks/hitl.py`](src/handoff/graph/hooks/hitl.py) |
| `event.interrupt()` / resume | the gate, and `WorkflowRunner.resume` |
| Batch interrupt | `finish_batch` — one question for a whole pass |
| `Graph` + `GraphBuilder` | [`graph/factory.py`](src/handoff/graph/factory.py) |
| Conditional edges | an empty webhook never costs a model invocation |
| `Graph.serialize_state` | a paused run survives a process restart |
| `MCPClient` (stdio + HTTP) | [`mcp/servers.py`](src/handoff/mcp/servers.py) |
| `AgentTool` subclass | [`host/tools.py`](src/handoff/host/tools.py) — host tools as Strands tools |
| `OpenAIModel` subclass | [`providers.py`](src/handoff/providers.py) — repairs malformed tool-call JSON |
| OpenTelemetry tracing | `config.configure_observability()` |
| `SessionRepository` + `RepositorySessionManager` | [`chat/repository.py`](src/handoff/chat/repository.py) — chats persisted in the same store as everything else |
| `BeforeToolCallEvent` / `AfterToolCallEvent` narration | [`chat/service.py`](src/handoff/chat/service.py) — a card per tool call, streamed |

Built and verified against **`strands-agents` 1.55.1**, on a real model (Groq
`qwen/qwen3.8-27b`): 8 items, 7 handled alone, 1 escalated, one interrupt.

The interrupt API is version-sensitive — `event.interrupt(name, reason=…,
response=…)` returns the human's answer on resume rather than taking a `data=`
payload — so pin the version before changing anything in the gate.

---

## AWS deployment

| Service | Purpose |
|---|---|
| Amazon Bedrock (Amazon Nova / Claude Sonnet 4.5) | reasoning for all three agents |
| AgentCore Runtime | serverless background execution, long-running invocations |
| AgentCore Memory | learned preferences across runs |
| AgentCore Browser | the competitor-pricing workflow |
| AgentCore Observability | OTEL traces → CloudWatch |
| DynamoDB | one table, partitioned by collection — configs, runs, interrupts, sessions, usage, audit |
| EventBridge Scheduler → Lambda | cron triggers (Scheduler cannot invoke AgentCore directly; a twelve-line function forwards the tick) |
| SNS | "a decision is waiting" notifications |

```bash
python infra/deploy_agentcore.py --check    # tells you exactly what's missing
python infra/deploy_agentcore.py            # build (arm64) → ECR → Runtime, via boto3
python infra/memory_setup.py                # AgentCore Memory store
python infra/dynamodb_setup.py              # one table, partitioned by collection
python infra/iam_setup.py                   # the role EventBridge Scheduler assumes
python infra/lambda_setup.py --runtime-arn … # Scheduler can't target AgentCore directly
python infra/eventbridge_setup.py --target-arn <lambda> --role-arn <role>
```

Every store has a local JSON backend, so none of this is required to run, test
or demo the project — only to deploy it.

**Two things Bedrock will tell you confusingly.** Model ids are not bare: a
current model is reached through a cross-region inference profile prefixed by
geography (`us.`, `apac.`, `eu.`), and the prefix must match the region you
call from — so Handoff resolves a bare id against `AWS_REGION` rather than
hardcoding one. And Anthropic models on Bedrock are sold through AWS
Marketplace while Amazon's own are not, so an account that cannot complete a
Marketplace agreement gets `INVALID_PAYMENT_INSTRUMENT` on Claude in *every*
region and works fine on Nova. That is why the default is Nova Pro.
[`docs/SETUP.md`](docs/SETUP.md) has the long version.

---

## Tests

```bash
make test
# 168 passed
```

The ones worth reading are in
[`tests/test_hitl_gate.py`](tests/test_hitl_gate.py), which drive the gate
inside a real Strands agent and assert the things that actually matter:

- an unsure call stops the loop **and the tool never runs**
- resuming executes what the human chose, not what the agent suggested
- choosing "leave it" cancels the tool rather than running it with a no-op
- a malformed confidence score fails toward asking, never toward acting

---

## Layout

```
src/handoff/
├── graph/hooks/hitl.py     ⭐ the interrupt gate
├── graph/factory.py        the Strands Graph
├── graph/nodes/            trigger, executor, classifier, gate, completer
├── agents/                 builder, executor runner, learner
├── host/                   embed Handoff in another agent runtime
├── chat/                   persisted chats: store-backed SessionRepository, streaming service
├── platform/               workspaces, credentials, skills, agents, workbench, MCP, usage, workspace.yml
├── web/                    FastAPI + HTMX + Jinja — the shell and every page; tokens.css / ui.css / pages.css
├── workflows/              five shipped templates
├── memory/store.py         AgentCore Memory + local preferences
├── mcp/servers.py          MCP registry
├── tools/voice.py          Whisper in, Orpheus out, spoken commands
├── providers.py            resilient OpenAI-compatible provider
├── events.py               live run feed (SSE)
├── desktop.py              native window that remembers itself
├── doctor.py               real-call credential checks
└── app.py                  AgentCore Runtime entrypoint

docs/       ARCHITECTURE · SETUP · DEMO · SUBMISSION · diagram · plan/
infra/      AgentCore, DynamoDB, Memory, EventBridge
tests/      168 tests
```

---

## Licence

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

All of it is original work built on the Strands Agents SDK. No third-party
source is vendored; every dependency is installed from its own distribution and
stays under its own licence.
