# Handoff — Demo Video Script + builder.aws.com Post

---

## Part 1: Demo Video (≤5 minutes)

### Storyboard

#### 0:00–0:40 — THE PROBLEM
**Voiceover:** "Every day, professionals lose hours to the same small tasks — triaging email, filing tickets, sending follow-ups. Each one takes a few minutes, but together they drain real time and attention."

**On screen:** Quick montage of inbox, ticket boards, Slack channels — the daily grind.

**Voiceover:** "The usual fix — another app to manage — just adds overhead. What if you could describe the task once, hand it off, and it just runs?"

#### 0:40–1:10 — INTRODUCE HANDOFF
**Voiceover:** "Meet Handoff. You describe a repetitive task in plain language. Handoff builds it into an autonomous workflow that runs on schedule — and only pings you when there's a real decision to make."

**On screen:** Show the Handoff dashboard. Clean, professional, dark theme.

#### 1:10–2:00 — BUILD A WORKFLOW (Chat)
**Voiceover:** "Let me show you. I open the chat and type..."

**On screen:** Type into the chat interface:
> "Every weekday at 8am, triage my inbox. Real asks from teammates → file as Linear tickets. Newsletters → archive. Anything from my manager → draft a reply. Anything ambiguous → ask me."

**Voiceover:** "The Builder Agent interprets this, selects the right MCP tools — Gmail, Linear, Slack — and generates a workflow."

**On screen:** Show the Builder Agent responding with the workflow config preview.

**Voiceover:** "One conversation. The workflow is ready."

#### 2:00–3:30 — WATCH IT RUN (Autonomous Execution)
**Voiceover:** "Now let's trigger it. The workflow runs in the background on AgentCore Runtime."

**On screen:** Click "Run Now" on the dashboard. Show the trace viewer:

**Voiceover (narrate each step):**
- "It fetches 8 unread emails..."
- "Classifies each one using its judgment..."
- "Alice's API review request — clear teammate ask, confidence 95% — auto-files a Linear ticket."
- "TechCrunch newsletter — obvious, 99% confidence — auto-archived."
- "Manager's sync request — drafts a reply automatically."
- "Bob's sprint retro — another teammate ask — auto-filed."
- "GitHub security alert — auto-filed as a ticket."

**On screen:** Show the trace: 5 items handled autonomously, green checkmarks. The agent is working.

**Voiceover:** "Five items handled. Zero interruptions. The agent just did five minutes of work in seconds."

#### 3:30–4:30 — THE MONEY MOMENT (Human Decision) ⭐
**Voiceover:** "But then it hits an email from an unknown vendor — 'Partnership opportunity.' The agent isn't sure. Is this spam, or a real business lead?"

**On screen:** Trace shows a yellow "⏸️ Paused" indicator. Notification pops up:
> "🔔 Handoff needs your input"

**Voiceover:** "The agent pauses. It fires an interrupt and surfaces ONE decision."

**On screen:** Click through to the Decision Screen. Show:
- Email summary
- Agent's reasoning: "Unknown sender, could be spam or a legitimate business inquiry. Confidence: 30%."
- Confidence bar (low, visual)
- Action buttons: [Archive] [Reply] [File Ticket] [Skip]

**Voiceover:** "One screen. One decision. I click Archive."

**On screen:** Click "Archive." Screen shows ✅ "Decision applied. Workflow resumed."

**Voiceover:** "The agent archives it, logs my decision, and — here's the key — it learns. Next time it sees email from this vendor, it archives automatically. No interruption."

#### 4:30–4:50 — WHY IT MATTERS
**Voiceover:** "Handoff uses every major feature of the Strands Agents SDK: Graph orchestration for deterministic workflows, the interrupt gate for human-in-the-loop decisions, MCP for tool integration, AgentCore Memory for learning, and it's deployed on AgentCore Runtime as a serverless background job."

**On screen:** Quick flash of the architecture diagram.

**Voiceover:** "It's not another app to manage. You describe it once. You hand it off. It runs."

#### 4:50–5:00 — CLOSE
**On screen:** Handoff logo + tagline + repo URL + live demo link.

**Voiceover:** "Handoff. Built with Strands Agents SDK for the Agents for Humans hackathon. Professional Agents track. Thank you."

---

