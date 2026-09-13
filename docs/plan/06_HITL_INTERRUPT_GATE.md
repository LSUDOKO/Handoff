# Handoff — Human-in-the-Loop Interrupt Gate

## Why This Is the Most Important File

The hackathon brief says: **"the agent runs autonomously and only surfaces when there's a real decision to make."**

The interrupt gate is that sentence, implemented as code. It is:
- The feature the sponsor asked for
- The feature judges will look for
- The feature that separates "clever demo" from "winning submission"
- The thing you build FIRST and demo MOST PROMINENTLY

---

## How It Works (End-to-End Flow)

```
Agent processing items in a loop
        │
        ├─ Item 1: teammate request, confidence 0.95
        │   → submit_action(action="file_ticket", confidence=0.95)
        │   → Hook checks: 0.95 >= 0.7? YES → auto-execute ✅
        │
        ├─ Item 2: newsletter, confidence 0.99
        │   → submit_action(action="archive", confidence=0.99)
        │   → Hook checks: 0.99 >= 0.7? YES → auto-execute ✅
        │
        ├─ Item 3: unknown vendor, confidence 0.3
        │   → submit_action(action="??", confidence=0.3, force_interrupt=True)
        │   → Hook checks: 0.3 >= 0.7? NO → event.interrupt() 🔴
        │   │
        │   │  ┌─────────────────────────────────────────────┐
        │   │  │          AGENT LOOP PAUSES HERE              │
        │   │  │                                              │
        │   │  │  Interrupt payload sent to UI/notification:  │
        │   │  │  • Email from: unknown@vendor.com            │
        │   │  │  • Subject: "Partnership opportunity"        │
        │   │  │  • Agent's reasoning: "Unknown sender,       │
        │   │  │    could be spam or legitimate business"     │
        │   │  │  • Confidence: 30%                           │
        │   │  │  • Options: [Reply] [Archive] [File ticket]  │
        │   │  │             [Skip]                           │
        │   │  │                                              │
        │   │  │  Human clicks: [Archive]                     │
        │   │  └─────────────────────────────────────────────┘
        │   │
        │   ▼ resume with decision
        │   → execute "archive" action ✅
        │   → Learning Agent stores: "vendor@vendor.com → archive"
        │
        ├─ Item 4: continues processing...
```

---

## Implementation: Three Layers

### Layer 1: The Hook (registers on the executor agent)

```python
# graph/hooks/hitl.py

from strands.hooks import BeforeToolCallEvent
from datetime import datetime
import uuid
import json

# Tools that ALWAYS require human approval
ALWAYS_GATED = {"delete_item", "send_message"}

# Tools that are gated conditionally (based on confidence)
CONDITIONALLY_GATED = {"submit_action", "create_ticket", "draft_reply"}

# Confidence threshold — below this, interrupt
CONFIDENCE_THRESHOLD = 0.7


def register_hitl_gate(agent, on_interrupt_callback=None):
    """Register the human-in-the-loop interrupt gate on an agent.
    
    Args:
        agent: The Strands Agent to gate
        on_interrupt_callback: Optional function called when an interrupt fires.
            Used to push the decision to the UI/notification system.
    """
    
    @agent.hooks.add(BeforeToolCallEvent)
    def decision_gate(event: BeforeToolCallEvent):
        tool_name = event.tool_use.get("name", "")
        tool_input = event.tool_use.get("input", {})
        
        # Determine if this call should be gated
        should_interrupt = False
        reason = ""
        
        if tool_name in ALWAYS_GATED:
            should_interrupt = True
            reason = f"Tool '{tool_name}' always requires human approval"
        
        elif tool_name in CONDITIONALLY_GATED:
            confidence = tool_input.get("confidence", 1.0)
            force = tool_input.get("force_interrupt", False)
            
            if force:
                should_interrupt = True
                reason = "Agent flagged this item as requiring human judgment"
            elif confidence < CONFIDENCE_THRESHOLD:
                should_interrupt = True
                reason = f"Confidence ({confidence:.0%}) below threshold ({CONFIDENCE_THRESHOLD:.0%})"
        
        if should_interrupt:
            interrupt_id = str(uuid.uuid4())
            
            payload = {
                "interrupt_id": interrupt_id,
                "timestamp": datetime.now().isoformat(),
                "tool": tool_name,
                "reason": reason,
                "item": {
                    "summary": tool_input.get("summary", "No summary"),
                    "sender": tool_input.get("sender", "Unknown"),
                    "subject": tool_input.get("subject", ""),
                    "snippet": tool_input.get("snippet", ""),
                },
                "agent_analysis": {
                    "suggested_action": tool_input.get("action", ""),
                    "confidence": tool_input.get("confidence", 0),
                    "reasoning": tool_input.get("reasoning", ""),
                },
                "options": tool_input.get("options", [
                    "approve_suggested",
                    "archive",
                    "reply",
                    "file_ticket",
                    "skip"
                ]),
            }
            
            # Notify the UI/notification system
            if on_interrupt_callback:
                on_interrupt_callback(payload)
            
            # PAUSE THE AGENT LOOP
            event.interrupt(
                reason=reason,
                data=payload
            )
```

### Layer 2: The Notification (pushes to user)

When an interrupt fires, the user needs to know. Three channels:

