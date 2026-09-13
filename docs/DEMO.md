# Handoff — demo storyboard (5:00)

The whole video is one argument: *an agent that asks about everything is
useless, and an agent that asks about nothing is dangerous.* Handoff is the
line between those, and the line moves as it learns.

Rehearse with `make demo` (scripted model, instant, free). Record the real take
on Groq — but only once, because the free tier is 200K tokens/day and a full
run is ~25K.

---

## 0:00 – 0:25 · The problem, in their own inbox

Open on the terminal, nothing running.

> "Every morning I do the same twenty minutes of triage. File the real asks.
> Archive the newsletters. Reply to my manager. None of it is hard — it's just
> that it's every morning, and it's never worth building a tool for."

## 0:25 – 1:00 · One sentence becomes a workflow

Go to **Build a workflow**. Skip the templates; type the sentence and let the
Builder work.

> "I describe it once, the way I'd describe it to a colleague."

Let the generated config land on screen. Point at the `human_gate` step
specifically.

> "It picked the integrations, wrote the cron expression — and it decided where
> the line is between what it may do alone and what it has to ask me about.
> That's the part I care about."

## 1:00 – 2:00 · It runs, and mostly leaves you alone

Press **Run now** on the dashboard. The live feed appears under the row —
*fetched 8 messages… filed a ticket for… archived… not sure about this one,
setting it aside*. Let it reach **needs you**.

> "That feed is the agent working. You can watch it think — or not. That's the
> point: you don't have to."

Point at the counters: **7 handled on its own, 1 waiting on you**.

> "It stopped on one. Not one that was hard to parse — one that was genuinely
> ambiguous. And notice it didn't stop *at* that one and freeze. It set it
> aside and kept working through the rest of the inbox."

## 2:00 – 3:15 · The decision (the money shot)

Click the vendor email. Full screen on `/decide/…`.

> "One screen, one decision. Here's the email. Here's why it stopped —"

Read the agent's reasoning out loud, verbatim. On the recorded run it said:

> *"Unknown vendor pitching a 'strategic partnership' with a CEO intro call,
> flagged time-sensitive. I can't tell if this is a legitimate vendor worth
> engaging, or spam/phishing. Real stakes either way."*

> "That's not 'this is ambiguous'. That's it telling me exactly what it couldn't
> determine, so I can decide in five seconds without opening the email."

Point at the gauge.

> "Forty percent confident. The threshold is seventy. That gap is the whole
> product."

Now turn **Voice on**. Reload — it reads the decision aloud. Hold the mic and
say *"archive it, it's cold outreach."* Watch it match, submit, and speak back.

> "I didn't type anything. I told it, the way I'd tell a person. And the run
> picks up exactly where it stopped — not a new run, the same one. Its
> reasoning context survived my coffee break."

## 3:15 – 4:00 · It gets quieter

Show the learned rule on the dashboard — *"Archive cold outreach emails
pitching strategic partnerships or integrations."* Then **Run now** again.

> "Same inbox. Same eight messages."

Let it land on **0 waiting on you**, with **1 from rules you set**.

> "Zero questions. The one it asked about a minute ago, it handled itself —
> because I answered once and it wrote that down. It gets quieter the longer you
> use it."

## 4:00 – 4:35 · How it's built

Cut to `src/handoff/graph/hooks/hitl.py`, the `event.interrupt()` call
highlighted.

> "This is a `BeforeToolCallEvent` hook on the Strands Agents SDK. It fires
> before the tool body runs, so when the agent is unsure, nothing has happened
> to your mail yet. The interrupt suspends the agent loop; the human's answer
> resumes it."

Scroll to `finish_batch`.

> "And unsure items are deferred, not interrupted — one interrupt for the whole
> batch, once the pass is done. One screen, not one interruption per question."

Cut to the graph in `factory.py`.

> "Trigger, executor, completer — a Strands `Graph`, not a `Swarm`. A Swarm
> takes a different path every time. For something filing tickets in my name at
> 8am, that's a bug."

Cut to the trace view.

> "Every action attributed: what it did alone, what I decided, what it did from
> a rule I set."

## 4:35 – 5:00 · Close

> "Handoff runs on AgentCore Runtime, learns through AgentCore Memory, and
> reaches your tools over MCP. But the thing it actually does is simpler than
> that: it does the boring part, and it knows when to stop and ask."

End on the dashboard, **0 waiting on you**.

---

## Recording notes

- `make serve`, then reset between takes with `make clean`.
- Browser at 1280×900, zoom 110% — the decision screen should fill the frame.
- Don't narrate the counters; they're on screen. Narrate *why* it stopped.
- The voice moment needs a quiet room — the browser records raw mic audio and
  Whisper transcribes it.
- If a take runs long, cut 4:00–4:35 to just the `event.interrupt()` line. The
  decision moment is what must not be rushed.
- Real-model runs take 3–4 minutes wall-clock (Groq free-tier rate limits).
  Either cut away during the run or speed it up in the edit — don't leave three
  silent minutes in.
