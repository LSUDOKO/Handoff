# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Recording what happened inside a run, step by step.

The audit log answers "what did it do to my mail". This answers the question
you ask when the audit log surprises you: *why*. Every model turn and every
tool call, in order, with inputs, outputs, timings and token counts — so the
reasoning turn that led to a tool call sits directly above it.

It is a Strands ``HookProvider``, which means it observes the same event
stream the interrupt gate hooks into and needs no cooperation from the agents
themselves. Attach it to any agent and it records.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from strands.hooks import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from handoff.platform.models import Session, SessionStep, UsageRecord
from handoff.store import get_store

#: Tool results longer than this are truncated in the trace. The full result
#: still reached the model; this only bounds what we keep to look at.
MAX_OUTPUT = 4000


def _summarise(value: Any, limit: int = MAX_OUTPUT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except Exception:
            text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}\n… ({len(text) - limit} more characters)"


def _result_text(result: Any) -> tuple[str, str]:
    """Flatten a tool result into (text, status)."""
    if isinstance(result, dict):
        status = str(result.get("status", "ok"))
        content = result.get("content")
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and "text" in block
            ]
            if parts:
                return _summarise("\n".join(parts)), status
        return _summarise(result), status
    return _summarise(result), "ok"


class SessionRecorder(HookProvider):
    """Captures a run's steps. One per run; attach to every agent in it."""

    def __init__(self, run_id: str, workspace_id: str = "", workflow_id: str = "") -> None:
        self.session = Session(
            run_id=run_id, workspace_id=workspace_id, workflow_id=workflow_id
        )
        self._node = ""
        self._model_started: datetime | None = None
        self._persisted = False

    # -- HookProvider ------------------------------------------------------

    def register_hooks(self, registry: HookRegistry, **_: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model)
        registry.add_callback(AfterModelCallEvent, self._after_model)
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def bind(self, agent: Any, node: str = "") -> Any:
        """Attach to one agent, remembering which graph node it is.

        ``agent.add_hook`` takes a single callback and infers its event type
        from the signature; a provider registers many at once and so goes
        through the registry directly.
        """
        self._node = node or getattr(agent, "name", "")
        agent.hooks.add_hook(self)
        return agent

    # -- steps -------------------------------------------------------------

    def _add(self, **kwargs: Any) -> SessionStep:
        step = SessionStep(index=len(self.session.steps), **kwargs)
        self.session.steps.append(step)
        return step

    def _node_of(self, event: Any) -> str:
        agent = getattr(event, "agent", None)
        return getattr(agent, "name", "") or self._node

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        self._model_started = datetime.now(UTC)

    def _after_model(self, event: AfterModelCallEvent) -> None:
        started = self._model_started
        duration = (
            int((datetime.now(UTC) - started).total_seconds() * 1000) if started else 0
        )
        self._model_started = None

        response = getattr(event, "stop_response", None)
        stop_reason = getattr(response, "stop_reason", "") if response else ""
        message = getattr(response, "message", None) if response else None

        text = ""
        if isinstance(message, dict):
            text = "\n".join(
                block.get("text", "")
                for block in message.get("content", []) or []
                if isinstance(block, dict) and "text" in block
            )

        exception = getattr(event, "exception", None)
        self._add(
            kind="model",
            node=self._node_of(event),
            name=str(stop_reason or "response"),
            output=_summarise(text) or (f"error: {exception}" if exception else ""),
            status="error" if exception else "ok",
            duration_ms=duration,
        )
        self._record_usage(event)

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        # Recorded on completion instead, so the step carries its result. The
        # gate may cancel or suspend this call in between.
        pass

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        tool_use = event.tool_use or {}
        output, status = _result_text(event.result)
        exception = getattr(event, "exception", None)
        cancel = getattr(event, "cancel_message", None)

        if exception:
            output, status = f"error: {exception}", "error"
        elif cancel:
            output, status = str(cancel), "cancelled"

        duration = getattr(event, "duration", None)
        self._add(
            kind="tool",
            node=self._node_of(event),
            name=tool_use.get("name", "tool"),
            input=tool_use.get("input", {}) or {},
            output=output,
            status=status,
            gated=bool(cancel),
            duration_ms=int((duration or 0) * 1000),
        )

    # -- usage -------------------------------------------------------------

    def _record_usage(self, event: AfterModelCallEvent) -> None:
        """Bank the token counts this model call reported.

        Strands puts them on the assistant message, at
        ``stop_response.message["metadata"]["usage"]`` — not on the response
        object itself. The other paths are kept as fallbacks because the
        OpenAI-compatible provider has reported usage on the response in the
        past, and a missing count should cost a record, not raise.
        """
        response = getattr(event, "stop_response", None)
        if response is None:
            return

        message = getattr(response, "message", None) or {}
        metadata = message.get("metadata") or {} if isinstance(message, dict) else {}

        usage = metadata.get("usage")
        if not usage:
            for holder in (response, getattr(response, "metrics", None)):
                usage = getattr(holder, "usage", None) or (
                    holder.get("usage") if isinstance(holder, dict) else None
                )
                if usage:
                    break
        if not usage:
            return

        def field(*names: str) -> int:
            for name in names:
                value = (
                    usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
                )
                if value:
                    return int(value)
            return 0

        from handoff import config

        record = UsageRecord(
            workspace_id=self.session.workspace_id,
            run_id=self.session.run_id,
            provider=config.active_provider(),
            model=config.active_model_id(),
            input_tokens=field("inputTokens", "input_tokens", "prompt_tokens"),
            output_tokens=field("outputTokens", "output_tokens", "completion_tokens"),
        )
        if record.total_tokens:
            get_store().usage.put(record, "usage_id")

    # -- persistence -------------------------------------------------------

    def save(self) -> Session:
        """Write the session. Safe to call more than once."""
        self.session.finished_at = datetime.now(UTC)
        get_store().sessions.put(self.session, "session_id")
        self._persisted = True
        return self.session
