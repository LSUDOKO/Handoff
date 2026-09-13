# Pitch script — Handoff (3 minutes, 13 slides)

Spoken at a natural pace this runs 2:50. Slide cues in **bold**; pauses marked ⏸.

**Slide 1 — title.** Handoff. You describe a chore in one sentence; it hands the chore off to an agent that runs it on a schedule, and only comes back to you when there is a real decision to make.

**Slide 2 — the half hour.** Every professional loses the first half hour of the day to the same small work. Triage the inbox. File the real asks. Archive the noise. None of it is hard, it's just every single morning — and it's never worth building a tool for. The tools that exist are another thing to open. And the thing people actually fear from an agent isn't that it's slow. It's that it does something they never sanctioned. ⏸ The hackathon brief put it exactly: an agent that runs autonomously and only surfaces when there's a real decision to make. We built that sentence.

**Slide 3 — say it once.** This is the Talk page. You tap the orb and you say it — every weekday at eight, triage my inbox, real asks become tickets, newsletters get archived, ask me about anything unsure. The caption fills in while you speak; that's Amazon Transcribe streaming over a WebSocket. Four tool calls later, the agent has picked the integrations, written the cron expression, and — the part I care about — decided where the line sits between what it may do alone and what it has to ask me about. Then it switched it on and told me so, in one sentence, in Polly's voice.

**Slide 4 — it runs.** And this is it running. That graph isn't a mock-up — it's the Strands Graph, drawn live from its own hook events. Memory recalled a rule. Gmail read eight. The executor judged them and acted on seven. And it set one aside. ⏸ Notice it didn't stop *at* that one and freeze the rest of the inbox. It finished the pass and asked once.

**Slide 5 — the gate.** The whole product is this one line. A `BeforeToolCallEvent` hook sits in front of the only tool that changes anything in the outside world. Below the confidence threshold it raises the interrupt *before the tool body runs* — so when the agent is unsure, nothing has happened to your mail yet. Unsure items are deferred, not interrupted, and the graph state is serialised, so a run paused at eight and answered at eleven-thirty is the same run. ⏸ And amber means exactly one thing anywhere in Handoff: waiting on you.

**Slide 6 — the decision.** One screen, one decision. Here's the email. Here's *why* it stopped, in the agent's own words: unknown vendor, strategic partnership, CEO intro call — I can't tell if this is a real lead or phishing. Forty percent sure, and it needs seventy to act alone. That gap is the product. I say "archive it, it's cold outreach." That phrase is matched locally — no model round-trip — and the run picks up exactly where it stopped.

**Slide 7 — it gets quieter.** My answer became a rule. Not a vague one: exact sender, whole domain, or two distinct keywords — one shared word is a coincidence, not a rule. Same inbox the next morning: seven handled, one from the rule, zero questions. It gets quieter the longer you use it.

**Slide 8 — Strands.** Every Strands feature the brief names is doing a real job. The Graph, because a workflow is a fixed, auditable sequence — a Swarm that takes a different path each morning is a bug when it's filing tickets in your name. The interrupt hook is the gate. The invocation hooks are the narrator that draws the graph. The session repository is why the terminal and the browser share one conversation. And two tools reach the page through a context variable, so a spoken sentence can end as an active workflow without anyone clicking Save.

**Slide 9 — AWS.** It's deployed. Bedrock Nova for reasoning, through cross-region profiles. AgentCore Runtime runs the graph as an arm64 container with a session per run. AgentCore Memory holds the learned rules. Transcribe and Polly are the voice. DynamoDB is one table. EventBridge can't invoke AgentCore directly, so a twelve-line Lambda forwards the tick. Every store also has a local JSON backend, so a fresh clone runs the entire loop offline.

**Slide 10 — three surfaces.** Talk, hands-free if you like, Ctrl-Space from anywhere. A native desktop window that records the microphone itself. And a CLI with every feature — run with `--watch` streams the same events into your terminal.

**Slide 11 — who it's for.** A consultant whose inbox is the business. An engineering lead who wants PR triage and blocked tickets in one morning memo. A founder who wants to know when a competitor's pricing moves — and nothing when it doesn't. Anyone with a chore on a schedule.

**Slide 12 — why not a chatbot.** A chatbot waits for you. Handoff runs when you're not there, with a written line it won't cross, an audit trail that says who decided what, and a memory that makes it ask less every week. The hard question for a background agent is *when may it act alone?* Everything here is one answer to that question — and the answer moves as it learns.

**Slide 13 — close.** It does the boring part. And it knows when to stop and ask. Thank you.

---

## Q&A crib

- *Cost?* A spoken set-up turn on Nova Lite is under a tenth of a cent; a full demo take on Nova Pro is cents. Transcribe is $0.024/min, Polly $16 per million characters.
- *What if the model is overconfident?* The prompts teach it not to inflate confidence to avoid asking; a malformed score fails toward asking, never toward acting; and the threshold is per workflow and per install.
- *Why not one agent?* Designing a workflow, running it, and learning from a decision need different context and fail differently. Three agents, one Graph.
- *Wake word?* Not in the browser — tap, hold Space, or hands-free. A native wake word is on the list.
