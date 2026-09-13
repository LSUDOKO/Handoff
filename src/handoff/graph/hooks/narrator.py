# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Narrate an agent's work onto the events bus, as it happens.

One hook, bound to any Strands ``Agent``, turns four SDK events into four
lines a page can paint: the node starting and finishing, and every tool call
starting and finishing with its timing and result. The chat uses it to draw
tool cards under a reply; the workflow runner binds one per graph node so
the orb can draw the graph filling in — the trigger, the executor and its
tool calls, the completer — from the same events the audit trail is built on.
"""

from __future__ import annotations

import json
import time
from typing import Any

from strands.hooks import (
    AfterInvocationEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from handoff import events

#: How much of a tool's output the feed carries. The full text is in the
#: session trace; this is for reading along, not archiving.
OUTPUT_LIMIT = 4000


def _result_text(result: Any) -> str:
    text = ""
    for block in (result or {}).get("content", []) or []:
        if isinstance(block, dict):
            if "text" in block:
                text += block["text"]
            elif "json" in block:
                text += json.dumps(block["json"], indent=2, default=str)
    return text


class Narrator(HookProvider):
    """Emits ``node_start``/``node_end`` and a ``tool_start``/``tool_end``
    pair for every tool call, on ``channel``.

    Args:
        channel: The events channel — ``chat:<id>`` for a chat turn, the run
            id for a workflow run.
        turn: The chat turn number, so a page can filter one reply's events.
        node: The graph node this agent is, when it is one.
    """

    def __init__(self, channel: str, turn: int = 0, node: str = "") -> None:
        self.channel = channel
        self.turn = turn
        self.node = node
        self.steps: list[dict[str, Any]] = []
        self._started: dict[str, float] = {}
        self._node_started = 0.0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._node_before)
        registry.add_callback(AfterInvocationEvent, self._node_after)
        registry.add_callback(BeforeToolCallEvent, self._before)
        registry.add_callback(AfterToolCallEvent, self._after)

    # -- node ------------------------------------------------------------------

    def _node_before(self, event: BeforeInvocationEvent) -> None:
        self._node_started = time.monotonic()
        events.emit(self.channel, "node_start", f"{self.node or 'agent'} starting", turn=self.turn, node=self.node)

    def _node_after(self, event: AfterInvocationEvent) -> None:
        ms = int((time.monotonic() - self._node_started) * 1000) if self._node_started else 0
        events.emit(self.channel, "node_end", f"{self.node or 'agent'} done", turn=self.turn, node=self.node, ms=ms)

    # -- tools -----------------------------------------------------------------

    def _before(self, event: BeforeToolCallEvent) -> None:
        use = event.tool_use or {}
        tool_id = str(use.get("toolUseId", ""))
        self._started[tool_id] = time.monotonic()
        events.emit(
            self.channel,
            "tool_start",
            f"calling {use.get('name')}",
            turn=self.turn,
            node=self.node,
            tool_id=tool_id,
            name=use.get("name", "tool"),
            input=use.get("input", {}),
        )

    def _after(self, event: AfterToolCallEvent) -> None:
        use = event.tool_use or {}
        tool_id = str(use.get("toolUseId", ""))
        ms = int((time.monotonic() - self._started.pop(tool_id, time.monotonic())) * 1000)
        result = event.result or {}
        status = "error" if getattr(event, "exception", None) or result.get("status") == "error" else "ok"
        if getattr(event, "cancel_message", None):
            status = "cancelled"
        step = {
            "tool_id": tool_id,
            "node": self.node,
            "name": use.get("name", "tool"),
            "input": use.get("input", {}),
            "output": _result_text(result)[:OUTPUT_LIMIT],
            "status": status,
            "ms": ms,
        }
        self.steps.append(step)
        events.emit(
            self.channel,
            "tool_end",
            f"{step['name']} {status}",
            turn=self.turn,
            node=self.node,
            tool_id=tool_id,
            name=step["name"],
            output=step["output"],
            status=status,
            ms=ms,
        )


def bind_graph_narrator(channel: str, agents: dict[str, Any]) -> list[Narrator]:
    """Attach one narrator per named graph node."""
    narrators: list[Narrator] = []
    for node, agent in agents.items():
        narrator = Narrator(channel, node=node)
        agent.hooks.add_hook(narrator)
        narrators.append(narrator)
    return narrators