```python
# tools/notify.py

from strands import tool
import httpx
import json

@tool
def notify_decision_needed(interrupt_payload: dict, 
                            channel: str = "slack") -> dict:
    """Notify the user that a decision is needed.
    
    Sends a notification via the configured channel with a link
    to the decision screen.
    """
    interrupt_id = interrupt_payload["interrupt_id"]
    summary = interrupt_payload["item"]["summary"]
    
    decision_url = f"{UI_BASE_URL}/decide/{interrupt_id}"
    
    if channel == "slack":
        message = (
            f"🔔 *Handoff needs your input*\n"
            f"Item: {summary}\n"
            f"Reason: {interrupt_payload['reason']}\n"
            f"<{decision_url}|Make your decision>"
        )
        # Post to Slack webhook
        httpx.post(SLACK_WEBHOOK_URL, json={"text": message})
    
    elif channel == "email":
        # Send via SNS/SES
        pass
    
    return {"notified": True, "channel": channel, "url": decision_url}
```

### Layer 3: The Decision Screen (where the human acts)

See `07_UI_AND_FRONTEND.md` for the full UI. Key requirements:
- ONE screen. No navigation.
- Shows: item summary, agent's reasoning, confidence bar, suggested action.
- Buttons: each option is one click.
- Optional: note field for context.
- POST to `/decide/{interrupt_id}` → resumes the agent.

---

## Resume Flow (after human decides)

```python
# When the human clicks a button on the decision screen:

async def resume_workflow(interrupt_id: str, decision: UserDecision):
    """Resume a paused workflow with the human's decision."""
    
    # 1. Resume the Strands graph
    result = graph.resume(
        interrupt_id=interrupt_id,
        decision={
            "action": decision.chosen_action,
            "approved": True,
            "note": decision.user_note,
            "decided_by": "human",
            "timestamp": decision.timestamp.isoformat()
        }
    )
    
    # 2. Log the decision to audit trail
    await write_audit_entry(AuditEntry(
        run_id=current_run_id,
        workflow_id=current_workflow_id,
        timestamp=decision.timestamp,
        action=decision.chosen_action,
        item_id=interrupt_id,
        decision_by="human",
        details={"note": decision.user_note}
    ))
    
    # 3. Trigger the Learning Agent
    learner_agent(f"""
        The user just made a decision:
        - Item: {interrupt_payload['item']['summary']}
        - Sender: {interrupt_payload['item']['sender']}
        - Decision: {decision.chosen_action}
        - Note: {decision.user_note}
        
        Analyze this decision and store a preference so I can
        handle similar items automatically next time.
    """)
    
    return result
```

---

## Testing the Gate

```python
# tests/test_hitl_gate.py

class TestHITLGate:
    
    def test_high_confidence_auto_executes(self):
        """Actions with confidence >= 0.7 execute without interruption."""
        agent = create_test_agent_with_gate()
        result = agent("Process this email: clear teammate request, confidence 0.95, action file_ticket")
        assert "executed" in str(result)
        # No interrupt should have fired
    
    def test_low_confidence_interrupts(self):
        """Actions with confidence < 0.7 trigger an interrupt."""
        agent = create_test_agent_with_gate()
        # This should raise an interrupt, not execute
        with pytest.raises(InterruptException) as exc_info:
            agent("Process this email: unknown sender, confidence 0.3, action unclear")
        assert exc_info.value.data["reason"] == "human_approval_required"
    
    def test_force_interrupt_always_gates(self):
        """force_interrupt=True always triggers regardless of confidence."""
        agent = create_test_agent_with_gate()
        with pytest.raises(InterruptException):
            agent("Process: force_interrupt=True, confidence 0.99")
    
    def test_always_gated_tools_always_interrupt(self):
        """Tools in ALWAYS_GATED fire the interrupt regardless."""
        agent = create_test_agent_with_gate()
        with pytest.raises(InterruptException):
            agent("Delete this item")
    
    def test_interrupt_payload_complete(self):
        """Interrupt payload contains all required fields."""
        # Trigger interrupt and capture payload
        payload = capture_interrupt_payload(...)
        assert "interrupt_id" in payload
        assert "item" in payload
        assert "summary" in payload["item"]
        assert "options" in payload
        assert "agent_analysis" in payload
        assert "reasoning" in payload["agent_analysis"]
    
    def test_resume_executes_chosen_action(self):
        """After resume with decision, the chosen action executes."""
        # 1. Trigger interrupt
        # 2. Resume with decision {"action": "archive"}
        # 3. Assert archive action was executed
        pass
    
    def test_resume_triggers_learning(self):
        """After resume, the Learning Agent is called to store preference."""
        # 1. Trigger interrupt
        # 2. Resume with decision
        # 3. Assert Learning Agent was invoked
        # 4. Assert preference was stored in Memory
        pass
```

---

## What Judges Will Look For (and how we deliver it)

| Judge expectation | How Handoff delivers |
|---|---|
| "Only surfaces when there's a real decision" | Confidence threshold: auto-handle clear cases, interrupt ambiguous ones |
| "Runs autonomously" | Background cron trigger on AgentCore Runtime |
| "Non-trivial Strands usage" | BeforeToolCallEvent hook + event.interrupt() + Graph resume |
| "Human-in-the-loop" | Full loop: interrupt → notify → decide → resume → learn |
| "Demonstrates working project" | Live demo: 5 auto, 3 interrupted, 1 decided on camera |
