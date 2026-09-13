# Handoff — Strands Agents SDK Integration Guide

## Overview
This document details every Strands Agents SDK feature Handoff uses and how to integrate each one. **Read the official docs at `strandsagents.com` before building** — API surfaces evolve. Pin your SDK version on Day 1.

## Installation

```bash
pip install strands-agents strands-agents-tools
pip install strands-agents[bedrock]  # Bedrock model provider
```

---

## 1. Agent Class (core primitive)

Every agent in Handoff is a Strands `Agent` instance:

```python
from strands import Agent
from strands.models.bedrock import BedrockModel

model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    region_name="us-east-1"
)

agent = Agent(
    model=model,
    system_prompt="Your system prompt here",
    tools=[tool1, tool2, tool3],  # list of @tool functions
    # callback_handler=...,  # optional streaming callback
)

# Invoke
response = agent("Process these emails and classify them")
print(response)
```

**Handoff uses 3 agents:**
- `builder_agent` — conversational, takes user input
- `executor_agent` — autonomous, runs in background
- `learner_agent` — post-decision, updates memory

---

## 2. Tools (`@tool` decorator)

Every tool is a Python function with the `@tool` decorator:

```python
from strands import tool

@tool
def fetch_unread_emails(query: str = "is:unread", max_results: int = 20) -> list[dict]:
    """Fetch unread emails matching the query.
    
    Args:
        query: Gmail search query string
        max_results: Maximum number of emails to return
    
    Returns:
        List of email objects with id, sender, subject, snippet
    """
    # Implementation here
    return [...]
```

**Rules for tools:**
- Docstring becomes the tool description the LLM sees — make it clear and specific.
- Type hints on params are required — they become the tool's input schema.
- Return type should be JSON-serializable (dict, list, str, int, bool).
- Tool name = function name. Keep names descriptive and unique.

**Handoff's tool inventory:**

| Tool | Agent | Purpose |
|---|---|---|
| `check_trigger` | Trigger node | Check if trigger condition met |
| `fetch_unread_emails` | Executor | Get emails from Gmail |
| `classify_email` | Executor | LLM classifies an email |
| `submit_action` | Executor (GATED) | Execute action — interrupt gate here |
| `finalize_run` | Completer | Write audit log + send summary |
| `discover_mcp_tools` | Builder | List available MCP servers |
| `validate_workflow` | Builder | Validate workflow config JSON |
| `preview_workflow` | Builder | Human-readable workflow preview |
| `store_user_preference` | Learner | Write to AgentCore Memory |
| `recall_preferences` | Executor | Read from AgentCore Memory |

---

## 3. Hooks — BeforeToolCallEvent (THE CENTERPIECE)

The interrupt gate is Handoff's most important feature. It uses a `BeforeToolCallEvent` hook:

```python
from strands.hooks import BeforeToolCallEvent

def register_hitl_gate(agent):
    @agent.hooks.add(BeforeToolCallEvent)
    def gate(event: BeforeToolCallEvent):
        tool_name = event.tool_use.get("name", "")
        tool_input = event.tool_use.get("input", {})
        
        should_interrupt = (
            tool_name in GATED_TOOLS
            or tool_input.get("confidence", 1.0) < 0.7
        )
        
        if should_interrupt:
            event.interrupt(
                reason="human_approval_required",
                data={
                    "tool": tool_name,
                    "summary": tool_input.get("summary"),
                    "options": tool_input.get("options"),
                    "reasoning": tool_input.get("reasoning"),
                }
            )
```

**IMPORTANT:** Confirm the exact `event.interrupt()` API signature against current Strands docs. Alternative approaches include:
- `HumanInTheLoop` intervention handler (allow-lists + LLM classifier)
- Tool-context interrupt (return special value from tool)
- Remote interrupt (Step Functions / SNS approval pattern)

Check `strandsagents.com/docs/user-guide/concepts/agents/interrupt/` and the GitHub issues for the latest.

**How resume works:**
```python
# After the human decides, resume the paused graph:
graph.resume(
    interrupt_id=interrupt_id,
    decision={"action": "archive", "approved": True}
)
```

---

## 4. Graph (multi-agent orchestration)

Handoff's workflow executor is a Strands `Graph` — a deterministic directed flow:

```python
from strands.multiagent import GraphBuilder  # confirm exact import path

builder = GraphBuilder()

# Add nodes (each is a Strands Agent)
builder.add_node(trigger_agent, "trigger")
builder.add_node(executor_agent, "executor")
builder.add_node(completer_agent, "completer")

# Add edges (deterministic flow)
builder.add_edge("trigger", "executor")
builder.add_edge("executor", "completer")

# Set entry point
builder.set_entry_point("trigger")

# Build
graph = builder.build()

# Invoke
result = graph.invoke({"trigger_type": "cron", "today": "2026-09-10"})
```

**Why Graph, not Swarm or agents-as-tools:**
- Graph = deterministic, auditable, same flow every time.
- Swarm = free-form agent conversation — wrong for a repeatable workflow.
- Agents-as-tools = one agent calling another — useful for the Builder calling a preview, but wrong for the execution pipeline.

