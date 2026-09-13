# Handoff — Implementation Plan (Phase-by-Phase)

## Repo Structure

```
handoff/
├── README.md                          # required deliverable
├── LICENSE                            # Apache-2.0 (required)
├── ARCHITECTURE.md                    # architecture write-up + diagram embed
├── pyproject.toml
├── requirements.txt
├── .env.example                       # never commit real secrets
├── Dockerfile                         # ARM64 for AgentCore Runtime
├── docker-compose.yml                 # local dev (optional)
│
├── docs/
│   ├── architecture.png               # visual diagram (required)
│   ├── architecture.excalidraw        # source for diagram
│   └── demo-script.md                 # storyboard for ≤5 min video
│
├── src/
│   └── handoff/
│       ├── __init__.py
│       ├── app.py                     # AgentCore entrypoint (BedrockAgentCoreApp)
│       ├── config.py                  # settings, model IDs, region, env vars
│       ├── models.py                  # pydantic data models (workflow config, etc.)
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── builder.py             # Builder Agent (chat → workflow config)
│       │   ├── executor.py            # Workflow Executor (Graph, runs autonomously)
│       │   └── learner.py             # Learning Agent (post-decision → Memory)
│       │
│       ├── graph/
│       │   ├── __init__.py
│       │   ├── factory.py             # Builds a Strands Graph from workflow config
│       │   ├── nodes/
│       │   │   ├── __init__.py
│       │   │   ├── trigger.py         # Trigger node (cron/webhook/event)
│       │   │   ├── executor.py        # Executor node (calls MCP tools)
│       │   │   ├── classifier.py      # Classifies results (auto vs ambiguous)
│       │   │   ├── gate.py            # Decision gate (event.interrupt)
│       │   │   └── completer.py       # Finalizes + audit log + notify
│       │   └── hooks/
│       │       ├── __init__.py
│       │       └── hitl.py            # BeforeToolCallEvent → interrupt gate
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── workflow_store.py      # Save/load workflow configs (DynamoDB)
│       │   ├── audit_log.py           # Write execution audit entries
│       │   ├── mcp_discovery.py       # Discover available MCP tools
│       │   ├── notify.py              # SNS/SES/Slack notification
│       │   └── scheduler.py           # EventBridge cron management
│       │
│       ├── memory/
│       │   ├── __init__.py
│       │   └── store.py               # AgentCore Memory read/write
│       │
│       └── mcp/
│           ├── __init__.py
│           └── servers.py             # MCP server registry + connection
│
├── ui/
│   ├── server.py                      # FastAPI app (chat + decision screen)
│   ├── static/
│   │   └── styles.css
│   └── templates/
│       ├── chat.html                  # Chat interface (workflow builder)
│       ├── decision.html              # Approve / Edit / Decline screen
│       ├── dashboard.html             # Workflow list + status + audit log
│       └── trace.html                 # Observability trace viewer
│
├── workflows/
│   └── examples/
│       ├── inbox_triage.json          # Pre-built demo workflow config
│       └── competitor_monitor.json    # Second demo workflow config
│
├── infra/
│   ├── deploy_agentcore.py            # AgentCore deploy script
│   ├── dynamodb_setup.py              # Create tables
│   └── eventbridge_setup.py           # Create cron rules
│
├── tests/
│   ├── test_builder_agent.py          # Builder generates valid workflow config
│   ├── test_graph_factory.py          # Graph builds correctly from config
│   ├── test_hitl_gate.py              # Interrupt fires before irreversible actions
│   ├── test_classifier.py             # Classification accuracy
│   ├── test_learner.py                # Memory updates correctly
│   └── test_e2e.py                    # Full loop with mock MCP tools
│
└── scripts/
    ├── seed_workflows.py              # Load example workflow configs
    └── run_local.py                   # Local dev runner (no AgentCore)
```

---

## Phase 0 — Environment Setup (Day 1 morning)

### 0.1 Accounts & access
- [ ] AWS account with Bedrock model access enabled (Claude Sonnet + Nova).
- [ ] AWS Builder ID created (required for submission).
- [ ] $50 AWS credit request submitted (Resources tab).
- [ ] IAM role with: Bedrock, AgentCore, DynamoDB, SNS/SES, CloudWatch, ECR, EventBridge.
- [ ] Region chosen (e.g. `us-east-1` — verify AgentCore availability).

