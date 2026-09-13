# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Bedrock AgentCore Runtime entrypoint.

One handler, four kinds of event. AgentCore gives Handoff what it actually
needs from a deployment target: serverless background execution, session
isolation per run, and long-running invocations — a workflow that is paused on
a human decision might not resume for hours.

Run locally with ``python -m handoff.app`` (serves on :8080), or deploy with
``infra/deploy_agentcore.py``.
"""

from __future__ import annotations

from typing import Any

from handoff import config
from handoff.agents.executor import run_workflow, submit_decision
from handoff.store import get_store
from handoff.tools.workflow_store import seed_examples

config.configure_observability()

try:
    from bedrock_agentcore import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()
except ImportError:  # pragma: no cover - only when the SDK isn't installed
    app = None


def handle(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Dispatch one AgentCore invocation.

    Event shapes:
        {"type": "tick", "workflow_id": "..."}      scheduled run (EventBridge)
        {"type": "webhook", "workflow_id", "payload"}  signal-triggered run
        {"type": "decide", "interrupt_id", "action", "note"}  human answered
        {"type": "build", "message": "..."}         a turn with the Builder
        {"type": "status"}                          health + counters
    """
    kind = (event or {}).get("type", "tick")

    if kind in ("tick", "webhook", "run"):
        workflow_id = event.get("workflow_id", "inbox-triage-morning")
        seed_examples()
        trigger = "cron" if kind == "tick" else "webhook"
        return dict(run_workflow(workflow_id, trigger, event.get("payload")))

    if kind in ("decide", "resume"):
        interrupt_id = event.get("interrupt_id", "")
        action = event.get("action") or (event.get("decision") or {}).get("action", "")
        note = event.get("note") or (event.get("decision") or {}).get("note", "")
        if not interrupt_id or not action:
            return {"error": "decide requires 'interrupt_id' and 'action'"}
        return dict(submit_decision(interrupt_id, action, note))

    if kind == "build":
        from handoff.agents.builder import BuilderSession

        message = event.get("message", "")
        if not message:
            return {"error": "build requires a 'message'"}
        return BuilderSession().send(message)

    if kind == "status":
        store = get_store()
        return {
            "ok": True,
            "settings": config.settings_summary(),
            "stats": store.stats(),
            "pending": [p.model_dump(mode="json") for p in store.pending_interrupts()],
        }

    return {"error": f"Unknown event type '{kind}'"}


if app is not None:

    @app.entrypoint
    def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
        return handle(event, context)


def main() -> None:
    if app is None:
        raise SystemExit(
            "bedrock-agentcore is not installed. Install it with:\n"
            "    pip install bedrock-agentcore\n"
            "Or run the local UI instead: python scripts/run_local.py --serve"
        )
    app.run()


if __name__ == "__main__":
    main()
