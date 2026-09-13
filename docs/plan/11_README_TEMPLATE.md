# ⚡ Handoff

**Describe it. Hand it off. It runs.**

Handoff turns natural-language descriptions of repetitive professional tasks into autonomous workflows that run on schedule — and only surface when there's a real decision to make.

> Built with [Strands Agents SDK](https://strandsagents.com) for the [Agents for Humans Hackathon](https://agentsforhumans.devpost.com/) — Professional Agents track.

[Demo Video](#demo) · [Live Demo](#live-demo) · [Architecture](#architecture) · [Setup](#setup) · [How It Works](#how-it-works)

---

## The Problem

Professionals lose hours every day to small, repetitive tasks — triaging email, filing tickets, sending follow-ups, compiling reports. Each one takes a few minutes, but together they drain real time and attention. The usual fix — another app to manage — just adds overhead.

## Who It's For

Developers, operators, founders, and small-team professionals who do the same background tasks every day and want them handled autonomously.

## How It Works

1. **Describe** — Type what you want automated in plain language
2. **Build** — Handoff's Builder Agent assembles a workflow with the right tools and rules
3. **Run** — The workflow runs autonomously on schedule (AgentCore Runtime)
4. **Decide** — When the agent hits something genuinely ambiguous, it pauses and asks you — one screen, one decision
5. **Learn** — Your decisions feed back into Memory so the agent handles similar cases next time

### The Interrupt Gate (the centerpiece)

Handoff never acts on ambiguous items without human approval. The `BeforeToolCallEvent` hook fires `event.interrupt()` when the agent's confidence is below threshold — pausing the loop and surfacing a one-screen decision to the user. Clear cases are handled silently. Only genuinely ambiguous items surface.

**This is the feature the hackathon asked for:** *"the agent runs autonomously and only surfaces when there's a real decision to make."*

---

## Architecture

![Architecture Diagram](docs/architecture.png)

### Three Agents

| Agent | Role |
|---|---|
| **Builder Agent** | Interprets natural-language task descriptions → generates workflow configs |
| **Workflow Executor** | Runs autonomously as a Strands Graph: Trigger → Execute → Classify → Gate → Complete |
| **Learning Agent** | Post-decision: updates AgentCore Memory so the agent improves with use |

### Why Graph (not Swarm)

The workflow is a deterministic sequence — trigger → execute → classify → gate → complete. This is a fixed directed flow, which is exactly what Strands `Graph` is for. Swarm is for free-form agent collaboration — architecturally wrong for a repeatable, auditable workflow.

### AWS Services Used

| Service | Purpose |
|---|---|
| Amazon Bedrock (Claude Sonnet) | LLM for all agents |
| AgentCore Runtime | Serverless background execution |
| AgentCore Memory | Learned user preferences across runs |
| AgentCore Browser | Web workflows (competitor monitoring) |
| AgentCore Code Interpreter | Data processing workflows |
| AgentCore Gateway | Custom API tools |
| AgentCore Identity | Cognito auth |
| AgentCore Observability | OTEL → CloudWatch traces |
| DynamoDB | Workflow configs + audit log |
| EventBridge | Cron triggers |
| SNS/SES | Notifications |

### Strands SDK Features Used

Agent class, `@tool` decorator, `BeforeToolCallEvent` hooks, `event.interrupt()`, Graph orchestration, MCP tools, session + long-term Memory, OpenTelemetry observability, AgentCore Runtime deployment.

---

## Demo

[▶ Watch the 5-minute demo video](YOUR_VIDEO_URL_HERE)

The demo shows:
- Building an inbox-triage workflow from a single sentence
- The agent autonomously handling 5 out of 8 emails (tickets filed, newsletters archived, replies drafted)
- The agent pausing on 3 ambiguous emails and surfacing one-screen decisions
- The human approving in one click
- The learning loop storing the preference for next time
- The full observability trace

## Live Demo

[🔗 Try the live demo](YOUR_LIVE_DEMO_URL_HERE)

---

## Setup

### Prerequisites
- Python 3.12+
- AWS account with Bedrock model access
- AWS CLI configured

### Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/handoff.git
cd handoff

# Setup
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your AWS credentials and model IDs

# Setup DynamoDB tables
python infra/dynamodb_setup.py

# Run locally
python scripts/run_local.py --workflow inbox_triage

# Start the UI
cd ui && uvicorn server:app --reload --port 8000
# Open http://localhost:8000
```

### Deploy to AgentCore (optional, recommended)

```bash
# Build and push Docker image
docker buildx build --platform linux/arm64 -t handoff:latest .
# Push to ECR (see docs/DEPLOYMENT.md for full commands)

# Deploy
agentcore configure --entrypoint src/handoff/app.py
agentcore launch
```

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for complete deployment instructions.

---

## Data & Privacy

- **Synthetic data only.** The demo uses mock emails with fictional senders and content. No real PII is used or stored.
- **Human-in-the-loop guardrail.** No irreversible action executes without explicit human approval through the interrupt gate.

---

## Testing

```bash
pytest tests/ -v
```

Key tests:
- `test_hitl_gate.py` — verifies the interrupt fires before gated actions
- `test_graph_factory.py` — verifies the Graph builds correctly
- `test_classifier.py` — verifies email classification accuracy
- `test_e2e.py` — full workflow loop with mock tools

---

## Project Structure

```
handoff/
├── src/handoff/
│   ├── agents/          # Builder, Executor, Learner agents
│   ├── graph/           # Graph factory, nodes, hooks (HITL gate)
│   ├── tools/           # Custom @tool functions
│   ├── memory/          # AgentCore Memory integration
│   └── mcp/             # MCP server connections
├── ui/                  # FastAPI + HTMX (chat, decision, dashboard, trace)
├── workflows/examples/  # Pre-built workflow configs
├── tests/               # Test suite
├── infra/               # AWS setup scripts
└── docs/                # Architecture diagram, deployment guide
```

---

## Built With

- [Strands Agents SDK](https://strandsagents.com) — agent framework
- [Amazon Bedrock](https://aws.amazon.com/bedrock/) — LLM provider
- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) — Runtime, Memory, Browser, Gateway, Identity
- [FastAPI](https://fastapi.tiangolo.com/) + [HTMX](https://htmx.org/) — web UI
- [DynamoDB](https://aws.amazon.com/dynamodb/) — data store
- [MCP](https://modelcontextprotocol.io/) — tool integration

---

## License

[Apache-2.0](LICENSE)

---

## Hackathon

- **Event:** [Agents for Humans Hackathon](https://agentsforhumans.devpost.com/)
- **Track:** Professional Agents
- **AWS Builder ID:** YOUR_BUILDER_ID
- **builder.aws.com post:** [YOUR_POST_URL]
