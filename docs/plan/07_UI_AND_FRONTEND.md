# Handoff — UI & Frontend

## Tech Choice: FastAPI + HTMX + Jinja2
- No React/Vue/Svelte build step. Judges can run it immediately.
- HTMX gives dynamic behavior without JavaScript complexity.
- Clean, professional look with minimal CSS.
- Same stack as `aws-samples/sample-strands-agentcore-starter`.

## Four Screens

### Screen 1: Dashboard (`/`)
Shows workflow list, status, recent runs, and audit log.

```html
<!-- ui/templates/dashboard.html -->
<!DOCTYPE html>
<html>
<head>
    <title>Handoff — Dashboard</title>
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <header>
        <h1>⚡ Handoff</h1>
        <p class="tagline">You describe it. You hand it off. It runs.</p>
        <nav>
            <a href="/" class="active">Dashboard</a>
            <a href="/chat">Build Workflow</a>
        </nav>
    </header>
    
    <main>
        <section class="workflows">
            <h2>Your Workflows</h2>
            {% for workflow in workflows %}
            <div class="workflow-card">
                <div class="workflow-header">
                    <h3>{{ workflow.name }}</h3>
                    <span class="status {{ workflow.status }}">{{ workflow.status }}</span>
                </div>
                <p>{{ workflow.description }}</p>
                <div class="workflow-meta">
                    <span>⏰ {{ workflow.trigger.schedule }}</span>
                    <span>🔧 {{ workflow.mcp_tools | join(', ') }}</span>
                    <span>📊 Last run: {{ workflow.last_run }}</span>
                </div>
                <div class="workflow-actions">
                    <button hx-post="/workflow/{{ workflow.workflow_id }}/run" 
                            hx-swap="outerHTML">
                        ▶ Run Now
                    </button>
                    <a href="/trace/{{ workflow.last_run_id }}">View Trace</a>
                </div>
            </div>
            {% endfor %}
        </section>
        
        <section class="pending-decisions">
            <h2>🔔 Pending Decisions</h2>
            {% for decision in pending %}
            <a href="/decide/{{ decision.interrupt_id }}" class="decision-card">
                <strong>{{ decision.item.subject }}</strong>
                <p>{{ decision.reason }}</p>
                <span class="confidence">{{ (decision.agent_analysis.confidence * 100) | int }}% confidence</span>
            </a>
            {% endfor %}
        </section>
        
        <section class="audit-log">
            <h2>📋 Recent Activity</h2>
            <table>
                <tr><th>Time</th><th>Action</th><th>Item</th><th>Decided By</th></tr>
                {% for entry in audit_log %}
                <tr>
                    <td>{{ entry.timestamp }}</td>
                    <td>{{ entry.action }}</td>
                    <td>{{ entry.item_id }}</td>
                    <td>
                        {% if entry.decision_by == "agent" %}
                        🤖 Agent
                        {% else %}
                        👤 Human
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </table>
        </section>
    </main>
</body>
</html>
```

### Screen 2: Chat (Builder Agent) (`/chat`)
Chat interface for describing workflows in natural language.

```html
<!-- ui/templates/chat.html -->
<main class="chat-container">
    <div class="chat-header">
        <h2>Build a Workflow</h2>
        <p>Describe what you want automated in plain language.</p>
    </div>
    
    <div id="messages" class="chat-messages">
        <div class="message assistant">
            <p>Hi! I'm Handoff. Tell me what repetitive task you'd like automated.</p>
            <p>For example: <em>"Every weekday at 8am, triage my inbox. Real asks → 
            file as Linear tickets. Newsletters → archive. Anything ambiguous → ask me."</em></p>
        </div>
    </div>
    
    <div class="chat-input">
        <input type="text" id="user-input" 
               placeholder="Describe your workflow..."
               hx-post="/chat/send"
               hx-trigger="keyup[keyCode==13]"
               hx-target="#messages"
               hx-swap="beforeend"
               hx-include="this"
               name="message">
        <button hx-post="/chat/send" 
                hx-target="#messages" 
                hx-swap="beforeend"
                hx-include="#user-input">
            Send
        </button>
    </div>
</main>
```

### Screen 3: Decision Screen (`/decide/{interrupt_id}`) — THE MONEY SCREEN
This is the most important UI in the whole project. ONE screen, ONE decision.

