# Devpost submission — Handoff

Paste-ready copy for the submission form. Replace the two placeholders at the
bottom before submitting.

---

**Tagline:** Describe it. Hand it off. It runs.

## Inspiration

Professionals lose the first half hour of every day to work that is too small
to automate and too constant to ignore: triaging mail, filing the real asks,
archiving the noise. Every tool built to help is another thing to open. The
hackathon brief put it exactly — an agent that *runs autonomously and only
surfaces when there's a real decision to make*. We built that sentence.

## What it does

You describe a chore in a sentence. Handoff turns it into a workflow — the
integrations, the schedule, and, most importantly, the line between what it may
do alone and what it must ask about. Then it runs on that schedule, handles what
it can judge confidently, sets aside what it can't, and asks you about all of it
on one screen. Your answer becomes a rule, so the next run asks less. You can
do all of it out loud: tap the orb, say the sentence, watch the workflow and
the run's graph appear, and answer the one question it has by voice.

On a real model, eight messages: seven handled alone, one escalated with a
specific reason — *"unknown vendor pitching a strategic partnership with a CEO
intro call; I can't tell if this is a legitimate vendor or phishing"* — one
interruption, then done. Answer it once and the next run asks nothing.

## How we built it

- **Strands Agents SDK, all the way down.** A `Graph` (trigger → executor →
  completer), three `Agent`s (Builder, Executor, Learner), fourteen `@tool`s,
  and a `BeforeToolCallEvent` hook on the one tool that changes anything.
- **The interrupt gate.** Unsure items are *deferred* during the pass; when the
  pass completes, `finish_batch` raises a single `event.interrupt()` carrying
  every deferred item. The graph state is serialised, so the run survives a
  restart and resumes — the same run — when you answer.
- **Learning that doesn't overreach.** The Learning Agent writes narrow rules
  (exact sender, whole domain, or two distinct keywords); the gate applies them
  before deciding whether to ask, so a question answered once is never asked
  again.
- **Providers.** Bedrock for the AgentCore deployment; Anthropic and Groq behind
  the same switch so a fresh clone reasons today. A resilient provider repairs
  tool-call JSON that open-weight models occasionally malform, instead of
  re-sampling.
- **Voice, on AWS.** The page streams the microphone to Amazon Transcribe over a
  WebSocket while you are still talking; Amazon Polly answers. Groq's Whisper
  and Orpheus are the second choice, browser speech the floor. Spoken turns run
  on the same Strands `Agent` as typed chat with two extra tools that save and
  start workflows; a hook bound to every graph node narrates the run so the
  page draws the `Graph` filling in. Spoken decisions are matched locally — no
  model round-trip to turn "archive it" into `archive`.
- **Three surfaces.** A web UI, a native desktop window that opens on the orb,
  and a CLI with every feature (`handoff chat`, `build`, `run --watch`, `talk`).
  A static site with the guides is on Cloudflare Pages.
- **Two surfaces.** A FastAPI + HTMX web UI with a live feed of the agent
  working (server-sent events), and a native desktop window via pywebview. It
  also embeds in another agent runtime, where the same gate answers through that
  host's own human-input channel.
- **Real integrations.** Gmail, Linear, Slack and GitHub over MCP and direct
  APIs; a credential-free web-fetch MCP server so the competitor-pricing
  workflow reads a live page on a fresh clone; `handoff doctor` verifies every
  credential with a real call.

## Challenges we ran into

Open-weight models through a strict endpoint. The first live runs died six tool
calls in on a stray quote after a number — `"confidence": 0.95"` — which the
endpoint rejects wholesale. Re-sampling at low temperature reproduces the same
slip. The fix that held wasn't a retry: it was making tools take ids and
judgement only, so there's little text to malform, and repairing what the
endpoint hands back rather than asking again. Free-tier token budgets forced the
same discipline — every argument the model re-types costs on every later turn.

And a product lesson that only showed up under a real model: the obvious
interrupt design — stop at the first unsure item — is worse UX than the batch.
With one tool call per item, the first hard email froze the rest of the inbox
and produced one interruption per question. Finish the pass, then ask once.

## Accomplishments we're proud of

Every Strands feature the brief names, used for its actual purpose, and a demo
that holds up on a real model rather than a scripted one. 255 tests. The
decision screen — the agent's reasoning in its own words, the confidence gauge
with the threshold marked, and four buttons.

## What we learned

Confidence is a real decision only when something depends on it. Making the gate
consult the number the model reports turned "estimate your confidence" from a
formality into the thing the whole product turns on — and the prompts had to
teach the model not to inflate it to avoid asking, or deflate it to avoid
responsibility.

## What's next for Handoff

It is deployed: AgentCore Runtime in ap-northeast-2, EventBridge Scheduler
through a twelve-line Lambda bridge, DynamoDB single-table state, AgentCore
Memory for learned rules. Next is the second-order rule: noticing when a
*learned* rule has started handling things you'd have wanted to see, and
asking about that — and a wake word for the orb.

## Built with

`strands-agents` · `amazon-bedrock` · `bedrock-agentcore` · `amazon-transcribe` ·
`amazon-polly` · `dynamodb` · `eventbridge` · `lambda` · `groq` · `anthropic` ·
`fastapi` · `htmx` · `pywebview` · `mcp` · `webgl` · `rich` · `cloudflare-pages` · `python`

## Links

- **Repository:** https://github.com/LSUDOKO/Handoff (Apache-2.0)
- **Site and docs:** https://handoff-eya.pages.dev
- **Pitch deck:** `docs/pitch/deck.pdf` (also `.pptx`) · **Script:** `docs/pitch/script.md`
- **Architecture:** `docs/architecture.png` (editable `docs/architecture.excalidraw`)
- **Demo video:** `ADD BEFORE SUBMITTING`
- **AWS Builder ID:** `ADD BEFORE SUBMITTING`
