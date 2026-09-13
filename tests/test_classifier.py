# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Classification recording, and the memory overlay that raises confidence."""

from __future__ import annotations

import pytest

from handoff.graph.nodes.classifier import classify_email
from handoff.memory.store import save_preference
from handoff.models import LearnedPreference
from handoff.tools.mock_data import EXPECTED_CLASSIFICATIONS, MOCK_EMAILS


def _call(**overrides):
    base = {
        "email_id": "msg_x",
        "sender": "someone@example.com",
        "subject": "A subject",
        "category": "teammate_request",
        "confidence": 0.9,
        "suggested_action": "file_ticket",
        "reasoning": "Because.",
        "snippet": "",
    }
    return classify_email(**{**base, **overrides})


class TestClassifyEmail:
    def test_records_what_the_agent_decided(self):
        result = _call(category="newsletter", suggested_action="archive", confidence=0.99)
        assert result["category"] == "newsletter"
        assert result["suggested_action"] == "archive"
        assert result["confidence"] == 0.99

    def test_unknown_category_falls_back_to_ambiguous(self):
        """An invented category must route to a human, not to an action."""
        assert _call(category="probably_fine")["category"] == "ambiguous"

    @pytest.mark.parametrize("value,expected", [(1.7, 1.0), (-0.4, 0.0)])
    def test_confidence_is_clamped(self, value, expected):
        assert _call(confidence=value)["confidence"] == expected

    def test_no_preference_means_no_overlay(self):
        assert _call()["applied_preference"] is None


class TestMemoryOverlay:
    def test_matching_sender_rule_overrides_the_action(self):
        pref = LearnedPreference(
            preference_key="inbox_triage_rules",
            pattern="Always archive mail from partnerships@vendor.com",
            match_sender="partnerships@vendor.com",
            action="archive",
            confidence=0.95,
        )
        save_preference(pref)

        result = _call(
            sender="partnerships@vendor.com",
            suggested_action="file_ticket",
            confidence=0.3,
        )

        assert result["suggested_action"] == "archive"
        assert result["confidence"] == 0.95  # now above threshold: no interrupt
        assert result["applied_preference"] == pref.preference_id
        assert "rule you set earlier" in result["reasoning"]

    def test_rule_never_lowers_confidence(self):
        save_preference(
            LearnedPreference(
                preference_key="k",
                pattern="weak rule",
                match_sender="a@b.com",
                action="skip",
                confidence=0.4,
            )
        )
        assert _call(sender="a@b.com", confidence=0.95)["confidence"] == 0.95


class TestFixtureIntegrity:
    """The demo's whole argument is the 5:3 ratio — guard it."""

    def test_every_mock_email_has_an_expected_classification(self):
        assert {e["email_id"] for e in MOCK_EMAILS} == set(EXPECTED_CLASSIFICATIONS)

    def test_the_ratio_shows_selectivity_not_timidity(self):
        ambiguous = [
            k for k, v in EXPECTED_CLASSIFICATIONS.items() if v["category"] == "ambiguous"
        ]
        assert len(ambiguous) == 3
        assert len(EXPECTED_CLASSIFICATIONS) - len(ambiguous) == 5

    def test_ambiguous_items_sit_below_the_threshold(self):
        for key, value in EXPECTED_CLASSIFICATIONS.items():
            if value["category"] == "ambiguous":
                assert value["confidence"] < 0.7, key
            else:
                assert value["confidence"] >= 0.7, key
