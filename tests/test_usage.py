# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Token accounting.

Usage is the one thing in the product that is silently wrong when it breaks:
a miswired extraction reports $0.00 and looks like a quiet month rather than a
bug. These tests pin the shape Strands actually reports and the prefix
normalisation that pricing depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from handoff.platform.usage import PRICES, bare_model_id, estimate_cost


@dataclass
class _StopResponse:
    """The shape Strands 1.55 hands to AfterModelCallEvent."""

    message: dict[str, Any]
    stop_reason: str = "end_turn"


@dataclass
class _Event:
    stop_response: Any


def _stop_response(usage: dict[str, int] | None) -> _StopResponse:
    metadata = {"usage": usage} if usage is not None else {}
    return _StopResponse(
        message={
            "role": "assistant",
            "content": [{"text": "ok"}],
            "metadata": metadata,
        }
    )


def _recorder():
    from handoff.platform.sessions import SessionRecorder

    return SessionRecorder(run_id="run_test", workflow_id="wf_test")


def test_usage_is_read_from_the_message_metadata():
    """Bedrock reports tokens on the message, not on the response object."""
    recorder = _recorder()
    recorder._record_usage(
        _Event(_stop_response({"inputTokens": 120, "outputTokens": 34, "totalTokens": 154}))
    )

    from handoff.store import get_store

    records = get_store().list_usage()
    assert len(records) == 1
    assert records[0].input_tokens == 120
    assert records[0].output_tokens == 34


def test_usage_falls_back_to_openai_field_names():
    recorder = _recorder()
    recorder._record_usage(
        _Event(_stop_response({"prompt_tokens": 10, "completion_tokens": 5}))
    )

    from handoff.store import get_store

    records = get_store().list_usage()
    assert len(records) == 1
    assert (records[0].input_tokens, records[0].output_tokens) == (10, 5)


def test_a_call_with_no_usage_records_nothing_and_does_not_raise():
    recorder = _recorder()
    recorder._record_usage(_Event(_stop_response(None)))
    recorder._record_usage(_Event(None))

    from handoff.store import get_store

    assert get_store().list_usage() == []


def test_inference_profile_prefixes_do_not_hide_the_price():
    """The same model costs the same however you route to it."""
    bare = "amazon.nova-pro-v1:0"
    assert bare in PRICES

    for prefix in ("us.", "apac.", "eu.", "global."):
        assert bare_model_id(f"{prefix}{bare}") == bare
        assert estimate_cost(f"{prefix}{bare}", 1_000_000, 0) == PRICES[bare][0]


def test_an_unknown_model_is_free_rather_than_a_crash():
    assert estimate_cost("some.model-nobody-priced", 1_000_000, 1_000_000) == 0.0
