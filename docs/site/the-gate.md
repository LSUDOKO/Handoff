# The gate

A background agent has one hard question: when is it allowed to act without asking? Handoff answers it with a gate in front of the only tool that changes anything in the outside world, one number that says how sure the agent has to be, and a learning loop that moves the number's effect over time.

## Where it sits

The executor agent does its work through tools. Fetching mail and classifying it are free and reversible, so they are not gated. `submit_action` — the call that archives, files a ticket, drafts a reply — is the one chokepoint, and a hook on the Strands `BeforeToolCallEvent` sits in front of it.

Before, not after. The hook fires before the tool body runs. When the gate stops a call, nothing has happened to your mail. A gate that fires after the fact is an audit log, not a gate.

## What it decides

For each `submit_action` call the gate looks at three things, in order:

1. **Your rules first.** If a rule you taught it covers this item, the call is rewritten to the action you chose last time and stamped as decided by memory. There is nothing to ask.
2. **Irreversible tools always ask.** Deleting, sending mail, posting publicly — these are gated regardless of confidence. Confidence is not the right control for "cannot be undone".
3. **Otherwise, confidence.** The model reports how sure it is, from 0 to 1. Below the threshold, or when the model itself flags the item with `force_interrupt`, the gate stops and asks. A malformed score counts as zero — failing toward asking, never toward acting.

The executor's instructions are explicit that inflating confidence to avoid interruption and deflating it to avoid responsibility are both failure modes, and that its reasoning is shown to you verbatim when it escalates. That is why a decision card reads like *"unknown vendor pitching a strategic partnership; I can't tell if this is a legitimate lead or phishing"* rather than *"this is ambiguous"*.

## One pass, one screen

An unsure item does not freeze the run. The gate **defers** it: the payload is set aside in the run context, the tool body does nothing to that item, and the executor keeps going through the rest of the batch. When the pass is complete the executor calls `finish_batch`, and that hook raises a single interrupt carrying every deferred item.

So you get one screen with every question from the run — each item its own decision, "and 2 more after this" — instead of one interruption per question. On a real model: eight messages, seven handled alone, one escalated, one interrupt.

The suspension is a Strands interrupt. The agent's message history, its partial reasoning and the rest of its context are serialised with the graph state and stored on the run, so a run paused at 08:04 and answered at 11:30 is the same run, even across a restart of the process.

## Answering

A waiting decision is amber everywhere it appears — the sidebar badge, the Activity page, the overview, the Talk page. Answer it wherever you are:

- **Activity** lists pending decisions across workspaces, answerable inline with a note.
- **The decision screen** (`/decide/<id>`) is one item full-screen: the email, the agent's reasoning, the confidence gauge against the threshold, the options.
- **Chat** surfaces a decision from a run it started as a card in the conversation.
- **Talk** reads it aloud and takes your answer by voice: *archive it*, *file a ticket*, *draft a reply*, *leave it*.
- **The terminal:** `handoff pending` lists them; `handoff decide <interrupt_id> <action> --note "why"` answers one.

The options are what the workflow's `human_gate` step lists — typically `file_ticket`, `archive`, `draft_reply` and `skip`. Choosing the agent's suggestion is `approve_suggested`. Choosing `skip` cancels the tool rather than running it with a no-op argument, so the audit trail records *declined*, not *did nothing*.

Answering resumes the run. The gate rewrites the pending call to the action you chose, with confidence forced to 1.0 and `decided_by` stamped `human`, and the tool carries it out.

## What it learns

Every answer wakes the Learning Agent, whose only job is to write one narrow rule from one decision. A rule has a pattern you would recognise as your own decision, a match — an exact sender, a whole domain like `@vendor.com`, or a set of distinctive keywords — an action, and a confidence.

The restraint is the point. A rule that fires too eagerly takes actions nobody sanctioned, which is worse than one extra question. So a stored rule fires only on an exact sender match, a whole domain, or **at least two distinct keyword hits** — one shared word is a coincidence. The note you leave when answering is the strongest signal the learner has: it is you telling it the reason directly.

Rules are applied *before* the gate decides, so the next run does not re-ask. The dashboard counts these separately — *handled from rules you set* is a different number from *always confident about* — so you can see the interruptions that did not happen.

See what it is acting on under **Memory** in the sidebar, or:

```bash
handoff rules
```

Read that list after the first week. The failure mode to watch for is not the agent acting wrongly on an item it asked about; it is a learned rule that is too broad quietly handling things you would have wanted to see.

## Tuning

One number decides how much it bothers you:

```bash
CONFIDENCE_THRESHOLD=0.7
```

- **Raise it** (0.8) to be asked more often. Sensible for the first week, while you decide whether you trust it.
- **Lower it** (0.6) once the rules have built up and the questions feel obvious.

The Settings page changes it without editing a file. A workflow can override it with its own `confidence_threshold` — the PR review template uses 0.8 because leaving a review comment in your name deserves more caution than archiving a newsletter; the competitor watch uses 0.75.

Two settings decide how you hear about a waiting decision: `NOTIFY_CHANNEL` (`console`, `slack` or `sns`) and `UI_BASE_URL`, which builds the deep link in the notification.

## The safety property

The gate fires before the tool runs, so an escalated item has had nothing done to it, whichever credentials are live. Every fallback in the system degrades the *quality* of the work — does less, or does it worse — and never its *safety*: an unreachable human channel means the item is skipped, not decided.
