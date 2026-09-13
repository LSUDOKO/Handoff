# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Completer node — close the run out honestly and tell someone."""

from __future__ import annotations

from datetime import UTC, datetime

from strands import tool

from handoff import events
from handoff.models import AuditEntry, DecidedBy
from handoff.runtime import current_run
from handoff.store import get_store
from handoff.tools.notify import send_notification


@tool
def finalize_run(summary: str, auto_count: int = -1, interrupt_count: int = -1) -> dict:
    """Close out the workflow run: write the audit entry and notify the user.

    Args:
        summary: Two or three sentences on what happened this run. Lead with
            what was done autonomously, then what needed a human.
        auto_count: How many items you handled without asking. Leave at -1 to
            use the count the runtime recorded.
        interrupt_count: How many items you escalated. Leave at -1 to use the
            runtime's count.

    Returns:
        The run summary, the final counts, and where the notification went.
    """
    ctx = current_run()
    if ctx is None:
        return {
            "summary": summary,
            "auto_count": max(auto_count, 0),
            "interrupt_count": max(interrupt_count, 0),
            "notified": False,
        }

    auto = ctx.auto_count if auto_count < 0 else auto_count
    human = ctx.human_count if interrupt_count < 0 else interrupt_count
    memory = ctx.memory_count

    store = get_store()
    store.write_audit(
        AuditEntry(
            run_id=ctx.run_id,
            workflow_id=ctx.workflow_id,
            action="run_completed",
            item_id=ctx.run_id,
            decision_by=DecidedBy.AGENT,
            details={
                "summary": summary,
                "auto_count": auto,
                "human_count": human,
                "memory_count": memory,
            },
        )
    )

    channel = "console"
    message = summary
    if ctx.workflow is not None:
        channel = ctx.workflow.completion.notify
        message = ctx.workflow.completion.message.format(
            auto_count=auto,
            interrupt_count=human,
            memory_count=memory,
            summary=summary,
        )

    notified = send_notification(
        message=message,
        channel=channel,
        target=ctx.workflow.completion.channel if ctx.workflow else "",
    )

    ctx.notes.append(summary)
    events.emit(ctx.run_id, "note", summary)

    return {
        "summary": summary,
        "auto_count": auto,
        "interrupt_count": human,
        "memory_count": memory,
        "notified": notified.get("sent", False),
        "channel": channel,
        "finished_at": datetime.now(UTC).isoformat(),
    }
