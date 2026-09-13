# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The agent workbench: run any agent on a prompt and watch it work.

The same narration the chat uses — a tool_start/tool_end pair per call and
text as it streams — on a channel per run, so the page can paint the run
live and the record survives for the history stack.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

from handoff import config, events
from handoff.chat.service import Narrator
from handoff.platform import agents_registry
from handoff.platform.models import AgentRun, CustomAgent, UsageRecord
from handoff.store import get_store

#: Which credential each tool leans on, for the preflight panel.
TOOL_CREDENTIALS: dict[str, list[str]] = {
    "fetch_unread_emails": ["gmail"],
    "get_email_body": ["gmail"],
    "submit_action": ["linear", "gmail"],
    "notify_user": ["slack"],
    "check_competitor_pricing": [],
    "read_audit_log": [],
}


def channel(run_id: str) -> str:
    return f"agent:{run_id}"


def preflight(agent: CustomAgent) -> list[dict[str, Any]]:
    """The credentials this agent's tools need, and whether each is connected."""
    from handoff.platform import credentials as creds

    wanted: list[str] = []
    for tool_name in agent.tools:
        for provider in TOOL_CREDENTIALS.get(tool_name, []):
            if provider not in wanted:
                wanted.append(provider)
    catalogue = {c["provider"]: c for c in creds.catalogue()}
    return [
        {
            "provider": provider,
            "label": catalogue.get(provider, {}).get("label", provider),
            "connected": bool(catalogue.get(provider, {}).get("connected")),
            "status": catalogue.get(provider, {}).get("status", "disconnected"),
        }
        for provider in wanted
    ]


def run(agent: CustomAgent, prompt: str) -> AgentRun:
    """Start a run on a worker thread; returns the record to follow."""
    store = get_store()
    record = AgentRun(
        agent_id=agent.agent_id,
        workspace_id=agent.workspace_id,
        prompt=prompt.strip(),
        model=agent.model_override or config.active_model_id(),
    )
    store.agent_runs.put(record, "run_id")
    threading.Thread(
        target=_execute, args=(agent, record), name=f"workbench-{record.run_id}", daemon=True
    ).start()
    return record


def _execute(agent: CustomAgent, record: AgentRun) -> None:
    store = get_store()
    chan = channel(record.run_id)
    narrator = Narrator(chan, turn=1)
    started = time.monotonic()
    text = ""

    def on_event(**kw: Any) -> None:
        nonlocal text
        data = kw.get("data")
        if isinstance(data, str) and data:
            text += data
            events.emit(chan, "delta", data, turn=1)

    events.emit(chan, "turn_start", "starting", turn=1)
    try:
        live = agents_registry.build(agent)
        live.callback_handler = on_event
        live.hooks.add_hook(narrator)
        result = live(record.prompt)
        metrics = getattr(result, "metrics", None)
        acc = getattr(metrics, "accumulated_usage", None) or {}
        record.input_tokens = int(acc.get("inputTokens", 0) or 0)
        record.output_tokens = int(acc.get("outputTokens", 0) or 0)
        record.result = text or str(result)
        record.status = "completed"
    except Exception as exc:
        record.error = str(exc)[:500]
        record.status = "failed"
        events.emit(chan, "error", record.error, turn=1)

    record.steps = narrator.steps
    record.duration_ms = int((time.monotonic() - started) * 1000)
    record.finished_at = datetime.now(UTC)
    store.agent_runs.put(record, "run_id")
    if record.input_tokens or record.output_tokens:
        store.usage.put(
            UsageRecord(
                workspace_id=record.workspace_id,
                run_id=record.run_id,
                provider=config.active_provider(),
                model=record.model,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
            ),
            "usage_id",
        )
    if record.status == "completed":
        events.emit(
            chan, "done", record.result, turn=1,
            usage={"input": record.input_tokens, "output": record.output_tokens},
            ms=record.duration_ms,
        )
