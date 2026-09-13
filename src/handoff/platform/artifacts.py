# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Things a run produced that are worth keeping.

A triage run's output is mostly side effects — a ticket filed, a draft saved.
But some workflows produce a *document*: a competitor pricing diff, a weekly
digest, a summary. Those go here, so they can be read later and linked from
the run that made them rather than living only in a Slack message.
"""

from __future__ import annotations

from strands import tool

from handoff.platform.models import Artifact
from handoff.runtime import current_run
from handoff.store import get_store

KINDS = {"text", "markdown", "json", "csv", "html"}


def save_artifact(
    name: str,
    content: str,
    kind: str = "markdown",
    run_id: str = "",
    workspace_id: str = "",
    produced_by: str = "",
) -> Artifact:
    artifact = Artifact(
        name=name,
        content=content,
        kind=kind if kind in KINDS else "text",
        run_id=run_id,
        workspace_id=workspace_id,
        produced_by=produced_by,
    )
    get_store().artifacts.put(artifact, "artifact_id")
    return artifact


@tool
def create_artifact(name: str, content: str, kind: str = "markdown") -> dict:
    """Save a document this run produced, so it can be read later.

    Use it for things worth keeping — a summary, a diff, a report. Not for
    every action you take; those are already in the audit trail.

    Args:
        name: A short title, e.g. "Competitor pricing — week of 9 Sep".
        content: The document itself.
        kind: "markdown", "text", "json", "csv" or "html".
    """
    ctx = current_run()
    artifact = save_artifact(
        name=name,
        content=content,
        kind=kind,
        run_id=ctx.run_id if ctx else "",
        workspace_id=getattr(ctx, "workspace_id", "") if ctx else "",
        produced_by="executor",
    )
    return {
        "artifact_id": artifact.artifact_id,
        "name": artifact.name,
        "kind": artifact.kind,
        "size": artifact.size,
    }
