# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The gate is the product. These are the tests that must never go red.

Two layers are covered here: the pure decision function (does this call need a
human?) and the live hook running inside a real Strands agent (does the loop
actually stop, and does the human's answer actually take effect?).
"""

from __future__ import annotations

import pytest
from strands import Agent, tool
from strands.models.model import Model

from handoff.graph.hooks.hitl import (
    ALWAYS_GATED,
    HITLGate,
    evaluate_gate,
    normalise_response,
)
from handoff.models import InterruptPayload, UserDecision

# --- the decision function -------------------------------------------------


class TestEvaluateGate:
    def test_high_confidence_passes_through(self):
        assert not evaluate_gate("submit_action", {"confidence": 0.95}).gated

    def test_confidence_at_threshold_passes(self):
        """0.7 is "confident enough", not "borderline"—the boundary is inclusive."""
        assert not evaluate_gate("submit_action", {"confidence": 0.7}, threshold=0.7).gated

    def test_low_confidence_is_gated(self):
        verdict = evaluate_gate("submit_action", {"confidence": 0.3}, threshold=0.7)
        assert verdict.gated
        assert "30%" in verdict.reason and "70%" in verdict.reason

    def test_force_interrupt_beats_high_confidence(self):
        verdict = evaluate_gate(
            "submit_action", {"confidence": 0.99, "force_interrupt": True}
        )
        assert verdict.gated
        assert "human judgement" in verdict.reason

    @pytest.mark.parametrize("tool_name", sorted(ALWAYS_GATED))
    def test_irreversible_tools_always_gate(self, tool_name):
        verdict = evaluate_gate(tool_name, {"confidence": 1.0})
        assert verdict.gated
        assert "irreversible" in verdict.reason

    def test_ungated_tools_are_never_gated(self):
        assert not evaluate_gate("fetch_unread_emails", {"confidence": 0.0}).gated

    def test_missing_confidence_is_treated_as_certain(self):
        """A tool that doesn't report confidence isn't asking to be gated."""
        assert not evaluate_gate("submit_action", {}).gated

    def test_garbage_confidence_is_treated_as_zero(self):
        """A malformed score must fail safe — toward asking, not toward acting."""
        assert evaluate_gate("submit_action", {"confidence": "nonsense"}).gated

    def test_threshold_is_configurable_per_workflow(self):
        assert not evaluate_gate("submit_action", {"confidence": 0.5}, threshold=0.4).gated
        assert evaluate_gate("submit_action", {"confidence": 0.5}, threshold=0.9).gated


# --- response normalisation ------------------------------------------------


class TestNormaliseResponse:
    @staticmethod
    def _payload(suggested="archive"):
        p = InterruptPayload()
        p.agent_analysis.suggested_action = suggested
        return p

    def test_plain_string_becomes_the_action(self):
        assert normalise_response("file_ticket", self._payload()).chosen_action == "file_ticket"

    def test_dict_with_note_is_preserved(self):
        decision = normalise_response(
            {"action": "skip", "note": "handled it myself"}, self._payload()
        )
        assert decision.chosen_action == "skip"
        assert decision.user_note == "handled it myself"

    def test_approve_suggested_resolves_to_the_suggestion(self):
        decision = normalise_response("approve_suggested", self._payload("draft_reply"))
        assert decision.chosen_action == "draft_reply"

    def test_empty_response_falls_back_to_the_suggestion(self):
        assert normalise_response("", self._payload("archive")).chosen_action == "archive"

    def test_empty_response_with_no_suggestion_skips(self):
        """When nobody has an opinion, do nothing — never invent an action."""
        assert normalise_response("", self._payload("")).chosen_action == "skip"

    def test_existing_decision_passes_through(self):
        original = UserDecision(interrupt_id="x", chosen_action="archive")
        assert normalise_response(original, self._payload()) is original


# --- the hook inside a real agent -----------------------------------------


@tool
def submit_action(action: str, item_id: str, confidence: float, summary: str = "") -> dict:
    """Stand-in for the real gated tool, so the test owns its side effects."""
    EXECUTED.append({"action": action, "item_id": item_id, "confidence": confidence})
    return {"status": "executed", "action": action, "item_id": item_id}


EXECUTED: list[dict] = []


class ScriptedModel(Model):
    """Emits one submit_action call with whatever input the test supplies."""

    def __init__(self, tool_input: dict) -> None:
        self.tool_input = tool_input
        self._config: dict = {}

    def update_config(self, **kwargs):
        self._config.update(kwargs)

    def get_config(self):
        return self._config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        yield {"output": output_model()}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        import json

        already = any(
            isinstance(b, dict) and "toolUse" in b
            for m in messages
            if m.get("role") == "assistant"
            for b in m.get("content", []) or []
        )
        yield {"messageStart": {"role": "assistant"}}
        if already:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "Done."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        else:
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": "t1", "name": "submit_action"}}
                }
            }
            yield {
                "contentBlockDelta": {
                    "delta": {"toolUse": {"input": json.dumps(self.tool_input)}}
                }
            }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }


def _agent(tool_input: dict, gate: HITLGate) -> Agent:
    return Agent(
        model=ScriptedModel(tool_input),
        tools=[submit_action],
        hooks=[gate],
        system_prompt="test",
        callback_handler=None,
    )


class TestGateInsideAgent:
    def setup_method(self):
        EXECUTED.clear()

    def test_confident_action_runs_without_interrupting(self):
        gate = HITLGate(threshold=0.7)
        result = _agent(
            {"action": "archive", "item_id": "m1", "confidence": 0.95}, gate
        )("go")

        assert result.stop_reason != "interrupt"
        assert not result.interrupts
        assert EXECUTED == [{"action": "archive", "item_id": "m1", "confidence": 0.95}]

    def test_unsure_action_stops_the_loop_before_the_tool_runs(self):
        gate = HITLGate(threshold=0.7)
        result = _agent(
            {"action": "archive", "item_id": "m2", "confidence": 0.3}, gate
        )("go")

        assert result.stop_reason == "interrupt"
        assert len(result.interrupts) == 1
        # The critical assertion: nothing happened to the user's mail.
        assert EXECUTED == []

    def test_interrupt_payload_has_what_the_decision_screen_needs(self):
        captured: list = []
        gate = HITLGate(threshold=0.7, on_interrupt=captured.append)
        _agent(
            {
                "action": "archive",
                "item_id": "m3",
                "confidence": 0.25,
                "summary": "Partnership pitch from an unknown vendor",
                "sender": "partnerships@vendor.com",
                "subject": "Strategic partnership",
                "reasoning": "Unknown sender using urgency language.",
                "options": ["file_ticket", "archive", "skip"],
            },
            gate,
        )("go")

        assert len(captured) == 1
        payload = captured[0]
        assert payload.item.sender == "partnerships@vendor.com"
        assert payload.item.summary == "Partnership pitch from an unknown vendor"
        assert payload.agent_analysis.confidence == 0.25
        assert payload.agent_analysis.reasoning
        assert payload.options == ["file_ticket", "archive", "skip"]
        assert "25%" in payload.reason

    def test_resume_executes_what_the_human_chose_not_what_was_suggested(self):
        gate = HITLGate(threshold=0.7)
        agent = _agent({"action": "archive", "item_id": "m4", "confidence": 0.3}, gate)

        result = agent("go")
        assert result.stop_reason == "interrupt"

        interrupt = result.interrupts[0]
        agent(
            [
                {
                    "interruptResponse": {
                        "interruptId": interrupt.id,
                        "response": {"action": "file_ticket", "note": "real lead"},
                    }
                }
            ]
        )

        assert len(EXECUTED) == 1
        assert EXECUTED[0]["action"] == "file_ticket"  # not "archive"
        assert gate.decisions[0].user_note == "real lead"

    def test_choosing_skip_cancels_the_tool_entirely(self):
        gate = HITLGate(threshold=0.7)
        agent = _agent({"action": "archive", "item_id": "m5", "confidence": 0.2}, gate)

        result = agent("go")
        agent(
            [
                {
                    "interruptResponse": {
                        "interruptId": result.interrupts[0].id,
                        "response": {"action": "skip"},
                    }
                }
            ]
        )

        # "Leave it alone" must mean the tool never ran, not that it ran with
        # action="skip" — the audit trail has to be able to tell those apart.
        assert EXECUTED == []
        assert gate.decisions[0].chosen_action == "skip"

    def test_on_decision_callback_receives_payload_and_decision(self):
        seen: list = []
        gate = HITLGate(
            threshold=0.7, on_decision=lambda p, d: seen.append((p, d))
        )
        agent = _agent({"action": "archive", "item_id": "m6", "confidence": 0.1}, gate)
        result = agent("go")
        agent(
            [
                {
                    "interruptResponse": {
                        "interruptId": result.interrupts[0].id,
                        "response": {"action": "archive", "note": "junk"},
                    }
                }
            ]
        )

        assert len(seen) == 1
        payload, decision = seen[0]
        assert payload.resolved is True
        assert decision.chosen_action == "archive"
        assert decision.user_note == "junk"
