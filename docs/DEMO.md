# Handoff — demo storyboard (5:00)

The whole video is one argument: *an agent that asks about everything is
useless, and an agent that asks about nothing is dangerous.* Handoff is the
line between those, and the line moves as it learns. This cut tells it out
loud: you talk, it builds, it runs, it asks, you answer, it stops asking.

Rehearse with `make demo` (scripted model, instant, free). Record the real
take on Bedrock Nova Pro — the whole take costs a few cents — and rehearse on
Nova Lite (`BEDROCK_MODEL_ID=amazon.nova-lite-v1:0`) until the words land.

---

## 0:00 – 0:20 · The problem, in their own inbox

Open on the desktop window, on **Talk**, the orb idle.

> "Every morning I do the same twenty minutes of triage. File the real asks.
> Archive the newsletters. Reply to my manager. None of it is hard — it's
> just that it's every morning, and it's never worth building a tool for."

## 0:20 – 1:00 · Say it once

Tap the orb. Say, in one breath:

> *"Every weekday at eight, triage my inbox. Real asks from teammates become
> Linear tickets, newsletters get archived, and ask me about anything you're
> not sure about. Set it up and run it now."*

Let the caption fill in as you speak — that is Amazon Transcribe streaming,
not a typed script. The orb turns violet while it thinks, green while it
calls tools; four tool lines appear under your words: *discover_mcp_tools,
validate_workflow, activate_workflow, start_run*.

Then the **workspace card** lands: *Signals* (the cron and its plain-English
reading), *Jobs* (what runs, where the line sits, where it reports), *Agents*
(gmail MCP, linear MCP, the executor LLM, the completer SEND). Handoff
answers out loud — one sentence, Polly's voice.

> "I described it once, the way I'd describe it to a colleague. It picked the
> integrations, wrote the cron, and — the part I care about — decided where
> the line is between what it may do alone and what it has to ask me about."

## 1:00 – 2:00 · It runs, and mostly leaves you alone

The **run graph** appears under the card — the Strands Graph, drawn from its
own hook events: *trigger → executor → completer*, and under the executor a
node per tool as it is called: *memory* recalled, *gmail* read eight,
*classify* judged eight, *act* handled seven. Each node shows milliseconds.

> "That's the agent working. You can watch it think — or not. That's the
> point: you don't have to."

It lands on **NEEDS YOU**. The orb goes amber — amber means exactly one thing
in Handoff: waiting on you. A decision card slides in under the graph, and
Handoff says so: *"I set aside one for you."*

> "Seven handled on its own, one waiting. It didn't stop *at* that one and
> freeze — it set it aside, finished the inbox, and asked once."

## 2:00 – 3:15 · The decision (the money shot)

Read the card out loud, verbatim. On the recorded run it said:

> *"Unknown vendor pitching a 'strategic partnership' with a CEO intro call,
> flagged time-sensitive. I can't tell if this is a legitimate vendor worth
> engaging, or spam/phishing. Real stakes either way."*

> "That's not 'this is ambiguous'. That's it telling me exactly what it
> couldn't determine, so I can decide in five seconds without opening the
> email."

Point at the badge: **40 % sure — needs 70 % to act alone.**

> "That gap is the whole product."

Say: *"Archive it — it's cold outreach."* No model round-trip: the phrase is
matched locally, the card flips to *decided*, Handoff says *"Archive it.
Done."*, and the run picks up exactly where it stopped — the same run, its
graph state restored, not a new one.

> "I didn't type anything. I told it, the way I'd tell a person."

## 3:15 – 4:00 · It gets quieter

Say: *"Run it again."* The graph redraws. *memory* now reads *1 rule
applied*. It lands on **DONE** with nothing set aside; the orb stays blue.

> "Same inbox. Zero questions. The one it asked about a minute ago, it handled
> itself — because I answered once and it wrote that down. It gets quieter the
> longer you use it."

Switch to **Memory** for two seconds: the rule it wrote is there in words.

## 4:00 – 4:35 · How it's built

Cut to `src/handoff/graph/hooks/hitl.py`, the `event.interrupt()` line.

> "This is a `BeforeToolCallEvent` hook on the Strands Agents SDK. It fires
> before the tool body runs, so when the agent is unsure nothing has happened
> to your mail yet. The interrupt suspends the agent loop; the answer resumes
> it. Unsure items are deferred, not interrupted — one interrupt for the whole
> batch."

Cut to `factory.py` for one beat.

> "Trigger, executor, completer — a Strands `Graph`, not a Swarm. The graph
> you just watched fill in *is* this graph; the nodes report through a hook."

## 4:35 – 5:00 · Close

Cut to the terminal: `handoff pending`, then `handoff run inbox-triage --watch`
streaming the same events. Then the landing page for two seconds.

> "Handoff runs on AgentCore Runtime, learns through AgentCore Memory, hears
> you through Transcribe and answers through Polly, and reaches your tools
> over MCP. But what it actually does is simpler than that: it does the boring
> part, and it knows when to stop and ask."

End on the orb, idle and blue.

---

## Recording notes

- `handoff desktop` at 1440×900. Reset between takes with **Start over** on
  the Talk page and `make clean`; the synthetic inbox (`USE_MOCK_TOOLS=true`)
  gives the same eight messages every time.
- A quiet room and a headset. Hands-free mode is off for the take — tap the
  orb so the cuts are predictable.
- Don't narrate the counters; they're on screen. Narrate *why* it stopped.
- If a take runs long, cut 4:00–4:35 to the `event.interrupt()` line alone.
  The decision moment is what must not be rushed.
- Nova Pro answers a spoken turn in 8–15 s and a run takes about a minute;
  cut away during the run or speed it up in the edit.
