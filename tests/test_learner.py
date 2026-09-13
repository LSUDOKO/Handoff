# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The learning loop, and — more importantly — its restraint.

A preference that fires too eagerly takes actions the human never sanctioned.
Most of these tests are about the rule *not* matching.
"""

from __future__ import annotations

from handoff.agents.learner import create_learner_agent, learn_from_decision
from handoff.memory.store import (
    find_matching_preference,
    list_preferences,
    memory_summary,
    recall_preferences,
    store_user_preference,
)
from handoff.models import InterruptPayload, LearnedPreference, UserDecision


def _payload(sender="partnerships@vendor.com", subject="Strategic partnership"):
    payload = InterruptPayload(run_id="r1", workflow_id="w1", tool="submit_action")
    payload.item.sender = sender
    payload.item.subject = subject
    payload.item.item_id = "msg_004"
    payload.item.snippet = "We'd love to explore a strategic integration."
    payload.agent_analysis.suggested_action = "file_ticket"
    payload.agent_analysis.confidence = 0.3
    payload.agent_analysis.reasoning = "Unknown sender using urgency language."
    payload.reason = "Confidence (30%) is below the 70% threshold"
    return payload


class TestLearningFromDecisions:
    def test_a_decision_becomes_a_stored_rule(self, fake_model):
        result = learn_from_decision(
            _payload(),
            UserDecision(interrupt_id="i1", chosen_action="archive", user_note="cold outreach"),
            model=fake_model,
        )
        assert result["stored"]
        assert result["total_rules"] == 1

    def test_the_rule_records_the_action_the_human_chose(self, fake_model):
        learn_from_decision(
            _payload(),
            UserDecision(interrupt_id="i1", chosen_action="file_ticket"),
            model=fake_model,
        )
        assert list_preferences()[0].action == "file_ticket"

    def test_learner_has_memory_tools(self, fake_model):
        assert "store_user_preference" in create_learner_agent(fake_model).tool_names


class TestPreferenceMatching:
    def test_exact_sender_matches(self):
        store_user_preference(
            pattern="Archive vendor pitches",
            action="archive",
            match_sender="partnerships@vendor.com",
        )
        found = find_matching_preference(sender="partnerships@vendor.com")
        assert found is not None and found.action == "archive"

    def test_a_different_sender_does_not_match(self):
        store_user_preference(
            pattern="Archive vendor pitches",
            action="archive",
            match_sender="partnerships@vendor.com",
        )
        assert find_matching_preference(sender="alice@team.com") is None

    def test_domain_rules_match_the_whole_domain(self):
        store_user_preference(
            pattern="Archive anything from vendor.com",
            action="archive",
            match_sender="@vendor.com",
        )
        assert find_matching_preference(sender="anyone@vendor.com") is not None
        assert find_matching_preference(sender="anyone@team.com") is None

    def test_one_shared_keyword_is_not_enough(self):
        """One word in common is a coincidence. Requiring two is the guardrail."""
        store_user_preference(
            pattern="Archive dependabot noise",
            action="archive",
            match_keywords=["dependabot", "lodash"],
        )
        assert find_matching_preference(subject="Dependabot alert") is None

    def test_two_shared_keywords_match(self):
        store_user_preference(
            pattern="Archive dependabot noise",
            action="archive",
            match_keywords=["dependabot", "lodash"],
        )
        assert (
            find_matching_preference(subject="Dependabot alert: lodash issue") is not None
        )

    def test_no_rules_means_no_match(self):
        assert find_matching_preference(sender="anyone@anywhere.com") is None

    def test_the_most_confident_rule_wins(self):
        store_user_preference(
            pattern="weak", action="skip", match_sender="a@b.com", confidence=0.5
        )
        store_user_preference(
            pattern="strong", action="archive", match_sender="a@b.com", confidence=0.95
        )
        assert find_matching_preference(sender="a@b.com").action == "archive"


class TestPreferenceStorage:
    def test_derives_keywords_when_given_neither_sender_nor_keywords(self):
        result = store_user_preference(
            pattern="Archive quarterly compliance digest emails", action="archive"
        )
        assert result["match_keywords"]
        assert "the" not in result["match_keywords"]  # stopwords stripped

    def test_recall_returns_stored_rules(self):
        store_user_preference(
            pattern="Archive vendor pitches",
            action="archive",
            match_sender="x@y.com",
            preference_key="inbox_triage_rules",
        )
        rules = recall_preferences("inbox", preference_key="inbox_triage_rules")
        assert len(rules) == 1 and rules[0]["action"] == "archive"

    def test_recall_is_scoped_by_preference_key(self):
        store_user_preference(
            pattern="a", action="archive", match_sender="x@y.com", preference_key="inbox"
        )
        assert recall_preferences("anything", preference_key="competitor") == []

    def test_confidence_is_clamped(self):
        pref = LearnedPreference(
            preference_key="k", pattern="p", action="archive", confidence=0.5
        )
        assert 0.0 <= pref.confidence <= 1.0
        assert store_user_preference(pattern="p", action="archive", confidence=5.0)
        assert all(0.0 <= p.confidence <= 1.0 for p in list_preferences())

    def test_summary_reports_the_local_backend(self):
        store_user_preference(pattern="p", action="archive", match_sender="a@b.com")
        summary = memory_summary()
        assert summary["count"] == 1 and summary["backend"] == "local"


class TestARuleMustFireOnItsOwnItem:
    """The invariant that makes learning actually reduce questions.

    A rule written from an item but unable to match that item is worse than no
    rule: it fails silently, the next run asks the same question, and nothing
    in the output says why. This came from a real Nova Lite run, which wrote
    "Archive cold outreach emails from partnerships@vendor.com" with
    ``match_sender`` empty and keywords lifted from its own sentence —
    "archive", "outreach", "emails" — none of which appear in a subject line.
    """

    def _unmatchable_rule(self, monkeypatch, preference_key="inbox_triage_rules"):
        """Stand in for a model that writes the sender in prose only."""
        from handoff.agents import learner
        from handoff.memory.store import save_preference

        def fake_agent(_model=None):
            def run(_briefing):
                save_preference(
                    LearnedPreference(
                        preference_key=preference_key,
                        pattern="Archive cold outreach emails from partnerships@vendor.com",
                        match_sender="",
                        match_keywords=["archive", "cold", "outreach", "emails"],
                        action="archive",
                        confidence=0.5,
                    )
                )
                return "stored"

            return run

        monkeypatch.setattr(learner, "create_learner_agent", fake_agent)

    def test_an_unmatchable_rule_is_repaired_with_the_exact_sender(self, monkeypatch):
        self._unmatchable_rule(monkeypatch)
        payload = _payload()

        result = learn_from_decision(
            payload,
            UserDecision(interrupt_id="i1", chosen_action="archive"),
            preference_key="inbox_triage_rules",
        )

        assert result["repaired"], "the dead rule should have been repaired"
        rules = list_preferences("inbox_triage_rules")
        assert rules[0].match_sender == "partnerships@vendor.com"

    def test_after_repair_the_same_item_matches(self, monkeypatch):
        """The point of the repair: the next run does not ask again."""
        self._unmatchable_rule(monkeypatch)
        payload = _payload()

        learn_from_decision(
            payload,
            UserDecision(interrupt_id="i1", chosen_action="archive"),
            preference_key="inbox_triage_rules",
        )

        match = find_matching_preference(
            sender=payload.item.sender,
            subject=payload.item.subject,
            snippet=payload.item.snippet,
            preference_key="inbox_triage_rules",
        )
        assert match is not None
        assert match.action == "archive"

    def test_a_rule_that_already_matches_is_left_alone(self, monkeypatch):
        """Don't narrow a good broad rule down to one sender."""
        from handoff.agents import learner
        from handoff.memory.store import save_preference

        def fake_agent(_model=None):
            def run(_briefing):
                save_preference(
                    LearnedPreference(
                        preference_key="inbox_triage_rules",
                        pattern="Archive strategic partnership pitches",
                        match_sender="",
                        match_keywords=["strategic", "partnership"],
                        action="archive",
                        confidence=0.8,
                    )
                )
                return "stored"

            return run

        monkeypatch.setattr(learner, "create_learner_agent", fake_agent)

        result = learn_from_decision(
            _payload(),
            UserDecision(interrupt_id="i1", chosen_action="archive"),
            preference_key="inbox_triage_rules",
        )

        assert result["repaired"] == []
        assert list_preferences("inbox_triage_rules")[0].match_sender == ""


