# Architecture

Handoff is three Strands agents, one Graph, a handful of hooks and an events bus, on a store with two backends. This page is the map: what each piece is for, how a run moves through them, and where the design choices came from.

## The shape of the problem

A background agent has exactly one hard question: when is it allowed to act without asking? Answer "always" and it files tickets from spam and archives the mail you needed. Answer "never" and it is a worse inbox with extra steps. Everything below falls out of answering that question well, and of being able to change the answer as the system learns what you want.

## Three agents

Separated because the jobs fail differently, not for tidiness.

| | Builder | Executor | Learner |
|---|---|---|---|
| Shape | conversational | autonomous graph | one-shot |
| Runs | while you type or talk | on a schedule | after each decision |
| Fails by | misunderstanding the ask | acting when it should not | over-generalising |
| Guardrail | a preview before saving | the interrupt gate | narrow matching |

The **Builder** turns a description into a workflow config you can read and version. It lives inside the workspace assistant — the same agent that operates the workspace from Chat and Talk — with tools to discover integrations, validate and preview a config, and save it. The **Executor** runs the workflow. The **Learner** turns each human decision into one narrow rule.

## The Graph

A workflow run is a Strands `Graph` with three nodes:

```
trigger ──▶ executor ──▶ completer
               │
               └── the gate (BeforeToolCallEvent on submit_action)
```

- **trigger** confirms the wake-up was legitimate: a cron fired, a webhook carried a body, a person pressed Run. The `trigger → executor` edge carries a condition — if the trigger reports `triggered: false`, the executor never runs and an empty signal costs no model call.
- **executor** does the work: recall rules, fetch, one `submit_action` per item, then `finish_batch`. The gate is attached here and only here.
- **completer** writes the audit entry and sends the completion notification.

Why `Graph` and not `Swarm`: a workflow is a fixed, auditable sequence with deterministic edges, one entry point and a replayable execution order. A swarm takes a different path every time, and for something filing tickets in your name at 8am, "different every time" is a bug.

The trigger and completer run on the cheaper fallback model; neither makes a judgement call. The executor runs on the primary.

## Hooks

Strands hooks are how Handoff observes and intervenes without touching the agent loop.

**The gate** (`graph/hooks/hitl.py`) registers on `BeforeToolCallEvent`. It applies learned rules, evaluates confidence, defers unsure items, and on `finish_batch` raises one `event.interrupt()` for everything deferred. On resume the same line returns the human's answers and the hook rewrites the pending call to what they chose. The gate is a suspension of one tool call, not a fork in the graph. See [The gate](/docs/the-gate).

**The narrator** registers on `BeforeToolCallEvent`, `AfterToolCallEvent` and the invocation events, and emits `tool_start` / `tool_end` with timings — plus `node_start` / `node_end` on the graph — onto the events bus. It is bound to every graph node and to every chat turn, which is what lets the Talk page draw the run graph as it fills in.

**The session recorder** is bound to every node and records each model turn and tool call with inputs, outputs, tokens and cost, so the Inspector can show a run — including the pause and what happened after it — as one trace.

## The events bus

`events.py` is an in-memory, per-process, bounded feed: up to 400 events for each of the last 50 channels. A channel is a run id or `chat:<id>`. Anything may `emit(channel, kind, text, **data)`; the web server exposes each channel over server-sent events at `/events/<run_id>`, and pages paint from it.

Run channels carry `started`, `fetched`, `acted`, `deferred`, `memory`, `asked`, `decided`, `resumed`, `completed`, `failed` and the narrator's node and tool events. Chat channels carry `delta` for streamed text, `tool_start` / `tool_end`, `asked` when a turn left decisions waiting, `workflow_saved` and `run_started` from the voice tools, and `done` with the final text and any config it produced.

The audit log is the record; the feed is the window. A restart loses the feed but not the record.

## Storage

One `Store` interface, two backends chosen by `USE_DYNAMODB`:

- **JSON files** under `HANDOFF_STATE_DIR`, one file per collection. The whole product runs on a laptop with no AWS account.
- **DynamoDB**, one table with `pk` = collection and `sk` = id. Same models, same methods.

The collections: workflows, runs, interrupts, audit, preferences, workspaces, credentials, tool servers, skills, agents, memory stores and entries, schedules, artifacts, sessions, usage, chats and chat messages, agent runs, profile. Access patterns are "get one by id" and "list a small collection", which is what the dashboard needs.

Chats are Strands sessions: each chat is an `Agent` with a `RepositorySessionManager` whose repository is backed by the store, so a conversation survives a restart and, deployed, lives in DynamoDB with the same durability as a run.

A paused run's graph state is serialised onto the run record and rehydrated on resume. Handoff keeps no parallel pause state — the Graph is the state.

## Memory

Learned rules live in the local store and, when `USE_AGENTCORE_MEMORY=true`, in AgentCore Memory as well, under a user-preference strategy and a semantic strategy per preference key. Recall is conservative on purpose: exact sender, whole domain, or two distinct keywords. Most of the tests about memory are about rules *not* matching.

## Providers

Bedrock, Anthropic and Groq sit behind `HANDOFF_MODEL_PROVIDER`; the agent code is identical. Two things learned from running open-weight models through Strands: tool-call JSON slips — a stray quote after a number — and the endpoint rejects the whole response, so a resilient provider repairs what the endpoint hands back instead of re-sampling; and tokens are the budget, so tools take ids and judgement only while the run context holds the text.

## Integrations

Tools are MCP servers rather than hard-coded clients, in a registry (`mcp/servers.py`): Gmail over a stdio server with its own OAuth, Linear and GitHub over their official remote servers, a credential-free web fetcher, AgentCore Browser and Code Interpreter, and Slack through the Web API directly because its MCP server was deprecated upstream. Adding a service is a registry entry and a credential, not a change to the executor.

## Speech

`handoff.speech` is one facade — `transcribe()`, `speak()`, `status()` — over three providers: Amazon Transcribe streaming and Polly, Groq Whisper and Orpheus, and the browser's own engines. The browser records 16 kHz PCM through an AudioWorklet; the server never needs ffmpeg.

## Two front ends, one gate

| Surface | The question goes to | Interrupt behaviour |
|---|---|---|
| Web / desktop | the decision screen, the Activity page, Chat, Talk | escapes; answered out of band; the run resumes later |
| Embedded in a host | the host's `request_human_input` | answered inline; the loop never unwinds |

Embedded, Handoff uses the host's already-authenticated tools and a gate subclass that hands the answer to `event.interrupt()` as a preemptive response. If the human channel is unreachable, it answers `skip`. An agent that cannot ask must not decide to act anyway.

## Layout

```
src/handoff/
├── graph/hooks/hitl.py     the interrupt gate
├── graph/factory.py        the Strands Graph
├── graph/nodes/            trigger, executor, classifier, gate, completer
├── agents/                 builder, executor runner, learner
├── chat/                   persisted chats and the streaming service
├── speech/                 Transcribe + Polly, Groq, WAV framing
├── platform/               workspaces, credentials, skills, agents, MCP, usage, workspace.yml
├── web/                    FastAPI + HTMX + Jinja — the shell and every page
├── cli/                    the command line
├── workflows/              the five templates
├── memory/store.py         AgentCore Memory and local rules
├── mcp/servers.py          the MCP registry
├── events.py               the live feed
├── store.py                JSON and DynamoDB behind one interface
├── doctor.py               real-call credential checks
└── app.py                  the AgentCore Runtime entrypoint
infra/                      DynamoDB, Memory, Runtime, IAM, Lambda, EventBridge
```