### 0.2 Local dev
```bash
# Python environment
python3.12 -m venv .venv
source .venv/bin/activate

# Core dependencies
pip install strands-agents strands-agents-tools
pip install fastapi uvicorn jinja2 python-multipart httpx
pip install boto3 pydantic python-dotenv
pip install bedrock-agentcore  # confirm package name at build time

# Dev dependencies
pip install pytest pytest-asyncio ruff

# AWS
aws configure  # set region, credentials
```

### 0.3 Verify Strands works
```python
# quick_test.py
from strands import Agent
from strands.models.bedrock import BedrockModel

model = BedrockModel(model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0")
agent = Agent(model=model, system_prompt="You are a helpful assistant.")
response = agent("Say hello in one sentence.")
print(response)
```

---

## Phase 1 — The Interrupt Gate + Minimal Graph (Days 1–3) ⭐ HIGHEST PRIORITY

**Goal:** A hardcoded inbox-triage Graph that runs, classifies mock emails, and fires `event.interrupt()` on ambiguous ones. This is the spine of the whole project — get it working first.

### 1.1 Data models (`models.py`)

```python
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional

class TriggerType(str, Enum):
    CRON = "cron"
    WEBHOOK = "webhook"
    MANUAL = "manual"

class WorkflowStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DRAFT = "draft"

class EmailCategory(str, Enum):
    TEAMMATE_REQUEST = "teammate_request"
    NEWSLETTER = "newsletter"
    MANAGER = "manager"
    AMBIGUOUS = "ambiguous"

class ClassifiedEmail(BaseModel):
    email_id: str
    sender: str
    subject: str
    snippet: str
    category: EmailCategory
    confidence: float
    suggested_action: str
    reasoning: str

class InterruptPayload(BaseModel):
    workflow_id: str
    run_id: str
    item: ClassifiedEmail
    options: list[str]
    context: str
    timestamp: datetime

class UserDecision(BaseModel):
    interrupt_id: str
    chosen_action: str
    user_note: str = ""
    timestamp: datetime

class WorkflowConfig(BaseModel):
    workflow_id: str
    name: str
    description: str
    trigger: dict
    mcp_tools: list[str]
    steps: list[dict]
    completion: dict
    memory: dict

class AuditEntry(BaseModel):
    run_id: str
    workflow_id: str
    timestamp: datetime
    action: str
    item_id: str
    decision_by: str  # "agent" or "human"
    details: dict
```

### 1.2 The interrupt gate (`graph/hooks/hitl.py`)

```python
from strands.hooks import BeforeToolCallEvent
import json

# Tools that require human approval before execution
GATED_TOOLS = {
    "submit_action",      # any irreversible action
    "send_message",       # sending emails/messages
    "create_ticket",      # when confidence is low
    "delete_item",        # destructive actions
}

def register_hitl_gate(agent):
    """Register the human-in-the-loop interrupt gate.
    
    This is the CENTERPIECE of Handoff. Before any gated tool runs,
    the agent pauses and hands control to a human.
    """
    
    @agent.hooks.add(BeforeToolCallEvent)
    def decision_gate(event: BeforeToolCallEvent):
        tool_name = event.tool_use.get("name", "")
        tool_input = event.tool_use.get("input", {})
        
        # Check if this tool requires human approval
        requires_gate = (
            tool_name in GATED_TOOLS
            or tool_input.get("confidence", 1.0) < 0.7
            or tool_input.get("force_interrupt", False)
        )
        
        if requires_gate:
            payload = {
                "interrupt_type": "decision_required",
                "tool": tool_name,
                "item_summary": tool_input.get("summary", ""),
                "suggested_action": tool_input.get("action", ""),
                "options": tool_input.get("options", ["approve", "skip"]),
                "reasoning": tool_input.get("reasoning", ""),
                "confidence": tool_input.get("confidence", 0.0),
            }
            
            # THIS IS THE KEY LINE — pause the agent loop
            event.interrupt(
                reason="human_approval_required",
                data=payload
            )
```

### 1.3 Graph nodes (`graph/nodes/`)

