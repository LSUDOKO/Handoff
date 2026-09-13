# Handoff — Tools & MCP Integration

## Tool Hierarchy

Handoff's tools are organized in three tiers:

### Tier 1: Core Custom Tools (build these — required)
These are `@tool`-decorated Python functions that make the core loop work.

| Tool | Purpose | Gated? |
|---|---|---|
| `check_trigger` | Validates trigger condition | No |
| `fetch_unread_emails` | Gets emails (mock or MCP) | No |
| `classify_email` | LLM classifies an item | No |
| `submit_action` | Executes action on item | **YES — interrupt gate** |
| `finalize_run` | Writes audit log + summary | No |
| `discover_mcp_tools` | Lists available MCP servers | No |
| `validate_workflow` | Validates workflow config | No |
| `preview_workflow` | Readable workflow preview | No |
| `store_user_preference` | Writes to Memory | No |
| `recall_preferences` | Reads from Memory | No |

### Tier 2: MCP Server Tools (connect these — high value)
These are external MCP servers that provide real-world tool access:

| MCP Server | Actions | Demo Priority |
|---|---|---|
| **Gmail** | search_threads, get_message, archive, create_draft, send | HIGH (primary demo) |
| **Linear** | create_issue, update_issue, search_issues | HIGH (primary demo) |
| **Slack** | post_message, read_channel | MEDIUM (completion notify) |
| **GitHub** | list_prs, create_issue, review_pr | LOW (stretch) |

### Tier 3: AgentCore Services (use these — strengthens score)
These are AWS-managed services accessed as agent capabilities:

| Service | Usage |
|---|---|
| **AgentCore Browser** | Web scraping for competitor-monitoring workflow |
| **AgentCore Code Interpreter** | Data processing for report-generation workflows |
| **AgentCore Gateway** | Expose custom Lambda/API as agent tools |

---

## Mock Tools Strategy (for reliable demo)

**Critical insight:** a flaky demo kills your chances. Build mock versions of every tool FIRST, then swap in real MCP connections if time permits.

### Mock email data (`tools/mock_data.py`)

```python
MOCK_EMAILS = [
    {
        "email_id": "msg_001",
        "sender": "alice@team.com",
        "sender_name": "Alice Chen",
        "subject": "Need API review by Thursday",
        "snippet": "Can you review the payments API PR #247? It's blocking the v2.1 release. I've tagged the specific files that changed.",
        "timestamp": "2026-09-12T07:23:00Z",
        "labels": ["team", "engineering"],
        "thread_length": 1
    },
    {
        "email_id": "msg_002",
        "sender": "newsletter@techcrunch.com",
        "sender_name": "TechCrunch Daily",
        "subject": "TC Daily: AI Agents Are Eating Software",
        "snippet": "Today's top stories: AWS launches new agent framework, Google responds with...",
        "timestamp": "2026-09-12T06:00:00Z",
        "labels": ["newsletter", "promotions"],
        "thread_length": 1
    },
    {
        "email_id": "msg_003",
        "sender": "boss@company.com",
        "sender_name": "Jordan Kim (Manager)",
        "subject": "Quick sync on Q3 targets",
        "snippet": "Let's discuss the pipeline numbers before the board deck. Free at 2pm today?",
        "timestamp": "2026-09-12T08:15:00Z",
        "labels": ["manager", "important"],
        "thread_length": 3
    },
    {
        "email_id": "msg_004",
        "sender": "partnerships@vendor.com",
        "sender_name": "Unknown — Vendor Corp",
        "subject": "Strategic partnership opportunity — time sensitive",
        "snippet": "We'd love to explore a strategic integration between our platforms. Our CEO is available next week for an intro call.",
        "timestamp": "2026-09-12T05:45:00Z",
        "labels": [],
        "thread_length": 1
    },
    {
        "email_id": "msg_005",
        "sender": "hr@company.com",
        "sender_name": "HR Team",
        "subject": "Updated PTO policy — action may be required",
        "snippet": "We've updated the PTO accrual policy effective Q4. Some changes may affect your remaining balance. Please review by Sept 20.",
        "timestamp": "2026-09-12T04:30:00Z",
        "labels": ["internal", "hr"],
        "thread_length": 1
    },
    {
        "email_id": "msg_006",
        "sender": "bob@team.com",
        "sender_name": "Bob Martinez",
        "subject": "Re: Sprint retro action items",
        "snippet": "I've drafted the post-mortem doc. Can you add the infra section? Link: ...",
        "timestamp": "2026-09-12T07:50:00Z",
        "labels": ["team"],
        "thread_length": 5
    },
    {
        "email_id": "msg_007",
        "sender": "security@github.com",
        "sender_name": "GitHub Security",
        "subject": "[handoff/handoff] Dependabot alert: lodash prototype pollution",
        "snippet": "A security vulnerability was detected in a dependency of your repository.",
        "timestamp": "2026-09-12T03:12:00Z",
        "labels": ["github", "automated"],
        "thread_length": 1
    },
    {
        "email_id": "msg_008",
        "sender": "cfo@company.com",
        "sender_name": "CFO Office",
        "subject": "FYI: Budget freeze through end of month",
        "snippet": "All non-essential purchases are paused until the monthly close. Exceptions require VP approval.",
        "timestamp": "2026-09-12T08:30:00Z",
        "labels": ["internal", "leadership"],
        "thread_length": 1
    }
]

# Expected classifications (for testing):
EXPECTED_CLASSIFICATIONS = {
    "msg_001": {"category": "teammate_request", "action": "file_ticket", "confidence": 0.95},
    "msg_002": {"category": "newsletter", "action": "archive", "confidence": 0.99},
    "msg_003": {"category": "manager", "action": "draft_reply", "confidence": 0.95},
    "msg_004": {"category": "ambiguous", "action": "interrupt", "confidence": 0.3},  # ← DECISION
    "msg_005": {"category": "ambiguous", "action": "interrupt", "confidence": 0.5},  # ← DECISION
    "msg_006": {"category": "teammate_request", "action": "file_ticket", "confidence": 0.9},
    "msg_007": {"category": "teammate_request", "action": "file_ticket", "confidence": 0.85},
    "msg_008": {"category": "ambiguous", "action": "interrupt", "confidence": 0.6},  # ← DECISION
}
```

