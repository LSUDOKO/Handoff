# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The seam between a Strands interrupt and a host runtime's human-input channel.

If this breaks, a run pauses somewhere nobody is looking.
"""

from __future__ import annotations

import json

import pytest
from strands import Agent, tool

from handoff.host.gate import (
    HostGate,
    mcp_text,
    options_for,
    question_for,
)
from handoff.models import InterruptPayload

from .test_hitl_gate import ScriptedModel

EXECUTED: list[dict] = []


@tool
def submit_action(action: str, item_id: str, confidence: float, summary: str = "") -> dict:
    """Stand-in for the gated tool."""
    EXECUTED.append({"action": action, "item_id": item_id})
    return {"status": "executed"}


class FakeStream:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def intent(self, text, **kwargs):
        self.messages.append(text)

    def progress(self, text, **kwargs):
        self.messages.append(text)


class FakeTools:
    """Stands in for a host runtime's MCP tool channel."""

    def __init__(self, answer: str = "archive", note: str = "", raises: bool = False) -> None:
        self.answer = answer
        self.note = note
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, args: dict):
        self.calls.append((name, args))
        if self.raises:
            raise RuntimeError("nats disconnected")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"status": "ok", "answer": self.answer, "note": self.note}
                    ),
                }
            ]
        }


class FakeCtx:
    def __init__(self, **kwargs) -> None:
        self.stream = FakeStream()
        self.tools = FakeTools(**kwargs)


def _run(ctx, tool_input: dict) -> HostGate:
    gate = HostGate(ctx, threshold=0.7)
    agent = Agent(
        model=ScriptedModel(tool_input),
        tools=[submit_action],
        hooks=[gate],
        system_prompt="test",
        callback_handler=None,
    )
    agent("go")
    return gate


@pytest.fixture(autouse=True)
def _clear():
    EXECUTED.clear()
    yield
    EXECUTED.clear()


class TestHostGate:
    def test_confident_calls_never_reach_the_human_channel(self):
        ctx = FakeCtx()
        _run(ctx, {"action": "archive", "item_id": "m1", "confidence": 0.95})

        assert ctx.tools.calls == []
        assert EXECUTED == [{"action": "archive", "item_id": "m1"}]

    def test_an_unsure_call_asks_the_person(self):
        ctx = FakeCtx(answer="file_ticket")
        _run(ctx, {"action": "archive", "item_id": "m2", "confidence": 0.3})

        assert len(ctx.tools.calls) == 1
        name, args = ctx.tools.calls[0]
        assert name == "request_human_input"
        assert args["question"]
        assert args["options"]

    def test_the_run_continues_inline_with_their_answer(self):
        """No interrupt escapes: the loop resolves it on the spot."""
        ctx = FakeCtx(answer="file_ticket", note="real lead")
        gate = _run(ctx, {"action": "archive", "item_id": "m3", "confidence": 0.3})

        assert EXECUTED == [{"action": "file_ticket", "item_id": "m3"}]
        assert gate.decisions[0].chosen_action == "file_ticket"
        assert gate.decisions[0].user_note == "real lead"

    def test_choosing_to_leave_it_cancels_the_tool(self):
        ctx = FakeCtx(answer="skip")
        _run(ctx, {"action": "archive", "item_id": "m4", "confidence": 0.2})
        assert EXECUTED == []

    def test_an_unreachable_human_never_becomes_an_action(self):
        """If we cannot ask, we must not decide to act anyway."""
        ctx = FakeCtx(raises=True)
        gate = _run(ctx, {"action": "archive", "item_id": "m5", "confidence": 0.2})

        assert EXECUTED == []
        assert gate.decisions[0].chosen_action == "skip"

    def test_progress_is_streamed_so_the_host_shows_the_wait(self):
        ctx = FakeCtx()
        _run(ctx, {"action": "archive", "item_id": "m6", "confidence": 0.3})
        assert any("Need your call" in m for m in ctx.stream.messages)

    def test_payloads_are_recorded_for_the_learner(self):
        ctx = FakeCtx(answer="archive")
        gate = _run(ctx, {"action": "archive", "item_id": "m7", "confidence": 0.3})
        assert len(gate.asked) == 1
        assert gate.asked[0].decision is not None


class TestPrompting:
    @staticmethod
    def _payload():
        payload = InterruptPayload(options=["approve_suggested", "archive", "skip"])
        payload.item.subject = "Strategic partnership opportunity"
        payload.item.sender = "partnerships@vendor.com"
        payload.agent_analysis.suggested_action = "archive"
        payload.agent_analysis.confidence = 0.3
        payload.agent_analysis.reasoning = "Unknown sender using urgency language."
        return payload

    def test_the_question_is_answerable_without_opening_the_item(self):
        text = question_for(self._payload())
        assert "Strategic partnership opportunity" in text
        assert "partnerships@vendor.com" in text
        assert "Unknown sender" in text
        assert "30%" in text

    def test_the_suggestion_is_marked(self):
        options = options_for(self._payload())
        suggested = [o for o in options if "(suggested)" in o["label"]]
        assert len(suggested) == 1
        assert suggested[0]["value"] == "archive"

    def test_approve_suggested_is_dropped_when_there_is_no_suggestion(self):
        payload = self._payload()
        payload.agent_analysis.suggested_action = ""
        assert "approve_suggested" not in {o["value"] for o in options_for(payload)}


class TestMcpText:
    def test_unwraps_text_content(self):
        assert mcp_text({"content": [{"type": "text", "text": "hi"}]}) == "hi"

    def test_falls_back_to_json(self):
        assert json.loads(mcp_text({"answer": "archive"}))["answer"] == "archive"

    def test_handles_a_plain_string(self):
        assert mcp_text("archive") == "archive"