**Trigger node (`trigger.py`):**
```python
from strands import tool

@tool
def check_trigger(trigger_type: str, config: dict) -> dict:
    """Check if the workflow trigger condition is met.
    
    For cron: always returns True (cron already fired to start this).
    For webhook: validates the incoming payload.
    For manual: always returns True.
    """
    return {
        "triggered": True,
        "trigger_type": trigger_type,
        "timestamp": datetime.now().isoformat()
    }
```

**Executor node — fetch emails (`executor.py`):**
```python
from strands import tool

@tool
def fetch_unread_emails(query: str = "is:unread newer_than:12h", 
                         max_results: int = 20) -> list[dict]:
    """Fetch unread emails from Gmail via MCP.
    
    In MVP: returns mock emails for demo.
    In production: calls Gmail MCP server.
    """
    # MVP: mock data for reliable demo
    mock_emails = [
        {
            "email_id": "msg_001",
            "sender": "alice@team.com",
            "subject": "Need API review by Thursday",
            "snippet": "Can you review the payments API PR? Blocking release.",
            "labels": ["team"]
        },
        {
            "email_id": "msg_002", 
            "sender": "newsletter@techcrunch.com",
            "subject": "TC Daily: AI Agents Are Eating Software",
            "snippet": "Today's top stories in tech...",
            "labels": ["newsletter"]
        },
        {
            "email_id": "msg_003",
            "sender": "boss@company.com",
            "subject": "Quick sync on Q3 targets",
            "snippet": "Let's discuss the pipeline numbers. Free at 2pm?",
            "labels": ["manager"]
        },
        {
            "email_id": "msg_004",
            "sender": "unknown@vendor.com",
            "subject": "Partnership opportunity - urgent",
            "snippet": "We'd love to explore a strategic partnership...",
            "labels": []
        },
        {
            "email_id": "msg_005",
            "sender": "hr@company.com",
            "subject": "Updated PTO policy — action may be required",
            "snippet": "Please review the new policy. Some changes affect your team.",
            "labels": ["internal"]
        }
    ]
    return mock_emails
```

**Classifier node (`classifier.py`):**
```python
from strands import tool

@tool
def classify_email(email: dict, rules: dict = None) -> dict:
    """Classify an email into a category using LLM reasoning.
    
    Returns the email with category, confidence, and suggested action.
    The agent uses its judgment here — this is where the LLM earns its keep.
    
    Categories:
    - teammate_request: clear ask from a known teammate → file ticket
    - newsletter: marketing/newsletter content → archive
    - manager: from direct manager → draft reply
    - ambiguous: unclear intent or unknown sender → human decision
    """
    # The LLM (via the agent's system prompt) will classify based on:
    # - sender (known team? manager? unknown?)
    # - subject line signals
    # - content analysis
    # - user's learned preferences from Memory
    
    # Return structure (the agent fills this based on reasoning):
    return {
        "email_id": email["email_id"],
        "sender": email["sender"],
        "subject": email["subject"],
        "snippet": email["snippet"],
        "category": "determined_by_agent",
        "confidence": 0.0,  # 0-1, agent estimates
        "suggested_action": "determined_by_agent",
        "reasoning": "agent explains why"
    }
```

**Decision gate node (`gate.py`):**
```python
from strands import tool

@tool
def submit_action(action: str, item_id: str, summary: str,
                   confidence: float, reasoning: str,
                   options: list[str] = None,
                   force_interrupt: bool = False) -> dict:
    """Execute an action on a classified item.
    
    IMPORTANT: This tool is GATED by the HITL interrupt hook.
    If confidence < 0.7 or force_interrupt=True, the agent loop
    will pause here and wait for human approval.
    
    For high-confidence, clear-category items, this executes automatically.
    For ambiguous items, the interrupt fires and the human decides.
    """
    # This is where the actual MCP tool call happens:
    # - "file_ticket" → Linear MCP create_issue
    # - "archive" → Gmail MCP archive
    # - "draft_reply" → Gmail MCP create_draft
    # - "skip" → log and move on
    
    return {
        "item_id": item_id,
        "action": action,
        "status": "executed",
        "decided_by": "agent" if confidence >= 0.7 else "human"
    }
```