```html
<!-- ui/templates/decision.html -->
<main class="decision-container">
    <div class="decision-header">
        <span class="badge">Decision Required</span>
        <h2>{{ payload.item.subject }}</h2>
    </div>
    
    <div class="decision-context">
        <div class="sender">
            <strong>From:</strong> {{ payload.item.sender }}
        </div>
        <div class="snippet">
            {{ payload.item.snippet }}
        </div>
    </div>
    
    <div class="agent-analysis">
        <h3>🤖 Agent's Analysis</h3>
        <p class="reasoning">{{ payload.agent_analysis.reasoning }}</p>
        
        <div class="confidence-bar">
            <label>Confidence: {{ (payload.agent_analysis.confidence * 100) | int }}%</label>
            <div class="bar">
                <div class="fill" style="width: {{ payload.agent_analysis.confidence * 100 }}%"></div>
            </div>
        </div>
        
        {% if payload.agent_analysis.suggested_action %}
        <p class="suggestion">
            Suggested: <strong>{{ payload.agent_analysis.suggested_action }}</strong>
        </p>
        {% endif %}
    </div>
    
    <div class="decision-actions">
        <h3>Your Decision</h3>
        
        <form hx-post="/decide/{{ payload.interrupt_id }}" hx-swap="innerHTML" hx-target="main">
            <div class="action-buttons">
                {% for option in payload.options %}
                <button type="submit" name="action" value="{{ option }}"
                        class="action-btn {{ 'suggested' if option == payload.agent_analysis.suggested_action }}">
                    {% if option == "archive" %}📥 Archive
                    {% elif option == "file_ticket" %}🎫 File Ticket
                    {% elif option == "reply" %}↩️ Reply
                    {% elif option == "draft_reply" %}✏️ Draft Reply
                    {% elif option == "skip" %}⏭️ Skip
                    {% elif option == "approve_suggested" %}✅ Approve Suggested
                    {% else %}{{ option }}
                    {% endif %}
                </button>
                {% endfor %}
            </div>
            
            <div class="note-field">
                <label for="note">Note (optional):</label>
                <input type="text" name="note" id="note" 
                       placeholder="Any context for this decision...">
            </div>
        </form>
    </div>
    
    <div class="decision-footer">
        <p class="learn-note">
            💡 Handoff will learn from this decision and handle similar items 
            automatically next time.
        </p>
    </div>
</main>
```

### Screen 4: Trace Viewer (`/trace/{run_id}`)
Shows the OTEL observability trace for a workflow run.

```html
<!-- ui/templates/trace.html -->
<main class="trace-container">
    <h2>Workflow Run: {{ run_id }}</h2>
    
    <div class="trace-timeline">
        {% for step in trace.steps %}
        <div class="trace-step {{ step.type }}">
            <div class="step-marker">
                {% if step.type == "auto" %}🤖
                {% elif step.type == "interrupt" %}🔔
                {% elif step.type == "human" %}👤
                {% endif %}
            </div>
            <div class="step-content">
                <strong>{{ step.tool }}</strong>
                <span class="step-time">{{ step.timestamp }}</span>
                <p>{{ step.description }}</p>
                {% if step.type == "interrupt" %}
                <div class="interrupt-detail">
                    <p>⏸️ Paused for human decision</p>
                    <p>Decision: {{ step.decision }}</p>
                </div>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>
    
    <div class="trace-summary">
        <h3>Summary</h3>
        <p>{{ trace.summary }}</p>
        <div class="stats">
            <span>Total items: {{ trace.total }}</span>
            <span>Auto-handled: {{ trace.auto_count }}</span>
            <span>Human decisions: {{ trace.interrupt_count }}</span>
            <span>Duration: {{ trace.duration }}s</span>
        </div>
    </div>
</main>
```

---

## CSS (keep it clean and professional)

```css
/* ui/static/styles.css */

:root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3a;
    --text: #e1e4ed;
    --text-secondary: #8b8fa3;
    --accent: #6366f1;
    --accent-hover: #818cf8;
    --success: #22c55e;
    --warning: #f59e0b;
    --danger: #ef4444;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}

header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 1rem 2rem;
    display: flex;
    align-items: center;
    gap: 2rem;
}

header h1 { font-size: 1.5rem; }
.tagline { color: var(--text-secondary); font-size: 0.9rem; }

nav a {
    color: var(--text-secondary);
    text-decoration: none;
    padding: 0.5rem 1rem;
    border-radius: 6px;
}
nav a.active, nav a:hover {
    color: var(--text);
    background: var(--border);
}

main { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }

/* Workflow cards */
.workflow-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
}

.status {
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8rem;
    font-weight: 600;
}
.status.active { background: #22c55e22; color: var(--success); }
.status.paused { background: #f59e0b22; color: var(--warning); }

/* Decision screen */
.decision-container {
    max-width: 600px;
    margin: 2rem auto;
}

.badge {
    background: var(--warning);
    color: #000;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 700;
}

.confidence-bar .bar {
    background: var(--border);
    border-radius: 4px;
    height: 8px;
    margin-top: 4px;
}
.confidence-bar .fill {
    background: var(--accent);
    border-radius: 4px;
    height: 100%;
    transition: width 0.3s;
}

.action-buttons {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin: 1rem 0;
}

.action-btn {
    padding: 0.75rem 1.5rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
    font-size: 1rem;
    transition: all 0.15s;
}
.action-btn:hover { border-color: var(--accent); }
.action-btn.suggested {
    border-color: var(--accent);
    background: #6366f122;
}

/* Chat */
.chat-messages {
    min-height: 400px;
    padding: 1rem;
}
.message {
    padding: 1rem;
    margin-bottom: 0.75rem;
    border-radius: 12px;
}
.message.assistant { background: var(--surface); }
.message.user { background: #6366f122; text-align: right; }

/* Trace */
.trace-step {
    display: flex;
    gap: 1rem;
    padding: 1rem 0;
    border-left: 2px solid var(--border);
    padding-left: 1.5rem;
    margin-left: 1rem;
}
.trace-step.interrupt { border-left-color: var(--warning); }
.trace-step.human { border-left-color: var(--success); }
```
