# Agents for Humans: what I learned building Handoff, an agent that knows when to shut up

*Submission for the AWS "Agents for Humans" hackathon — Professional Agents track.*
*Code: https://github.com/LSUDOKO/Handoff · Site: https://handoff-eya.pages.dev*

## The problem I actually had

Every weekday morning I lose the first half hour to the same small work: triage
the inbox, file the real asks as tickets, archive the noise. None of it is
hard. It's just constant, and it never feels worth building a tool for —
because the tools I'd tried before either did too little (a filter that
archives newsletters) or too much (an "AI inbox assistant" that once sent a
reply I never approved).

That second failure mode is the one that matters. The fear isn't that an
agent is slow. It's that it *does something you never sanctioned*. So the
brief's own framing — an agent that "runs autonomously and only surfaces when
there's a real decision to make" — wasn't a spec I had to interpret. It was
already the exact shape of the thing I wanted to exist.

## Who it's for

Anyone with a recurring chore made of many small judgment calls: inbox triage,
PR review triage, a competitor-pricing watch, a Slack digest, meeting
follow-ups. The pattern repeats across roles — the thing changes, the shape
doesn't: most of the batch is unambiguous, a few items genuinely need a human,
and the two categories are different every single day.

## Why it matters

The cost of getting the gate wrong isn't symmetric. Ask about everything and
you've built a worse inbox with extra steps — a notification for every
decision you were already making yourself. Ask about nothing and you've built
something that archives the email you needed or files a ticket from spam. The
whole design problem is the threshold between those two failures, and being
able to move it as the system learns what you actually want.

## How it works

Handoff turns one sentence — spoken or typed — into a workflow built on the
[Strands Agents SDK](https://strandsagents.com):

- **Builder** — a conversational agent that turns "every weekday at eight,
  triage my inbox, ask me about anything unsure" into a runnable config in a
  few tool calls: pick integrations, write the cron, decide where the
  autonomy line sits, save and start it.
- **Executor** — a Strands `Graph` (`trigger → executor → completer`), because
  a job that files tickets in your name at 8am needs a deterministic,
  replayable path, not open-ended agent collaboration. It fetches the batch,
  judges each item with a confidence score, and acts on what's clear.
- **Learner** — turns each decision into a narrow rule (exact sender, whole
  domain, or two distinct keyword hits — never a vague guess), so the same
  question doesn't come back next week.

The gate is one hook, on one chokepoint:

```python
response = event.interrupt(
    interrupt_name,
    reason=payload.model_dump(mode="json"),
)
```

`BeforeToolCallEvent`, in front of `submit_action` — the only tool in the
executor that changes anything outside the process. Fetching and classifying
mail are free and reversible, so only the action is gated. Below the
confidence threshold, the call is deferred rather than interrupted
immediately: the executor finishes judging the whole batch first, and *then*
raises one `event.interrupt()` carrying every deferred item, so the person
answers everything on one screen instead of getting interrupted per item.
Measured on a real model run: 8 items, 7 handled alone, 1 escalated, **one**
interrupt, 3m47s end to end.

`graph.serialize_state()` means a run paused at 8:04 and answered at 11:30 is
still the same run — Handoff keeps no parallel pause state of its own.

## What's real, not staged

Every claim in the repo is backed by something I actually ran:

- **`handoff doctor`** makes a real API call per service rather than checking
  that a variable is set — Groq, AWS Bedrock, Polly + Transcribe, Gmail (its
  own OAuth), Linear, GitHub, Slack, Notion, Airtable, DynamoDB, AgentCore
  Memory. 11 working, 0 broken on the account I demo with.
- The demo video's "say" and "run" scenes are **live footage against my real
  Gmail inbox** — the spoken sentence transcribed by Amazon Transcribe, the
  workflow built and started on Bedrock Nova Pro, the Strands graph drawn
  live from its own hook events, and real newsletters archived by the
  executor. Not a synthetic fixture.
- Getting there meant fixing real integration bugs the synthetic demo never
  exercised: the real Gmail MCP server answers in `Key: value` text blocks,
  not JSON, and speaks `search_emails` / `modify_email`, not the
  `search_threads` / `archive` verbs I'd written against. Linear's remote
  server has no `create_issue` — it's `save_issue` plus a team lookup. Small
  adapter modules now translate, with unit tests against the real response
  shapes.

## On AWS

Bedrock (Nova Pro / Claude) does the reasoning behind all three agents.
Deployed, the executor graph runs as an **AgentCore Runtime** container;
**AgentCore Memory** holds the rules the Learner writes. Because EventBridge
Scheduler can't target AgentCore Runtime directly, a twelve-line Lambda
bridges the tick — two IAM roles, nothing else allowed. State is one
DynamoDB table (`pk` = collection, `sk` = id), so every list is a `Query`,
never a `Scan`. Voice is Amazon Transcribe in, Amazon Polly out.

None of this is required to run the thing — no AWS account, no keys, no
checkout beyond `git clone` gets you the same interrupt-and-learn loop on a
scripted model in about three minutes (`make demo`). AWS is where it becomes
production: real speech, a real schedule, real durability.

## What I'd tell the next person building an agent like this

The interrupt gate is the whole product, and it fits in one file. Everything
else — the graph, the memory, the three surfaces — exists to make that one
`event.interrupt()` trustworthy: that it fires *before* anything happens, not
after; that it asks once per batch, not once per item; that a rule it learns
is narrow enough to trust. If your agent's safety story can't be summarized
as "this hook, on this chokepoint, before the call," it's worth asking
whether you actually know where the risk lives.

---

*Handoff — Apache 2.0. Repo: https://github.com/LSUDOKO/Handoff · Architecture:
[docs/architecture.pdf](https://github.com/LSUDOKO/Handoff/blob/main/docs/architecture.pdf) ·
Site: https://handoff-eya.pages.dev*