### 1.4 Graph factory (`graph/factory.py`)

```python
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.multiagent import GraphBuilder  # confirm exact import

from handoff.graph.nodes.trigger import check_trigger
from handoff.graph.nodes.executor import fetch_unread_emails
from handoff.graph.nodes.classifier import classify_email
from handoff.graph.nodes.gate import submit_action
from handoff.graph.nodes.completer import finalize_run
from handoff.graph.hooks.hitl import register_hitl_gate

EXECUTOR_SYSTEM_PROMPT = """You are Handoff's Workflow Executor agent.

Your job is to execute a workflow autonomously:
1. Fetch the items to process (emails, tasks, etc.)
2. Classify each item using your judgment
3. For clear cases (confidence >= 0.7): execute the action automatically
4. For ambiguous cases (confidence < 0.7): call submit_action with 
   force_interrupt=True so the human can decide

You are THOROUGH but SELECTIVE about interruptions. Only escalate 
genuinely ambiguous items. The user trusts you to handle the clear ones.

CRITICAL: When calling submit_action for ambiguous items, ALWAYS set 
force_interrupt=True and provide clear reasoning and options."""

def build_inbox_triage_graph(model):
    """Build the inbox triage workflow as a Strands Graph."""
    
    # Create agents for each node
    trigger_agent = Agent(
        model=model,
        tools=[check_trigger],
        system_prompt="You check if a workflow trigger condition is met."
    )
    
    executor_agent = Agent(
        model=model,
        tools=[fetch_unread_emails, classify_email, submit_action],
        system_prompt=EXECUTOR_SYSTEM_PROMPT
    )
    
    # Register the HITL gate on the executor agent
    register_hitl_gate(executor_agent)
    
    completer_agent = Agent(
        model=model,
        tools=[finalize_run],
        system_prompt="You finalize a workflow run: summarize what was done and log it."
    )
    
    # Wire the Graph
    builder = GraphBuilder()
    builder.add_node(trigger_agent, "trigger")
    builder.add_node(executor_agent, "executor")
    builder.add_node(completer_agent, "completer")
    builder.add_edge("trigger", "executor")
    builder.add_edge("executor", "completer")
    builder.set_entry_point("trigger")
    
    return builder.build()
```

### 1.5 Tests for Phase 1

```python
# tests/test_hitl_gate.py
import pytest

def test_interrupt_fires_on_low_confidence():
    """submit_action with confidence < 0.7 must trigger interrupt."""
    # Setup agent with gate hook
    # Call submit_action with confidence=0.4
    # Assert interrupt was raised (not executed)
    pass

def test_auto_executes_on_high_confidence():
    """submit_action with confidence >= 0.7 executes without interrupt."""
    # Setup agent with gate hook
    # Call submit_action with confidence=0.9
    # Assert action was executed (no interrupt)
    pass

def test_interrupt_payload_is_complete():
    """Interrupt payload contains all fields the decision UI needs."""
    # Trigger an interrupt
    # Assert payload has: summary, options, reasoning, confidence
    pass
```

### Phase 1 deliverables checklist:
- [ ] Models defined (pydantic)
- [ ] HITL gate hook working (`event.interrupt()` fires)
- [ ] Mock email data returns from executor tool
- [ ] Classifier tool structure ready (LLM fills it)
- [ ] Graph wired (trigger → executor → completer)
- [ ] `test_hitl_gate.py` passing
- [ ] Can run locally: `python scripts/run_local.py`

---

## Phase 2 — Builder Agent + Workflow Config (Days 3–5)

**Goal:** A conversational agent that takes a natural-language description and outputs a valid workflow config JSON.

### 2.1 Builder Agent (`agents/builder.py`)

