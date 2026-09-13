# Handoff — Project Overview

## One-Line Pitch
**Describe a repetitive task in chat. Handoff builds it into an autonomous workflow that runs on schedule and only pings you when there's a real decision to make.**

## Name: Handoff
*"You describe it. You hand it off. It runs."*

## Hackathon
- **Event:** Agents for Humans Hackathon (AWS · Devpost)
- **Track:** Professional Agents
- **Prize pool:** $40,000 across three tracks + $10,000 Grand Prize
- **Deadline:** Sep 14, 2026, 5:00pm PDT
- **SDK:** Strands Agents SDK (required)
- **Deploy:** Amazon Bedrock AgentCore (strengthens Technical Implementation score)
- **License:** Apache-2.0 (required, visible in repo About section)

## The Problem
Professionals lose hours every day to small, repetitive tasks — triaging email, filing tickets, sending follow-ups, compiling reports, checking dashboards. Each one is too small to justify building a dedicated tool, but together they drain real time and attention. The typical solution — another app to open and manage — just adds overhead.

## Who It's For
Developers, operators, founders, and small-team professionals who do the same 5–10 background tasks every day/week and want them handled autonomously without building custom integrations from scratch.

## How It Works (The Core Loop)
1. **Describe** — The user types a natural-language description of what they want automated: *"Every weekday at 8am, triage my inbox. Real asks → file as Linear tickets. Newsletters → archive. Anything ambiguous → ask me."*
2. **Build** — Handoff's Builder Agent interprets the request, selects the right MCP tools, and assembles a Strands Graph workflow with the right nodes, triggers, and decision gates.
3. **Run** — The workflow deploys on AgentCore Runtime as a scheduled/async background job. It runs autonomously on the configured signal (cron, webhook, event).
4. **Decide** — When the agent hits a genuinely ambiguous or high-stakes moment, it fires `event.interrupt()` and surfaces a one-screen decision to the user. Nothing irreversible happens without human approval.
5. **Learn** — AgentCore Memory stores the user's decisions, so next time the agent handles similar cases without asking.

## The Golden Rule (from the hackathon brief)
> "Instead of another app people open and manage, the agent runs autonomously and only surfaces when there's a real decision to make."

Handoff IS this sentence, implemented as a product.

## Why It Wins

### vs. Single-purpose agents (ClauseGuard, RenewGuard, DenialDefender)
Handoff is **reusable** — judges see it applied to inbox triage in the demo but understand it works for any repetitive professional task. Bigger potential impact, bigger creativity score.

### vs. Generic platforms (Friday, n8n, Zapier)
Handoff is **purpose-built on Strands** — not a framework swap. Every Strands feature (Graph, interrupt, MCP, Memory, AgentCore) is a first-class citizen, not bolted on. And it has a specific demo use case, not a vague "platform" pitch.

### vs. Fork-and-swap approaches
Handoff is **built from scratch** on the official AWS starter. Full originality credit, clean Apache-2.0 license, unambiguous "new agent built with Strands."

## Judging Criteria Alignment

| Criterion | How Handoff scores |
|---|---|
| **Technological Implementation** | Uses EVERY major Strands feature: Graph, interrupt/HITL, MCP, Memory, @tool, hooks. Deployed on AgentCore Runtime with Memory, Browser, Code Interpreter, Gateway, Identity, Observability. Live demo link. Non-trivial multi-agent build. |
| **Design** | Complete product: chat-based workflow builder → generated workflow config → background execution → decision UI → audit trail. Not a proof of concept. |
| **Potential Impact** | Applies to any professional's repetitive tasks. Demo with inbox triage is relatable to every judge. Reusable = massive reach. |
| **Creativity & Originality** | "Chat → repeatable autonomous workflow with a human gate" is a novel application of Strands. No existing Strands project does this. Deep understanding of when agents should and shouldn't act. |
| **Presentation** | Crisp demo: type a sentence → watch it build → watch it run → see the interrupt → approve → done. Clear problem/who/why. |

## Demo Use Case (The One to Build and Show)
**Professional Inbox Triage + Ticket Filing**
- *"Every weekday at 8am, triage my inbox. Real asks from teammates → file as Linear tickets tagged 'inbox'. Newsletters → archive. Anything from my manager → draft a reply. Anything ambiguous → ask me."*
- This is the demo because: everyone has email, every judge understands it, it's visibly autonomous, the interrupt moment is obvious and relatable, and it shows MCP tools (Gmail, Linear, Slack) working together.

## Second Demo Use Case (show in video if time permits)
**Weekly Competitor Monitor**
- *"Every Monday, check competitor X's pricing page. If anything changed, summarize the diff and post to #competitive-intel in Slack."*
- Shows AgentCore Browser + cron trigger + a different workflow shape.
