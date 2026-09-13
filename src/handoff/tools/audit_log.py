# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Reading the audit trail.

Writes happen inside ``submit_action`` and ``finalize_run``, where the facts
are; this module is the read side, used by the UI and by the completer agent
when it needs to summarise what it just did.
"""

from __future__ import annotations

from strands import tool

from handoff.models import AuditEntry
from handoff.store import get_store


def write_audit_entry(entry: AuditEntry) -> AuditEntry:
    return get_store().write_audit(entry)


@tool
def read_audit_log(run_id: str = "", limit: int = 25) -> list[dict]:
    """Read recent entries from the audit trail.

    Args:
        run_id: Restrict to one run. Leave empty for the most recent activity
            across all workflows.
        limit: How many entries to return, newest first.

    Returns:
        Each entry's timestamp, action, item, who decided it, and details.
    """
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "run_id": e.run_id,
            "workflow_id": e.workflow_id,
            "action": e.action,
            "item_id": e.item_id,
            "decision_by": e.decision_by.value,
            "confidence": e.confidence,
            "details": e.details,
        }
        for e in get_store().list_audit(run_id or None, limit)
    ]
