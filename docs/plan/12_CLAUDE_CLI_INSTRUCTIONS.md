# Handoff — Claude CLI Build Instructions

## How to use these docs with Claude CLI (Claude Code)

These `.md` files are your complete blueprint. Feed them to Claude CLI as context to generate the actual code.

---

## Recommended Workflow

### Step 1: Initialize the project
```bash
# Create the repo
mkdir handoff && cd handoff
git init

# Create the directory structure
mkdir -p src/handoff/{agents,graph/{nodes,hooks},tools,memory,mcp}
mkdir -p ui/{templates,static}
mkdir -p workflows/examples
mkdir -p infra tests scripts docs

# Copy these docs into a reference folder
mkdir -p docs/plan
cp /path/to/these/md/files/* docs/plan/
```

### Step 2: Feed docs to Claude CLI for each phase

**Phase 1 — Interrupt Gate + Graph:**
```bash
claude "Read docs/plan/03_IMPLEMENTATION_PLAN.md, 
       docs/plan/04_STRANDS_INTEGRATION.md, and 
       docs/plan/06_HITL_INTERRUPT_GATE.md.
       
       Build Phase 1: create the data models (src/handoff/models.py),
       the HITL interrupt gate hook (src/handoff/graph/hooks/hitl.py),
       the graph nodes (trigger, executor, classifier, gate, completer),
       the graph factory (src/handoff/graph/factory.py),
       and the test (tests/test_hitl_gate.py).
       
       Use mock email data from docs/plan/05_TOOLS_AND_MCP.md.
       Pin strands-agents to the latest version.
       Follow the code sketches in the docs but verify against
       current Strands API at strandsagents.com."
```

**Phase 2 — Builder Agent:**
```bash
claude "Read docs/plan/03_IMPLEMENTATION_PLAN.md Phase 2 section.
       
       Build the Builder Agent (src/handoff/agents/builder.py)
       and its tools (discover_mcp_tools, validate_workflow, preview_workflow).
       
       Also create the pre-built workflow config at
       workflows/examples/inbox_triage.json matching the schema
       in docs/plan/02_ARCHITECTURE.md."
```

**Phase 3 — Memory + Tools:**
```bash
claude "Read docs/plan/03_IMPLEMENTATION_PLAN.md Phase 3 and
       docs/plan/05_TOOLS_AND_MCP.md.
       
       Build the Memory store (src/handoff/memory/store.py),
       the Learning Agent (src/handoff/agents/learner.py),
       and the MCP server registry (src/handoff/mcp/servers.py).
       
       Make sure the executor agent calls recall_preferences
       before classifying, and the learner stores preferences
       after each human decision."
```

**Phase 4 — UI:**
```bash
claude "Read docs/plan/07_UI_AND_FRONTEND.md completely.
       
       Build the full FastAPI app (ui/server.py) with all 4 routes
       and all 4 HTML templates (dashboard, chat, decision, trace).
       Include the CSS file (ui/static/styles.css).
       
       The decision screen is the most important page —
       make it clean, one-screen, with clear action buttons."
```

**Phase 5 — Deploy:**
```bash
claude "Read docs/plan/08_DEPLOYMENT.md.
       
       Create the AgentCore entrypoint (src/handoff/app.py),
       Dockerfile, infra scripts (dynamodb_setup.py, eventbridge_setup.py),
       .env.example, and requirements.txt.
       
       Also create the local run script (scripts/run_local.py)."
```

**Phase 6 — Polish:**
```bash
claude "Read docs/plan/11_README_TEMPLATE.md.
       
       Generate the final README.md for the repo.
       Fill in all sections. Leave placeholders for
       video URL, live demo URL, and Builder ID."
```

### Step 3: Test and iterate
```bash
# Run tests
pytest tests/ -v

# Run locally
python scripts/run_local.py --workflow inbox_triage

# Start UI
cd ui && uvicorn server:app --reload --port 8000

# Fix issues with Claude CLI
claude "The test test_hitl_gate.py is failing because [error]. 
       Fix the interrupt gate implementation."
```