```python
from strands import Agent
from strands.models.bedrock import BedrockModel

BUILDER_SYSTEM_PROMPT = """You are Handoff's Builder Agent.

The user will describe a repetitive task they want automated. Your job is to:

1. UNDERSTAND what they want (ask clarifying questions if needed)
2. IDENTIFY which MCP tools are needed (Gmail, Linear, Slack, etc.)
3. DETERMINE the trigger (cron schedule, webhook, manual)
4. DEFINE the classification rules (what's auto vs what needs human judgment)
5. GENERATE a valid workflow config JSON

OUTPUT FORMAT:
When you have enough information, output a JSON workflow config wrapped in
```json ... ``` tags. The config must follow this schema:

{
  "workflow_id": "slug-format-id",
  "name": "Human Readable Name",
  "description": "What this workflow does",
  "trigger": {
    "type": "cron|webhook|manual",
    "schedule": "cron expression (if cron)",
    "timezone": "timezone string"
  },
  "mcp_tools": ["gmail", "linear", "slack"],
  "steps": [...],
  "completion": {
    "notify": "slack|email|none",
    "message": "template with {variables}"
  },
  "memory": {
    "learn_from_decisions": true,
    "preference_key": "unique_key"
  }
}

Be SPECIFIC about the classification rules. The user trusts you to handle 
clear cases automatically — only genuinely ambiguous items should trigger 
a human decision.

Available MCP tools: gmail, linear, slack, github, jira, notion, 
browser (for web scraping), code_interpreter (for data processing).
"""

def create_builder_agent(model):
    return Agent(
        model=model,
        tools=[discover_mcp_tools, validate_workflow, preview_workflow],
        system_prompt=BUILDER_SYSTEM_PROMPT
    )
```

### 2.2 Builder tools

```python
from strands import tool

@tool
def discover_mcp_tools() -> list[dict]:
    """List all available MCP tools the user can use in workflows."""
    return [
        {"name": "gmail", "description": "Read, search, archive, draft, send emails",
         "actions": ["search_threads", "get_message", "archive", "create_draft", "send"]},
        {"name": "linear", "description": "Create, update, search issues and projects",
         "actions": ["create_issue", "update_issue", "search_issues"]},
        {"name": "slack", "description": "Send messages, read channels, post updates",
         "actions": ["post_message", "read_channel"]},
        {"name": "github", "description": "Manage PRs, issues, repos, code review",
         "actions": ["list_prs", "create_issue", "review_pr"]},
        {"name": "browser", "description": "Browse web pages, take screenshots, extract data",
         "actions": ["navigate", "screenshot", "extract_text"]},
    ]

@tool
def validate_workflow(config_json: str) -> dict:
    """Validate a workflow config JSON for correctness."""
    import json
    try:
        config = json.loads(config_json)
        errors = []
        if "workflow_id" not in config:
            errors.append("Missing workflow_id")
        if "trigger" not in config:
            errors.append("Missing trigger")
        if "steps" not in config:
            errors.append("Missing steps")
        if not config.get("mcp_tools"):
            errors.append("No MCP tools specified")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "config": config if not errors else None
        }
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"Invalid JSON: {e}"], "config": None}

@tool
def preview_workflow(config_json: str) -> str:
    """Generate a human-readable preview of what the workflow will do."""
    import json
    config = json.loads(config_json)
    
    preview = f"📋 Workflow: {config.get('name', 'Unnamed')}\n"
    preview += f"⏰ Trigger: {config.get('trigger', {}).get('type', 'manual')}"
    if config.get("trigger", {}).get("schedule"):
        preview += f" ({config['trigger']['schedule']})"
    preview += f"\n🔧 Tools: {', '.join(config.get('mcp_tools', []))}\n"
    preview += f"📝 Steps: {len(config.get('steps', []))}\n"
    preview += f"\nThis workflow will run and handle clear cases automatically. "
    preview += f"Ambiguous items will be surfaced for your decision."
    
    return preview
```

### Phase 2 deliverables checklist:
- [ ] Builder agent generates valid workflow config from natural language
- [ ] `discover_mcp_tools` returns available tools
- [ ] `validate_workflow` catches config errors
- [ ] `preview_workflow` shows readable summary
- [ ] Chat UI works (type description → get config)
- [ ] Pre-built `inbox_triage.json` example config in `workflows/examples/`

---

## Phase 3 — Memory, MCP, Real Tools (Days 5–8)

**Goal:** Connect real MCP servers, add AgentCore Memory for learning, and make the workflow loop actually call tools.

### 3.1 AgentCore Memory (`memory/store.py`)

