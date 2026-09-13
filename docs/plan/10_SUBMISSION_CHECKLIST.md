# Handoff — Submission Checklist

## Every hackathon requirement, mapped to deliverable and status.

---

## Required Deliverables

| # | Requirement | Deliverable | Location | Status |
|---|---|---|---|---|
| 1 | New AI agent built with Strands Agents SDK | Three agents (Builder, Executor, Learner) | `src/handoff/agents/` | ☐ |
| 2 | Runs autonomously, surfaces only for real decisions | Scheduled Graph + `event.interrupt()` gate | `src/handoff/graph/` | ☐ |
| 3 | Text description (what/who/how) | Devpost form text | See `09_DEMO_AND_POST.md` | ☐ |
| 4 | **Public** code repo URL | GitHub public repo | `github.com/YOU/handoff` | ☐ |
| 5 | All source code, assets, setup instructions | Complete repo | All of `/handoff` | ☐ |
| 6 | **MIT or Apache** license, visible in About | `LICENSE` file + GitHub About section | Root of repo | ☐ |
| 7 | README | Comprehensive README | `README.md` | ☐ |
| 8 | Architecture diagram | PNG diagram | `docs/architecture.png` | ☐ |
| 9 | Demo video (≤5 min) | Recorded video | YouTube/Loom link | ☐ |
| 10 | Demo covers: problem you're solving | First 40 seconds | Video §1 | ☐ |
| 11 | Demo covers: who it's for | 40s–1:10 mark | Video §2 | ☐ |
| 12 | Demo covers: why it matters | 4:30–4:50 | Video §5 | ☐ |
| 13 | Demo shows working project | 1:10–4:30 | Video §3–4 | ☐ |
| 14 | AWS Builder ID | Created and entered | Devpost form | ☐ |

## Optional (But Strongly Recommended)

| # | Requirement | Impact | Status |
|---|---|---|---|
| 15 | Live demo link | "Projects with a live demo score higher on Technical Implementation" | ☐ |
| 16 | AgentCore deployment | "Deploying with AgentCore strengthens Technical Implementation" | ☐ |
| 17 | builder.aws.com post with "Agents for Humans" in title | Explicit bonus points | ☐ |

---

## Pre-Submission Verification

### Code
- [ ] Repo is **public**
- [ ] `LICENSE` file exists (Apache-2.0)
- [ ] License is visible in GitHub repo's "About" section
- [ ] `README.md` is complete (see template in `11_README_TEMPLATE.md`)
- [ ] Architecture diagram exists at `docs/architecture.png`
- [ ] `.env.example` exists (NO real secrets committed)
- [ ] `requirements.txt` or `pyproject.toml` present
- [ ] Setup instructions work from a clean clone
- [ ] All tests pass: `pytest tests/ -v`

### Agent
- [ ] Agent is built with Strands Agents SDK (import visible)
- [ ] Agent runs autonomously (background/scheduled execution)
- [ ] Agent uses `event.interrupt()` for human decisions
- [ ] Clear cases are auto-handled (not everything interrupted)
- [ ] Resume flow works after human decision
- [ ] Audit log records agent vs human decisions

### Demo Video
- [ ] ≤5 minutes
- [ ] Shows the problem being solved
- [ ] Shows who it's for
- [ ] Shows why it matters
- [ ] Shows the working project end-to-end
- [ ] Shows the autonomous execution (agent working silently)
- [ ] Shows the interrupt moment (agent pausing for human)
- [ ] Shows the decision screen (human approving)
- [ ] Shows the observability trace (proof it's real)
- [ ] Audio is clear
- [ ] Resolution ≥ 1080p

### Accounts
- [ ] AWS Builder ID created
- [ ] $50 AWS credits requested (Resources tab)
- [ ] Devpost account created
- [ ] Hackathon joined on Devpost

### Bonus
- [ ] builder.aws.com post published
- [ ] Post title contains "Agents for Humans"
- [ ] Post links to repo
- [ ] Post includes code snippets + architecture diagram

---

## Submission Steps (on Devpost)

1. Go to https://agentsforhumans.devpost.com/
2. Click "Submit project"
3. Fill in:
   - **Project name:** Handoff
   - **Tagline:** Describe it. Hand it off. It runs.
   - **About:** (use text from `09_DEMO_AND_POST.md`)
   - **Built with:** Strands Agents SDK, Amazon Bedrock, AgentCore, FastAPI, HTMX, DynamoDB, MCP, Python
   - **Track:** Professional Agents
   - **Demo video:** YouTube/Loom URL
   - **Repository URL:** GitHub public repo URL
   - **Live demo link:** (if deployed)
   - **AWS Builder ID:** your ID
   - **builder.aws.com post URL:** (if published)
4. Upload screenshots (decision screen, dashboard, trace viewer)
5. Click Submit

---

## Timeline (compressed, adjust freely)

| Days | Focus | Key Deliverable |
|---|---|---|
| 1–3 | Phase 1: interrupt gate + minimal Graph | `test_hitl_gate.py` passing |
| 3–5 | Phase 2: Builder Agent + workflow config | Chat → config generation working |
| 5–8 | Phase 3: Memory + real/mock tools | Learning loop working |
| 7–10 | Phase 4: UI (decision screen + dashboard) | All 4 screens rendering |
| 9–12 | Phase 5: AgentCore deploy + observability | Live demo link |
| 12–13 | Phase 6: Video + builder post | Video recorded, post published |
| 14 | Submit | Devpost submission finalized |

**Hard deadline: Sep 14, 2026, 5:00pm PDT**

---

## Emergency Fallback Plan

If things go wrong near deadline, what to cut:

| Priority | Keep | Cut |
|---|---|---|
| P0 (must have) | Interrupt gate + Graph with mock tools + decision screen | — |
| P1 (high value) | Builder Agent chat + dashboard | Real MCP connections |
| P2 (bonus) | AgentCore deploy + live link | AgentCore Browser |
| P3 (nice to have) | Memory learning loop | Second demo workflow |
| P4 (bonus) | builder.aws.com post | Trace viewer UI |

A working local demo with mock tools + the interrupt gate + a clean video beats a half-broken cloud deployment every time.
