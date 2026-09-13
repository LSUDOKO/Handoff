# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The gated action tool.

``submit_action`` is the only tool in the executor that changes anything in the
outside world, which is what makes it the right chokepoint for the human gate.
The gating itself lives in ``handoff.graph.hooks.hitl`` — by the time this
function body runs, either the agent was confident enough to proceed or a human
has already chosen the action it is about to take.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from strands import tool

from handoff import config, events
from handoff.models import AuditEntry, DecidedBy
from handoff.runtime import current_run
from handoff.store import get_store

#: Maps a decision to the MCP call that carries it out.
ACTION_ROUTES: dict[str, tuple[str, str]] = {
    "file_ticket": ("linear", "create_issue"),
    "archive": ("gmail", "archive"),
    "draft_reply": ("gmail", "create_draft"),
    "reply": ("gmail", "create_draft"),
    "label": ("gmail", "add_label"),
    "notify": ("slack", "post_message"),
}


def _execute(action: str, item_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Carry out one action, through MCP or against the mock."""
    route = ACTION_ROUTES.get(action)
    if route is None:
        return {"status": "noop", "detail": f"No route for action '{action}'"}

    server, operation = route
    if config.USE_MOCK_TOOLS:
        return {
            "status": "executed",
            "detail": f"{server}.{operation} on {item_id}",
            "mock": True,
        }

    from handoff.mcp.servers import call_mcp_tool

    result = call_mcp_tool(server, operation, {"id": item_id, **params})
    return {"status": "executed", "detail": f"{server}.{operation}", "result": result}


@tool
def submit_action(
    action: str,
    item_id: str,
    confidence: float,
    reasoning: str,
    category: str = "",
    summary: str = "",
    sender: str = "",
    subject: str = "",
    snippet: str = "",
    options: list[str] | None = None,
    force_interrupt: bool = False,
    applied_preference: str = "",
) -> dict:
    """Act on one item. Gated: below the confidence threshold, or with
    force_interrupt=true, a human decides instead of you.

    Args:
        action: "file_ticket" | "archive" | "draft_reply" | "skip".
        item_id: Id from fetch_unread_emails.
        confidence: 0.0-1.0. Be honest; low routes to a human.
        reasoning: One or two sentences. If unsure, say exactly what is unclear.
        category: "teammate_request" | "newsletter" | "manager" | "automated" | "ambiguous".
        summary: Optional one-liner; defaults to the subject.
        sender: Optional; only if the item wasn't fetched this run.
        subject: Optional; same.
        snippet: Optional; same.
        options: Optional choices to offer the human.
        force_interrupt: True when it needs human judgement regardless.
        applied_preference: Set automatically when a learned rule applied.
    """
    ctx = current_run()
    if ctx is not None and ctx.is_deferred(item_id):
        # The gate set this one aside for a human. Nothing happens to it now;
        # finish_batch will apply whatever the person decides.
        known = ctx.item(item_id)
        events.emit(
            ctx.run_id, "deferred",
            f"Not sure about \"{known.get('subject', item_id)}\" ({confidence:.0%}) — setting it aside for you",
            item_id=item_id, confidence=confidence, reasoning=reasoning,
        )
        return {"item_id": item_id, "status": "deferred", "decided_by": "pending_human"}

    known = ctx.item(item_id) if ctx is not None else {}
    sender = sender or str(known.get("sender", ""))
    subject = subject or str(known.get("subject", ""))
    snippet = snippet or str(known.get("snippet", ""))
    summary = summary or (
        f"{subject} — from {known.get('sender_name') or sender}" if subject else item_id
    )

    if confidence >= 1.0 and not force_interrupt:
        # The gate rewrites confidence to 1.0 when a human resolves an interrupt.
        decided_by = DecidedBy.HUMAN
    elif applied_preference:
        # Handled automatically *because* the user answered this once before.
        # Counted separately: these are the interruptions that didn't happen.
        decided_by = DecidedBy.MEMORY
    else:
        decided_by = DecidedBy.AGENT

    # The hook rewrites `confidence` to 1.0 and stamps `decided_by` when a
    # human resolves an interrupt, so trust that marker when it is present.
    if isinstance(options, dict):  # defensive: some models send an object
        options = list(options.values())

    if action in {"skip", "none", "ignore"}:
        outcome = {"status": "skipped", "detail": "No action taken"}
    else:
        outcome = _execute(
            action,
            item_id,
            {"summary": summary, "subject": subject, "sender": sender},
        )

    record = {
        "item_id": item_id,
        "action": action,
        "status": outcome.get("status", "executed"),
        "detail": outcome.get("detail", ""),
        "confidence": confidence,
        "decided_by": decided_by.value,
        "applied_preference": applied_preference,
        "category": category,
        "summary": summary,
        "reasoning": reasoning,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if ctx is not None:
        if decided_by is DecidedBy.HUMAN:
            ctx.human_actions.append(record)
        elif decided_by is DecidedBy.MEMORY:
            ctx.memory_actions.append(record)
        else:
            ctx.auto_actions.append(record)

        verb = {"file_ticket": "Filed a ticket for", "archive": "Archived", "draft_reply": "Drafted a reply to",
                "skip": "Left alone", "post_to_slack": "Posted to Slack"}.get(action, f"{action} on")
        why = " (a rule you set)" if decided_by is DecidedBy.MEMORY else ""
        events.emit(
            ctx.run_id, "memory" if decided_by is DecidedBy.MEMORY else "acted",
            f"{verb} \"{subject or item_id}\"{why} — {confidence:.0%} sure",
            item_id=item_id, action=action, confidence=confidence, decided_by=decided_by.value,
        )

    if ctx is not None and decided_by is not DecidedBy.HUMAN:
        # Human-decided actions are logged once, by the gate's on_decision
        # callback, which knows what the agent had suggested and what the
        # person chose instead. Writing a second row here would double-count
        # every decision — and would miss the ones where the human said "skip"
        # and this tool never ran at all.
        get_store().write_audit(
            AuditEntry(
                run_id=ctx.run_id,
                workflow_id=ctx.workflow_id,
                action=action,
                item_id=item_id,
                decision_by=decided_by,
                confidence=confidence,
                details={
                    "summary": summary,
                    "reasoning": reasoning,
                    "category": category,
                    "status": record["status"],
                    "detail": record["detail"],
                    "applied_preference": applied_preference,
                },
            )
        )

    # Return only what the model needs to continue. Echoing the reasoning and
    # summary back into its context costs tokens on every later turn.
    return {
        "item_id": item_id,
        "action": action,
        "status": record["status"],
        "decided_by": decided_by.value,
    }


@tool
def finish_batch() -> dict:
    """Call once, after every item has had a submit_action. If any items were
    set aside for a human, this is where they are asked — all at once — and
    where their answers are carried out.
    """
    ctx = current_run()
    if ctx is None or not ctx.deferred:
        return {"deferred": 0, "decided": 0, "note": "Nothing needed a human this run."}

    decided: list[dict[str, Any]] = []
    events.emit(ctx.run_id, "decided", f"Applying your {len(ctx.batch_decisions)} decision(s)")
    for item_id, decision in list(ctx.batch_decisions.items()):
        payload = ctx.deferred.get(item_id)
        known = ctx.item(item_id)
        action = decision.chosen_action
        if action in {"skip", "ignore", "none", "do_nothing"}:
            outcome = {"status": "skipped", "detail": "Left alone by the human"}
        else:
            outcome = _execute(
                action,
                item_id,
                {
                    "summary": payload.item.summary if payload else "",
                    "subject": known.get("subject", ""),
                    "sender": known.get("sender", ""),
                },
            )
        record = {
            "item_id": item_id,
            "action": action,
            "status": outcome.get("status", "executed"),
            "detail": outcome.get("detail", ""),
            "confidence": 1.0,
            "decided_by": DecidedBy.HUMAN.value,
            "note": decision.user_note,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        ctx.human_actions.append(record)
        decided.append(record)
        events.emit(
            ctx.run_id, "acted",
            f"You chose {action.replace('_', ' ')} for \"{known.get('subject', item_id)}\" — done",
            item_id=item_id, action=action, decided_by="human",
        )

    count = len(ctx.deferred)
    ctx.deferred.clear()
    ctx.batch_decisions.clear()
    return {"deferred": count, "decided": len(decided), "actions": [
        {"item_id": r["item_id"], "action": r["action"], "status": r["status"]} for r in decided
    ]}