```python
from strands import tool

@tool
def store_user_preference(key: str, preference: dict) -> dict:
    """Store a learned user preference in AgentCore Memory.
    
    Called by the Learning Agent after each human decision.
    Example: user always archives emails from vendor@spam.com
    → store {"sender": "vendor@spam.com", "action": "archive", "confidence": 0.95}
    """
    # AgentCore Memory API call
    # memory.store(key=key, value=preference, strategy="user_preference")
    return {"stored": True, "key": key}

@tool
def recall_preferences(context: str) -> list[dict]:
    """Recall learned user preferences relevant to the current context.
    
    Called by the Executor before classifying items.
    Uses semantic search over stored preferences.
    """
    # AgentCore Memory API call
    # results = memory.recall(query=context, strategy="semantic")
    return []  # returns list of relevant preferences
```

### 3.2 Learning Agent (`agents/learner.py`)

```python
LEARNER_SYSTEM_PROMPT = """You are Handoff's Learning Agent.

After the user makes a decision on an ambiguous item, you analyze:
1. What was the item? (email, task, etc.)
2. What did the user decide? (action taken)
3. What pattern does this reveal? (e.g., "emails from X should always be archived")

Store the learned preference so the Executor can handle similar items 
automatically next time, WITHOUT interrupting the user.

Be SPECIFIC in the pattern — store sender, keywords, context, and the 
preferred action. Don't over-generalize.
"""
```

### 3.3 MCP server connections (`mcp/servers.py`)

```python
# MCP server registry
# These are the MCP servers Handoff can connect to
MCP_SERVERS = {
    "gmail": {
        "url": "npx @anthropic/gmail-mcp-server",
        "description": "Gmail read/write access",
        "requires_auth": True
    },
    "linear": {
        "url": "npx @anthropic/linear-mcp-server", 
        "description": "Linear issue tracking",
        "requires_auth": True
    },
    "slack": {
        "url": "npx @anthropic/slack-mcp-server",
        "description": "Slack messaging",
        "requires_auth": True
    },
    # For the demo, use mock MCP servers if real auth isn't available
}
```

### Phase 3 deliverables checklist:
- [ ] AgentCore Memory storing/recalling preferences
- [ ] Learning Agent updates preferences after each human decision
- [ ] At least one real MCP server connected (or convincing mock)
- [ ] Executor uses recalled preferences to improve classification
- [ ] Second run shows improvement (fewer interrupts)

---

## Phase 4 — Decision UI + Dashboard (Days 7–10)

**Goal:** A clean web interface for the chat builder, the decision screen, and a workflow dashboard.

### 4.1 FastAPI app (`ui/server.py`)

```python
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Handoff")
templates = Jinja2Templates(directory="ui/templates")
app.mount("/static", StaticFiles(directory="ui/static"), name="static")

@app.get("/")
async def dashboard(request: Request):
    """Show all workflows + recent runs + audit log."""
    workflows = await get_workflows()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "workflows": workflows
    })

@app.get("/chat")
async def chat_page(request: Request):
    """Chat interface for building workflows."""
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/chat/send")
async def chat_send(request: Request):
    """Send a message to the Builder Agent."""
    data = await request.json()
    response = builder_agent(data["message"])
    return {"response": str(response)}

@app.get("/decide/{interrupt_id}")
async def decision_page(request: Request, interrupt_id: str):
    """One-screen decision for an interrupted workflow item."""
    payload = await get_interrupt_payload(interrupt_id)
    return templates.TemplateResponse("decision.html", {
        "request": request, "payload": payload
    })

@app.post("/decide/{interrupt_id}")
async def submit_decision(request: Request, interrupt_id: str):
    """Human submits their decision — resume the workflow."""
    data = await request.form()
    decision = UserDecision(
        interrupt_id=interrupt_id,
        chosen_action=data["action"],
        user_note=data.get("note", "")
    )
    # Resume the paused graph with the decision
    await resume_workflow(interrupt_id, decision)
    return {"status": "resumed"}

@app.get("/trace/{run_id}")
async def trace_page(request: Request, run_id: str):
    """Show the observability trace for a workflow run."""
    trace = await get_trace(run_id)
    return templates.TemplateResponse("trace.html", {
        "request": request, "trace": trace
    })
```

