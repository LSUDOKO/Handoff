# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Answering a Strands interrupt through a host runtime's human-input channel.

A host that embeds Handoff usually already knows how to put a question in
front of a person and block a job until they answer — it exposes a tool,
conventionally ``request_human_input``. Strands already knows how to suspend
an agent loop mid-tool-call and resume it with the answer. This module is the
seam between them.

That seam is what makes an embedding real rather than adjacent. Without it
there would be two competing notions of "waiting for a human" — the host's and
the SDK's — and a run that paused in one would be invisible to the other.
Here, ``event.interrupt()`` and the host's prompt are the same event.

    Strands executor agent
        └── submit_action (gated)
              └── HITLGate.gate()
                    └── event.interrupt()          ← suspends the agent loop
                          ↑
    HostGate.ask() ───────┘   answers it inline, by asking the host, which
                              surfaces the question in its own UI and blocks
                              until the person chooses.

When the run is driven by Handoff's own web UI instead, the same gate is used
without a host context and the interrupt propagates normally — the decision
screen answers it out of band. One gate, two front ends.
"""

from __future__ import annotations

import json
from typing import Any

from handoff.graph.hooks.hitl import HITLGate
from handoff.models import InterruptPayload

#: Tool a host conventionally exposes for blocking on a person.
HUMAN_INPUT_TOOL = "request_human_input"

OPTION_LABELS = {
    "file_ticket": "File a ticket",
    "archive": "Archive it",
    "draft_reply": "Draft a reply",
    "reply": "Draft a reply",
    "post_to_slack": "Post to Slack",
    "skip": "Leave it",
    "approve_suggested": "Go with Handoff's call",
}


def mcp_text(result: Any) -> str:
    """Flatten an MCP tool result into its text content."""
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return json.dumps(result)
    return str(result)


def question_for(payload: InterruptPayload) -> str:
    """The one question, phrased so it can be answered without opening the item."""
    lines = [
        payload.item.subject or payload.item.summary,
        f"From {payload.item.sender}." if payload.item.sender else "",
        "",
        payload.agent_analysis.reasoning or payload.reason,
        "",
        f"I'm {payload.agent_analysis.confidence:.0%} sure the right move is "
        f"{payload.agent_analysis.suggested_action.replace('_', ' ')}."
        if payload.agent_analysis.suggested_action
        else "I don't have a confident suggestion.",
    ]
    return "\n".join(line for line in lines if line is not None).strip()


def options_for(payload: InterruptPayload) -> list[dict[str, str]]:
    suggested = payload.agent_analysis.suggested_action
    options = []
    for value in payload.options:
        if value == "approve_suggested" and not suggested:
            continue
        label = OPTION_LABELS.get(value, value.replace("_", " ").capitalize())
        if value == suggested:
            label = f"{label} (suggested)"
        options.append({"label": label, "value": value})
    return options


class HostGate(HITLGate):
    """A :class:`HITLGate` that answers its own interrupts, via the host.

    Every other gate raises and lets the caller deal with it. This one calls
    back into the host runtime from inside the hook, so from Strands' point of
    view the human's answer was simply available the first time it asked.

    Batch deferral is deliberately off here: a host that prompts inline has no
    reason to defer, and answering each question as it arises keeps the run in
    one piece.
    """

    def __init__(self, ctx: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ctx = ctx
        self.asked: list[InterruptPayload] = []

    def gate(self, event: Any) -> None:  # type: ignore[override]
        from handoff.graph.hooks.hitl import (
            apply_learned_rules,
            build_payload,
            evaluate_gate,
            normalise_response,
        )

        tool_name = event.tool_use.get("name", "")
        tool_input = event.tool_use.get("input", {}) or {}

        ruled = apply_learned_rules(tool_name, tool_input)
        if ruled is not tool_input:
            event.tool_use = {**event.tool_use, "input": ruled}
            tool_input = ruled

        verdict = evaluate_gate(tool_name, tool_input, self.threshold)
        if not verdict.gated:
            return

        interrupt_name = f"handoff_decision:{tool_input.get('item_id', tool_name)}"
        payload = self.payloads.get(interrupt_name)
        if payload is None:
            payload = build_payload(
                tool_name,
                tool_input,
                verdict.reason,
                run_id=self.run_id,
                workflow_id=self.workflow_id,
                interrupt_name=interrupt_name,
            )
            self.payloads[interrupt_name] = payload
            self.asked.append(payload)
            if self.on_interrupt is not None:
                self.on_interrupt(payload)

        answer = self.ask(payload)

        # Hand the answer to Strands as a *preemptive* interrupt response. The
        # loop never unwinds — from the agent's side the question was already
        # answered when it asked.
        response = event.interrupt(
            interrupt_name,
            reason=payload.model_dump(mode="json"),
            response=answer,
        )

        decision = normalise_response(response, payload)
        payload.decision = decision
        payload.resolved = True
        self.decisions.append(decision)

        from handoff.graph.hooks.hitl import NO_OP_ACTIONS

        if decision.chosen_action in NO_OP_ACTIONS:
            event.cancel_tool = (
                f"Human chose '{decision.chosen_action}' — no action taken on "
                f"{payload.item.item_id or payload.item.subject}."
            )
        else:
            new_input = dict(tool_input)
            new_input.update(
                {
                    "action": decision.chosen_action,
                    "confidence": 1.0,
                    "force_interrupt": False,
                    "decided_by": "human",
                    "human_note": decision.user_note,
                }
            )
            event.tool_use = {**event.tool_use, "input": new_input}

        if self.on_decision is not None:
            self.on_decision(payload, decision)

    def _progress(self, text: str) -> None:
        """Tell the host what we're waiting on, if it cares to listen."""
        stream = getattr(self.ctx, "stream", None)
        if stream is None:
            return
        try:
            stream.progress(text, tool_name=HUMAN_INPUT_TOOL)
        except TypeError:
            stream.progress(text)
        except Exception:
            pass

    def ask(self, payload: InterruptPayload) -> dict[str, str]:
        """Put the question to the person and block until they answer."""
        self._progress(
            f"Need your call on: {payload.item.subject or payload.item.summary}"
        )

        try:
            raw = self.ctx.tools.call(
                HUMAN_INPUT_TOOL,
                {
                    "question": question_for(payload),
                    "options": options_for(payload),
                },
            )
            parsed = json.loads(mcp_text(raw))
        except Exception as exc:
            # If the human channel is unavailable, do the safe thing: skip. An
            # agent that cannot ask must not decide to act anyway.
            self._progress(f"Could not reach you ({exc}); leaving it alone.")
            return {"action": "skip", "note": f"human input unavailable: {exc}"}

        if parsed.get("status") not in (None, "ok", "completed", "accepted"):
            return {"action": "skip", "note": f"declined: {parsed.get('status')}"}

        answer = parsed.get("answer") or parsed.get("value") or ""
        return {"action": str(answer), "note": str(parsed.get("note", ""))}