### Step 4: Deploy
```bash
# Follow docs/plan/08_DEPLOYMENT.md
claude "Help me deploy Handoff to AgentCore Runtime.
       Read docs/plan/08_DEPLOYMENT.md and walk me through
       each step with the actual commands for my AWS account."
```

### Step 5: Record demo
```bash
# Follow docs/plan/09_DEMO_AND_POST.md storyboard
# Use OBS Studio or Loom
# Narrate over screen recording
```

---

## Key Prompts for Claude CLI

### "Verify against current Strands docs"
```bash
claude "Before writing any Strands code, check the current API:
       1. What is the exact import path for BeforeToolCallEvent?
       2. What is the exact API for event.interrupt()?
       3. What is the exact import path for GraphBuilder?
       4. What is the exact import for BedrockModel?
       5. How does graph.resume() work?
       Read strandsagents.com docs and the strands-agents PyPI package."
```

### "Generate the architecture diagram"
```bash
claude "Read docs/plan/02_ARCHITECTURE.md.
       Generate a clean architecture diagram as an SVG or
       use mermaid/excalidraw format.
       Show: User Layer (chat + decision screen) →
       Agent Layer (Builder, Executor Graph, Learner) →
       Tool Layer (MCP + AgentCore services) →
       AWS Infra Layer (Runtime, Memory, DynamoDB, etc.)
       Save to docs/architecture.png"
```

### "Write all tests"
```bash
claude "Read the test descriptions in docs/plan/03_IMPLEMENTATION_PLAN.md
       and docs/plan/06_HITL_INTERRUPT_GATE.md.
       
       Generate complete test files:
       - tests/test_hitl_gate.py (interrupt fires/doesn't fire correctly)
       - tests/test_builder_agent.py (generates valid config)
       - tests/test_graph_factory.py (Graph builds from config)
       - tests/test_classifier.py (classification accuracy)
       - tests/test_learner.py (Memory updates correctly)
       - tests/test_e2e.py (full loop with mocks)
       
       Use pytest. Mock external services."
```

---

## File Generation Order (optimal for Claude CLI)

1. `pyproject.toml` / `requirements.txt` — dependencies first
2. `src/handoff/config.py` — settings and env vars
3. `src/handoff/models.py` — pydantic data models
4. `src/handoff/graph/hooks/hitl.py` — THE CENTERPIECE
5. `src/handoff/graph/nodes/*.py` — all graph nodes
6. `src/handoff/graph/factory.py` — graph wiring
7. `src/handoff/agents/executor.py` — workflow executor
8. `tests/test_hitl_gate.py` — test the gate IMMEDIATELY
9. `src/handoff/tools/*.py` — all custom tools
10. `src/handoff/agents/builder.py` — builder agent
11. `src/handoff/agents/learner.py` — learning agent
12. `src/handoff/memory/store.py` — memory integration
13. `src/handoff/mcp/servers.py` — MCP registry
14. `ui/server.py` — FastAPI app
15. `ui/templates/*.html` — all 4 templates
16. `ui/static/styles.css` — styling
17. `src/handoff/app.py` — AgentCore entrypoint
18. `Dockerfile` — container build
19. `scripts/run_local.py` — local runner
20. `infra/*.py` — AWS setup scripts
21. `workflows/examples/*.json` — example configs
22. Remaining tests
23. `README.md` — final README
24. `LICENSE` — Apache-2.0
25. `docs/architecture.png` — diagram

---

## Tips for Claude CLI

- **Be specific.** "Build the HITL gate" is better than "build the project."
- **Reference the docs.** Always tell Claude to read the relevant `.md` file first.
- **Build in phases.** Don't ask for everything at once. Phase 1 first, test, then Phase 2.
- **Verify Strands API.** The code sketches in these docs are based on documented patterns but the exact API may differ. Always tell Claude to check current docs.
- **Test after each phase.** Don't move to Phase 2 until Phase 1 tests pass.
- **Keep the gate as the spine.** If anything breaks, fix the interrupt gate first — it's the whole project.
