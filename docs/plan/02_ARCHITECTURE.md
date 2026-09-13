# Handoff — Technical Architecture

## System Architecture (ASCII — also create a visual diagram for submission)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER LAYER                                      │
│                                                                         │
│   ┌──────────────────┐          ┌──────────────────────────────┐        │
│   │  Chat Interface  │          │  Decision Screen (HTMX)      │        │
│   │  (FastAPI+HTMX)  │          │  Approve / Edit / Decline    │        │
│   │  "describe task"  │          │  (one-screen, one decision)  │        │
│   └────────┬─────────┘          └──────────────┬───────────────┘        │
│            │ natural language                   │ user decision          │
└────────────┼────────────────────────────────────┼───────────────────────┘
             │                                    │
             ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      AGENT LAYER (Strands SDK)                          │
│                                                                         │
│   ┌──────────────────┐                                                  │
│   │  BUILDER AGENT   │  Interprets user request → selects MCP tools     │
│   │  (conversational)│  → generates workflow config → validates         │
│   └────────┬─────────┘                                                  │
│            │ workflow config (JSON)                                      │
│            ▼                                                            │
│   ┌──────────────────────────────────────────────────────────┐          │
│   │  WORKFLOW GRAPH (Strands Graph — generated per workflow)  │          │
│   │                                                           │          │
│   │  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌───────────┐ │          │
│   │  │TRIGGER  │─▶│EXECUTOR  │─▶│DECISION │─▶│ COMPLETER │ │          │
│   │  │node     │  │node(s)   │  │GATE     │  │ node      │ │          │
│   │  │(cron/   │  │(tool     │  │(HITL    │  │(finalize  │ │          │
│   │  │webhook/ │  │calls)    │  │interrupt│  │+ notify)  │ │          │
│   │  │event)   │  │          │  │)        │  │           │ │          │
│   │  └─────────┘  └──────────┘  └─────────┘  └───────────┘ │          │
│   └──────────────────────────────────────────────────────────┘          │
│                                                                         │
│   ┌──────────────────┐                                                  │
│   │  LEARNING AGENT  │  Post-decision: updates Memory with              │
│   │  (background)    │  user preferences for future runs                │
│   └──────────────────┘                                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
             │                    │                    │
             ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     TOOL LAYER                                          │
│                                                                         │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│   │ Gmail MCP  │  │ Linear MCP │  │ Slack MCP  │  │ Custom     │      │
│   │ Server     │  │ Server     │  │ Server     │  │ @tool      │      │
│   └────────────┘  └────────────┘  └────────────┘  └────────────┘      │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐                      │
│   │ AgentCore  │  │ AgentCore  │  │ AgentCore  │                      │
│   │ Browser    │  │ Code Interp│  │ Gateway    │                      │
│   └────────────┘  └────────────┘  └────────────┘                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
             │                    │                    │
             ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     AWS INFRA LAYER                                      │
│                                                                         │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│   │ AgentCore  │  │ AgentCore  │  │ Bedrock    │  │ CloudWatch │      │
│   │ Runtime    │  │ Memory     │  │ (Claude/   │  │ (OTEL      │      │
│   │ (serverless│  │ (short+    │  │  Nova)     │  │  traces)   │      │
│   │  background│  │  long-term)│  │            │  │            │      │
│   │  execution)│  │            │  │            │  │            │      │
│   └────────────┘  └────────────┘  └────────────┘  └────────────┘      │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐                      │
│   │ AgentCore  │  │ DynamoDB   │  │ SNS / SES  │                      │
│   │ Identity   │  │ (workflows │  │ (notifi-   │                      │
│   │ (Cognito)  │  │  + audit)  │  │  cations)  │                      │
│   └────────────┘  └────────────┘  └────────────┘                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Three-Agent Architecture

Handoff uses THREE distinct Strands agents, each with a clear role:

### Agent 1: Builder Agent (conversational, interactive)
- **Role:** Interprets the user's natural-language description and builds a workflow config.
- **Type:** Conversational Strands Agent with system prompt + tools.
- **Tools:** `discover_mcp_tools` (lists available MCP servers), `validate_workflow` (checks the config is executable), `preview_workflow` (shows the user what will happen).
- **When it runs:** During the "describe" phase, in response to user chat.
- **Output:** A validated workflow config (JSON) specifying: trigger (cron/webhook/event), executor steps (which tools to call in what order), decision gate rules (what's ambiguous), and completion actions.

### Agent 2: Workflow Executor (autonomous, background — this is the main agent)
- **Role:** Runs the generated workflow autonomously on its trigger signal.
- **Type:** Strands Graph with dynamically-wired nodes based on the workflow config.
- **Nodes:**
  - **Trigger Node** — fires on cron/webhook/event signal.
  - **Executor Node(s)** — calls MCP tools (Gmail, Linear, Slack, Browser, etc.) to do the actual work.
  - **Decision Gate Node** — evaluates each result against the workflow's ambiguity rules. Clear cases → auto-act. Ambiguous cases → `event.interrupt()` → human decision.
  - **Completer Node** — finalizes actions post-decision, writes audit log, sends completion notification.
- **When it runs:** On schedule (AgentCore Runtime, background/async).
- **The interrupt gate lives HERE.** This is the centerpiece.

### Agent 3: Learning Agent (background, post-decision)
- **Role:** After each human decision, updates AgentCore Memory so the Workflow Executor handles similar cases automatically next time.
- **Type:** Simple Strands Agent with Memory tools.
- **When it runs:** After every `interrupt` → decision cycle.
- **Why it matters:** It's the "gets smarter" narrative — judges love this, and it's a real use of AgentCore Memory.

## Why Graph, Not Swarm
The workflow is a **deterministic sequence**: trigger → execute steps → check for ambiguity → gate → complete. This is a fixed directed flow — exactly what Strands `Graph` is for. Swarm is for collaborative, free-form multi-agent conversations; using it here would be architecturally wrong and the judges would notice. **Say this in the demo and builder post — it signals real understanding.**

## Data Flow for the Demo Use Case (Inbox Triage)

```
8:00 AM cron fires
        │
        ▼
Trigger Node activates
        │
        ▼
Executor Node 1: Gmail MCP → fetch unread emails (last 12h)
        │
        ▼
Executor Node 2: LLM classifies each email
        │  ├─ "teammate request"  → Linear MCP → create ticket (auto)
        │  ├─ "newsletter"        → Gmail MCP → archive (auto)
        │  ├─ "from manager"      → Gmail MCP → draft reply (auto)
        │  └─ "ambiguous"         → DECISION GATE
        │
        ▼
Decision Gate: event.interrupt()
        │  payload: { email_summary, sender, suggested_action, options }
        │  → surfaces to user via notification + decision UI
        │
        ▼ (user approves/edits/declines)
        │
Completer Node: execute chosen action + write audit log
        │
        ▼
Learning Agent: store decision in Memory for next run
```

## Workflow Config Schema (what the Builder Agent generates)

```json
{
  "workflow_id": "inbox-triage-morning",
  "name": "Morning Inbox Triage",
  "description": "Triage unread emails, file tickets, archive newsletters",
  "trigger": {
    "type": "cron",
    "schedule": "0 8 * * 1-5",
    "timezone": "America/New_York"
  },
  "mcp_tools": ["gmail", "linear", "slack"],
  "steps": [
    {
      "id": "fetch_emails",
      "action": "gmail.search_threads",
      "params": { "query": "is:unread newer_than:12h" }
    },
    {
      "id": "classify",
      "action": "llm_classify",
      "input_from": "fetch_emails",
      "categories": ["teammate_request", "newsletter", "manager", "ambiguous"]
    },
    {
      "id": "auto_actions",
      "rules": [
        { "category": "teammate_request", "action": "linear.create_issue", "auto": true },
        { "category": "newsletter", "action": "gmail.archive", "auto": true },
        { "category": "manager", "action": "gmail.create_draft", "auto": true }
      ]
    },
    {
      "id": "human_gate",
      "category": "ambiguous",
      "action": "interrupt",
      "present": ["email_summary", "sender", "suggested_action"],
      "options": ["file_ticket", "archive", "reply", "skip"]
    }
  ],
  "completion": {
    "notify": "slack",
    "channel": "#daily-triage",
    "message": "Morning triage complete. {auto_count} handled, {interrupt_count} decided."
  },
  "memory": {
    "learn_from_decisions": true,
    "preference_key": "inbox_triage_rules"
  }
}
```

## AWS Services Used (comprehensive)

| Service | Purpose |
|---|---|
| Amazon Bedrock (Claude Sonnet / Nova) | LLM for all three agents |
| AgentCore Runtime | Serverless background execution of workflow agent |
| AgentCore Memory | Short-term (session) + long-term (user preferences, learned rules) |
| AgentCore Browser | For workflows that need web interaction (competitor monitoring) |
| AgentCore Code Interpreter | For data processing steps (CSV analysis, report generation) |
| AgentCore Gateway | Expose Lambda/API tools to agents |
| AgentCore Identity | Cognito/OAuth for user auth + MCP service connections |
| AgentCore Observability | OTEL → CloudWatch traces (show in demo) |
| DynamoDB | Workflow configs, execution audit log |
| SNS / SES | Notifications to user (decision needed, workflow complete) |
| EventBridge | Cron trigger for scheduled workflows |
| ECR | Docker image for AgentCore Runtime deploy |

## Key Design Decisions (mention in demo + builder post)

1. **Graph over Swarm** — deterministic, auditable workflow execution.
2. **Three agents, not one** — separation of concerns: building ≠ executing ≠ learning.
3. **Interrupt gate on ambiguity, not on everything** — the agent handles clear cases silently; only genuinely ambiguous items surface. This is the hackathon's core requirement.
4. **Memory as a learning loop** — human decisions feed back into the agent's behavior. The agent improves with use.
5. **MCP-first tool integration** — tools are MCP servers, not hardcoded functions. This makes workflows portable and extensible.
