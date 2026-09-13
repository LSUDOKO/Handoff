# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Per-run ambient context.

Strands ``@tool`` functions are plain Python functions with LLM-visible
signatures, so the run they belong to must not become a parameter — the model
would have to invent it. A context variable keeps ``run_id``/``workflow_id``
out of the tool schema while still letting ``submit_action`` and
``finalize_run`` write correctly-attributed audit entries.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from handoff.models import WorkflowConfig


@dataclass
class RunContext:
    run_id: str
    workflow_id: str
    workflow: WorkflowConfig | None = None
    #: Actions the agent carried out without asking anyone.
    auto_actions: list[dict[str, Any]] = field(default_factory=list)
    #: Actions that were carried out because a human chose them.
    human_actions: list[dict[str, Any]] = field(default_factory=list)
    #: Actions taken automatically *because a learned preference matched* —
    #: tracked separately because "interrupts that didn't happen this time" is
    #: the whole payoff of the learning loop.
    memory_actions: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Every item this run fetched, by id. Tools look details up here so the
    #: model only has to pass an id and its judgement — never re-type a
    #: subject line. Less text in tool arguments means fewer malformed JSON
    #: payloads, which is the difference between a run that finishes and one
    #: that dies six tool calls in on an open-weight model.
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Items the gate set aside for a human, keyed by item id. The executor
    #: keeps working through the batch; ``finish_batch`` raises one interrupt
    #: for all of them at the end, so the person gets one screen rather than
    #: one interruption per item.
    deferred: dict[str, Any] = field(default_factory=dict)
    #: The human's answers for the deferred items, filled in on resume.
    batch_decisions: dict[str, Any] = field(default_factory=dict)

    def remember_items(self, items: list[dict[str, Any]], key: str = "email_id") -> None:
        for item in items:
            item_id = str(item.get(key) or item.get("id") or "")
            if item_id:
                self.items[item_id] = dict(item)

    def item(self, item_id: str) -> dict[str, Any]:
        return self.items.get(str(item_id), {})

    def defer(self, item_id: str, payload: Any) -> None:
        self.deferred[str(item_id)] = payload

    def is_deferred(self, item_id: str) -> bool:
        return str(item_id) in self.deferred

    @property
    def auto_count(self) -> int:
        return len(self.auto_actions)

    @property
    def human_count(self) -> int:
        return len(self.human_actions)

    @property
    def memory_count(self) -> int:
        return len(self.memory_actions)


_CURRENT: ContextVar[RunContext | None] = ContextVar("handoff_run_context", default=None)


def current_run() -> RunContext | None:
    return _CURRENT.get()


def require_run() -> RunContext:
    ctx = _CURRENT.get()
    if ctx is None:
        raise RuntimeError(
            "No active Handoff run context. Wrap execution in `with run_context(...)`."
        )
    return ctx


@contextmanager
def run_context(ctx: RunContext):
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)
