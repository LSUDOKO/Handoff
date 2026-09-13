# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Surviving an endpoint that rejects a tool call's JSON."""

from __future__ import annotations

import json

import pytest

from handoff.providers import (
    extract_failed_generation,
    repair_tool_call,
    synthesize_tool_use_events,
)

# Verbatim from a Groq 400 during a real run: a stray quote after the number.
GROQ_BROKEN = (
    '{"name": "classify_email", "arguments": {"category": "newsletter", '
    '"confidence": 0.95", "email_id": "msg_002", "reasoning": "TechCrunch daily '
    'is a newsletter", "suggested_action": "archive"}"}'
)


class FakeAPIError(Exception):
    def __init__(self, body):
        super().__init__(f"Error code: 400 - {body}")
        self.body = body


class TestExtract:
    def test_reads_failed_generation_from_the_error_body(self):
        exc = FakeAPIError({"error": {"code": "tool_use_failed", "failed_generation": GROQ_BROKEN}})
        assert extract_failed_generation(exc) == GROQ_BROKEN

    def test_falls_back_to_parsing_the_message(self):
        class Plain(Exception):
            pass

        exc = Plain(
            "Error code: 400 - {'error': {'message': 'x', 'code': 'tool_use_failed', "
            f"'failed_generation': '{GROQ_BROKEN}'}}}}"
        )
        assert extract_failed_generation(exc) == GROQ_BROKEN

    def test_returns_none_when_absent(self):
        assert extract_failed_generation(Exception("something else")) is None


class TestRepair:
    def test_repairs_the_real_groq_slip(self):
        name, args = repair_tool_call(GROQ_BROKEN)
        assert name == "classify_email"
        assert args["email_id"] == "msg_002"
        assert args["category"] == "newsletter"
        assert args["confidence"] == pytest.approx(0.95)
        assert args["suggested_action"] == "archive"

    def test_passes_clean_json_through(self):
        clean = json.dumps({"name": "submit_action", "arguments": {"action": "archive", "item_id": "m1", "confidence": 0.9}})
        name, args = repair_tool_call(clean)
        assert name == "submit_action" and args["action"] == "archive"

    def test_accepts_string_encoded_arguments(self):
        text = json.dumps({"name": "submit_action", "arguments": json.dumps({"action": "skip", "item_id": "m1"})})
        name, args = repair_tool_call(text)
        assert args["action"] == "skip"

    def test_refuses_to_invent_a_call_from_garbage(self):
        """A repair that isn't clearly a tool call must not become one."""
        assert repair_tool_call("I think we should archive this one.") is None
        assert repair_tool_call('{"reasoning": "no name here"}') is None


class TestSynthesize:
    def test_emits_the_sequence_strands_expects(self):
        events = list(synthesize_tool_use_events("classify_email", {"email_id": "m1"}))
        kinds = [next(iter(e)) for e in events]
        assert kinds == [
            "messageStart",
            "contentBlockStart",
            "contentBlockDelta",
            "contentBlockStop",
            "messageStop",
            "metadata",
        ]
        assert events[1]["contentBlockStart"]["start"]["toolUse"]["name"] == "classify_email"
        assert json.loads(events[2]["contentBlockDelta"]["delta"]["toolUse"]["input"]) == {"email_id": "m1"}
        assert events[4]["messageStop"]["stopReason"] == "tool_use"