**Confirm the exact Graph API** at `strandsagents.com/docs/user-guide/concepts/multi-agent/`. The import path and builder pattern may differ from the sketch above.

---

## 5. MCP (Model Context Protocol)

Strands has native MCP support for connecting to external tool servers:

```python
from strands import Agent
from strands.mcp import MCPClient  # confirm exact import

# Connect to an MCP server
gmail_mcp = MCPClient(
    server_command="npx @anthropic/gmail-mcp-server",
    # or server_url="http://localhost:3000/mcp" for remote servers
)

# Pass MCP tools to agent
agent = Agent(
    model=model,
    tools=[gmail_mcp],  # agent discovers tools from the MCP server
    system_prompt="..."
)
```

**For the demo:** if real MCP auth is complex, use mock tools that return synthetic data. The Graph + interrupt gate carry the score — real MCP is a bonus.

**Confirm MCP API** at `strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/`.

---

## 6. Memory (sessions + long-term)

### Short-term (session memory)
```python
from strands import Agent
from strands.memory import SessionMemory  # confirm import

agent = Agent(
    model=model,
    memory=SessionMemory(session_id="workflow-run-001"),
    tools=[...],
    system_prompt="..."
)
```

### Long-term (AgentCore Memory)
```python
# AgentCore Memory provides strategies:
# - semantic: vector-based recall
# - user_preference: key-value user prefs
# - summary: condensed conversation history
# - episodic: event-based recall

# Confirm AgentCore Memory API at build time
```

**Handoff uses Memory for:**
1. **Session context:** remembering the current workflow run's state.
2. **User preferences:** learned rules from past decisions ("always archive vendor@spam.com").
3. **Workflow history:** what happened in past runs (for the Completer's summary).

---

## 7. Observability (OpenTelemetry)

```python
import os

# Enable OTEL tracing
os.environ["STRANDS_OTEL_ENABLE"] = "true"

# Export to CloudWatch (when on AgentCore)
os.environ["STRANDS_OTEL_EXPORTER"] = "cloudwatch"

# Or export to console (local dev)
os.environ["STRANDS_OTEL_EXPORTER"] = "console"
```

**Show the trace in the demo.** The observability trace proves the agent is real and reasoning, not a scripted demo. Judges see: trigger fired → emails fetched → classified → 3 auto-acted → 1 interrupted → human decided → completed.

---

## 8. AgentCore Runtime (deployment)

```python
from bedrock_agentcore import BedrockAgentCoreApp  # confirm import

app = BedrockAgentCoreApp()

@app.entrypoint
def handler(event, context):
    # Your agent logic here
    pass

if __name__ == "__main__":
    app.run()
```

**Key Runtime features used by Handoff:**
- **Serverless execution** — no infra to manage
- **Session isolation** — each workflow run is isolated
- **Up to 8-hour execution** — plenty for any workflow
- **Async/long-running** — the workflow runs in background
- **Scheduled triggers** — via EventBridge integration

---

## 9. Strands Feature Checklist (for scoring)

| Feature | Used in Handoff | Where |
|---|---|---|
| ✅ Agent class | All three agents | `agents/` |
| ✅ @tool decorator | 10+ custom tools | `tools/`, `graph/nodes/` |
| ✅ System prompts | Each agent has a specific prompt | `agents/`, `graph/factory.py` |
| ✅ BeforeToolCallEvent hook | HITL interrupt gate | `graph/hooks/hitl.py` |
| ✅ event.interrupt() | Decision gate | `graph/hooks/hitl.py` |
| ✅ Graph orchestration | Workflow executor pipeline | `graph/factory.py` |
| ✅ MCP tools | Gmail, Linear, Slack | `mcp/servers.py` |
| ✅ Memory (session) | Workflow run context | `memory/store.py` |
| ✅ Memory (long-term) | Learned user preferences | `memory/store.py` |
| ✅ Observability (OTEL) | Reasoning traces | `config.py` |
| ✅ AgentCore Runtime | Serverless background deploy | `app.py` |
| ✅ AgentCore Memory | User preferences + semantic | `memory/store.py` |
| ✅ AgentCore Browser | Competitor monitoring workflow | optional |
| ✅ AgentCore Code Interpreter | Data processing workflows | optional |
| ✅ AgentCore Gateway | Expose custom APIs as tools | optional |
| ✅ AgentCore Identity | Cognito auth for UI | `ui/server.py` |

That is **every major Strands + AgentCore feature** in one project. No other submission will touch all of them.

---

## 10. Common Pitfalls to Avoid

1. **Don't guess the API** — pin `strands-agents==X.Y.Z` on Day 1 and read the docs for that version.
2. **Don't build a chat wrapper** — the hackathon explicitly says "not another app people open and manage." The background execution + interrupt is what wins.
3. **Don't skip the interrupt gate** — it's the single feature the hackathon brief describes. Make it work first, polish everything else second.
4. **Don't hardcode tool calls** — use the `@tool` decorator properly so the LLM reasons about which tools to call. That's the "model-driven" philosophy of Strands.
5. **Don't deploy a broken AgentCore** — a working local demo beats a broken cloud deploy. Get local working first, then deploy.