### Video Production Tips
- **Screen recording:** OBS Studio (free) or Loom.
- **Voiceover:** Record separately in a quiet room; edit over screen capture.
- **No face cam needed** — the hackathon explicitly says so.
- **Resolution:** 1080p minimum.
- **Pacing:** don't rush the Decision Screen moment — that's the payoff.
- **Show the trace:** the observability trace is proof the agent is real, not scripted. Pause on it for 2-3 seconds.
- **Narrate problem/who/why explicitly** — these are the three required beats.

---

## Part 2: builder.aws.com Post (Bonus Points)

### Title (must contain "Agents for Humans")
**"Agents for Humans: Building Handoff — An Autonomous Workflow Agent with Strands and AgentCore"**

### Outline

#### Section 1: The Problem I Wanted to Solve
- Professionals lose hours to repetitive background tasks
- The "another app to manage" trap
- What if you could describe a task once and it ran forever?

#### Section 2: Why Strands Agents SDK
- Model-driven: model + system prompt + tools = agent
- The Graph pattern for deterministic, auditable workflows
- Why I chose Graph over Swarm (auditability in professional contexts)
- Native MCP support for tool integration

#### Section 3: The Architecture
- Three agents: Builder, Executor, Learner
- The interrupt gate as the centerpiece (with code snippet)
- How `event.interrupt()` works in practice
- The learning loop: human decisions feed back into Memory

#### Section 4: Building on AgentCore
- Runtime: serverless background execution
- Memory: learning user preferences across runs
- Observability: OTEL traces that prove the agent is reasoning
- What each AgentCore service gave me that I'd have had to build from scratch

#### Section 5: The Demo Use Case — Inbox Triage
- Why email triage is the perfect demo
- Mock data design: why I included ambiguous cases
- The "5 auto, 3 interrupted" ratio

#### Section 6: What Broke and How I Fixed It
- Be honest about a real challenge
- e.g., "The interrupt resume flow was trickier than expected because..."
- e.g., "AgentCore Memory's semantic strategy needed careful key design..."

#### Section 7: What I'd Build Next
- More workflow templates (PR review, competitor monitoring, report generation)
- Multi-user support (team workflows)
- Workflow marketplace (share and discover)

### Post Tips
- Include code snippets (especially the interrupt gate hook)
- Include the architecture diagram
- Include a screenshot of the Decision Screen
- Link to the repo
- Publish BEFORE the deadline
- You can submit more than one post

---

## Part 3: Devpost Submission Text

### Title
**Handoff — Describe It. Hand It Off. It Runs.**

### Tagline
An autonomous workflow agent that turns natural-language descriptions into repeatable background workflows, powered by Strands Agents SDK.

### Inspiration
Every day, professionals lose hours to repetitive tasks that are too small to justify a custom tool but too numerous to ignore. We wanted to build an agent that handles these tasks in the background — not as another app to manage, but as a quiet worker that only interrupts when there's a genuinely ambiguous decision.

### What it does
Handoff lets you describe any repetitive professional task in plain language. It builds a workflow, runs it autonomously on schedule, and only surfaces when it encounters something genuinely ambiguous that needs your judgment. After you decide, it learns your preference so it handles similar cases automatically next time.

### How we built it
Built with the Strands Agents SDK using three coordinated agents (Builder, Executor, Learner) orchestrated as a Strands Graph. The human-in-the-loop interrupt gate uses `BeforeToolCallEvent` hooks to pause the agent loop at decision points. Deployed on Amazon Bedrock AgentCore Runtime with Memory for learning, Browser for web workflows, and full OpenTelemetry observability.

### Challenges we ran into
[Fill in honestly during the build — authenticity matters]

### Accomplishments that we're proud of
The interrupt gate — the agent handles clear cases silently and only surfaces genuinely ambiguous items. In the demo, 5 out of 8 emails are handled autonomously; only 3 trigger a human decision. That selectivity is the whole point.

### What we learned
[Fill in during the build]

### What's next for Handoff
Workflow templates for common use cases (PR review, competitor monitoring, weekly reports), multi-user team workflows, and a workflow marketplace.

### Built With
- Strands Agents SDK
- Amazon Bedrock (Claude Sonnet)
- Amazon Bedrock AgentCore (Runtime, Memory, Browser, Gateway, Identity)
- FastAPI + HTMX
- DynamoDB
- MCP (Model Context Protocol)
- Python