class TestPreferenceStrength:
    def test_tiers_are_ordered_sender_then_domain_then_keywords(self):
        from handoff.memory.store import (
            MATCH_DOMAIN,
            MATCH_KEYWORDS,
            MATCH_NONE,
            MATCH_SENDER,
            preference_strength,
        )

        item = dict(
            sender="partnerships@vendor.com",
            subject="Strategic partnership",
            snippet="a strategic integration",
        )

        def rule(**kw):
            return LearnedPreference(
                preference_key="k", pattern="p", action="archive", **kw
            )

        assert (
            preference_strength(rule(match_sender="partnerships@vendor.com"), **item)
            == MATCH_SENDER
        )
        assert preference_strength(rule(match_sender="@vendor.com"), **item) == MATCH_DOMAIN
        assert (
            preference_strength(
                rule(match_keywords=["strategic", "partnership"]), **item
            )
            == MATCH_KEYWORDS
        )
        assert preference_strength(rule(match_keywords=["strategic"]), **item) == MATCH_NONE
        assert preference_strength(rule(match_sender="someone@else.com"), **item) == MATCH_NONE

    def test_a_subdomain_is_not_the_domain(self):
        from handoff.memory.store import MATCH_NONE, preference_strength

        rule = LearnedPreference(
            preference_key="k", pattern="p", action="archive", match_sender="@vendor.com"
        )
        assert (
            preference_strength(rule, sender="a@evil-vendor.com", subject="", snippet="")
            == MATCH_NONE
        )