### Why these specific emails matter for the demo:
- **msg_001, msg_006** — clear teammate requests → auto-filed as tickets (proves autonomy)
- **msg_002** — obvious newsletter → auto-archived (proves autonomy)
- **msg_003** — from manager → auto-draft reply (proves smart classification)
- **msg_004** — unknown vendor → INTERRUPT (the demo's money moment — is this spam or legit?)
- **msg_005** — internal but requires action → INTERRUPT (genuinely ambiguous)
- **msg_007** — automated alert → auto-filed (proves it handles non-human senders)
- **msg_008** — leadership FYI → INTERRUPT (important but unclear action needed)

**5 auto-handled, 3 interrupted = proves the agent is selective, not interrupting everything.**

---

## Connecting Real MCP Servers (if time permits)

### Gmail MCP
```bash
# Install the MCP server
npx @anthropic/gmail-mcp-server

# Or use the Strands MCP integration:
from strands.mcp import MCPClient

gmail = MCPClient(
    command="npx",
    args=["@anthropic/gmail-mcp-server"],
    env={"GMAIL_OAUTH_TOKEN": os.environ["GMAIL_OAUTH_TOKEN"]}
)
```

### Linear MCP
```bash
npx @linear/mcp-server

# Requires LINEAR_API_KEY
```

### Slack MCP
```bash
npx @anthropic/slack-mcp-server

# Requires SLACK_BOT_TOKEN
```

### Fallback if MCP auth is complex
Use the mock tools with a clear label in the demo:
> "In production, these connect to real Gmail, Linear, and Slack via MCP. For this demo, we're using synthetic data to show the workflow logic and the interrupt gate clearly."

Judges care about the *architecture* (MCP-based, swappable tools) more than whether you authenticated with real Gmail in a 5-minute demo.

---

## AgentCore Browser (for the second demo workflow)

The competitor-monitoring workflow uses AgentCore Browser:

```python
from strands import tool

@tool
def check_competitor_pricing(url: str) -> dict:
    """Navigate to a competitor's pricing page and extract current prices.
    
    Uses AgentCore Browser (Playwright/CDP) for real web interaction.
    """
    # AgentCore Browser provides a managed Chromium instance
    # browser = agentcore.browser.launch()
    # page = browser.new_page()
    # page.goto(url)
    # prices = page.query_selector_all(".pricing-card")
    # ...
    return {
        "url": url,
        "prices": [...],
        "changed": True,
        "diff": "Enterprise tier increased from $99 to $129/mo"
    }
```

---

## Tool Testing

```python
# tests/test_tools.py

def test_fetch_emails_returns_list():
    result = fetch_unread_emails(query="is:unread", max_results=10)
    assert isinstance(result, list)
    assert len(result) > 0
    assert "email_id" in result[0]
    assert "sender" in result[0]
    assert "subject" in result[0]

def test_classify_email_returns_category():
    email = MOCK_EMAILS[0]
    result = classify_email(email=email)
    assert "category" in result
    assert "confidence" in result
    assert result["confidence"] >= 0 and result["confidence"] <= 1

def test_submit_action_gated():
    """Low-confidence submit_action must trigger the interrupt gate."""
    # This is tested in test_hitl_gate.py
    pass
```