### 4.2 Decision screen HTML (`ui/templates/decision.html`)
Keep this SIMPLE — one screen, one decision:
- Item summary (email subject, sender, snippet)
- Agent's reasoning ("I'm not sure because...")
- Agent's suggested action
- Confidence score (visual bar)
- 3-4 action buttons: the suggested action, alternatives, "skip"
- Optional note field
- The buttons POST to `/decide/{interrupt_id}` and resume the workflow

### Phase 4 deliverables checklist:
- [ ] Chat interface works (type → Builder Agent responds)
- [ ] Decision screen renders from interrupt payload
- [ ] Decision submission resumes the workflow
- [ ] Dashboard shows workflow list + recent runs
- [ ] Trace page shows OTEL reasoning trace

---

## Phase 5 — AgentCore Deploy + Observability (Days 9–12)

**Goal:** Deploy the Workflow Executor on AgentCore Runtime as a scheduled background job. Enable observability. Get a live demo link.

### 5.1 AgentCore entrypoint (`app.py`)

```python
from bedrock_agentcore import BedrockAgentCoreApp  # confirm import
from handoff.graph.factory import build_inbox_triage_graph
from handoff.config import get_model

app = BedrockAgentCoreApp()

@app.entrypoint
def handler(event, context):
    """
    AgentCore Runtime entrypoint.
    
    Event types:
    - {"type": "tick"}: scheduled cron trigger → run the workflow
    - {"type": "resume", "interrupt_id": "...", "decision": {...}}: 
      human made a decision → resume the paused graph
    - {"type": "build", "message": "..."}: user describing a workflow → Builder Agent
    """
    model = get_model()
    
    if event.get("type") == "tick":
        graph = build_inbox_triage_graph(model)
        return graph.invoke({"trigger_type": "cron"})
    
    elif event.get("type") == "resume":
        return graph.resume(
            interrupt_id=event["interrupt_id"],
            decision=event["decision"]
        )
    
    elif event.get("type") == "build":
        from handoff.agents.builder import create_builder_agent
        builder = create_builder_agent(model)
        return builder(event["message"])

if __name__ == "__main__":
    app.run()
```

### 5.2 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY ui/ ./ui/
COPY workflows/ ./workflows/

ENV PYTHONPATH=/app/src
EXPOSE 8080

CMD ["python", "-m", "handoff.app"]
```

### 5.3 Deploy commands

```bash
# Build ARM64 image
docker buildx build --platform linux/arm64 -t handoff:latest .

# Push to ECR
aws ecr create-repository --repository-name handoff
docker tag handoff:latest <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/handoff:latest
docker push <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/handoff:latest

# Deploy to AgentCore Runtime
pip install bedrock-agentcore-starter-toolkit
agentcore configure --entrypoint src/handoff/app.py
agentcore launch

# Test deployed agent
agentcore invoke '{"type":"tick"}'
```

### 5.4 Observability
```python
# In config.py — enable OTEL tracing
import os
os.environ["STRANDS_OTEL_ENABLE"] = "true"
os.environ["STRANDS_OTEL_EXPORTER"] = "cloudwatch"
```

### Phase 5 deliverables checklist:
- [ ] Dockerfile builds (ARM64)
- [ ] Deployed on AgentCore Runtime
- [ ] Scheduled trigger working (EventBridge → AgentCore)
- [ ] Live demo URL accessible
- [ ] OTEL traces visible in CloudWatch
- [ ] Reasoning trace captured for demo video

---

## Phase 6 — Polish, Video, Submit (Days 12–14)

### 6.1 Final testing
```bash
pytest tests/ -v
# All tests green, especially test_hitl_gate.py
```

### 6.2 Demo video (≤5 min) — see `09_DEMO_VIDEO_SCRIPT.md`

### 6.3 builder.aws.com post — see `10_BUILDER_POST.md`

### 6.4 Devpost submission — see `11_SUBMISSION_CHECKLIST.md`

### Phase 6 deliverables checklist:
- [ ] All tests passing
- [ ] README.md finalized
- [ ] Architecture diagram (PNG) in docs/
- [ ] Demo video recorded and uploaded
- [ ] builder.aws.com post published
- [ ] Devpost submission complete
- [ ] Live demo link working
