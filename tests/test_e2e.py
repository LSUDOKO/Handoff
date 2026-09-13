# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The whole loop: run, pause, decide, resume, learn, run again quieter.

This is the test that would catch a regression in the product's actual promise
rather than in any one component.
"""

from __future__ import annotations

import pytest

from handoff.agents.executor import WorkflowRunner, run_workflow, submit_decision
from handoff.models import DecidedBy, RunStatus
from handoff.store import get_store

DECISIONS = {
    "partnerships@vendor.com": ("archive", "Cold outreach, not a real lead."),
    "hr@company.com": ("skip", "Already read it."),
    "cfo@company.com": ("file_ticket", "Track the freeze."),
}


def _resolve_all(store, model):
    for payload in list(store.pending_interrupts()):
        action, note = DECISIONS[payload.item.sender]
        submit_decision(payload.interrupt_id, action, note, model=model)


class TestFirstRun:
    def test_handles_the_clear_cases_and_stops_on_the_rest(self, fake_model, triage_workflow):
        outcome = WorkflowRunner(triage_workflow, fake_model).start("cron")

        assert outcome["status"] == RunStatus.WAITING_ON_HUMAN.value
        assert outcome["auto_count"] == 5
        assert len(outcome["pending_interrupts"]) == 3

    def test_the_escalated_items_are_the_genuinely_hard_ones(self, fake_model, triage_workflow):
        WorkflowRunner(triage_workflow, fake_model).start("cron")
        senders = {p.item.sender for p in get_store().pending_interrupts()}
        assert senders == set(DECISIONS)

    def test_each_escalation_explains_itself(self, fake_model, triage_workflow):
        WorkflowRunner(triage_workflow, fake_model).start("cron")
        for payload in get_store().pending_interrupts():
            assert payload.agent_analysis.reasoning
            assert payload.agent_analysis.confidence < 0.7
            assert payload.options
            assert payload.reason

    def test_the_run_is_resumable_from_another_process(self, fake_model, triage_workflow):
        """Graph state must be serialised, or a restart loses the pending run."""
        outcome = WorkflowRunner(triage_workflow, fake_model).start("cron")
        run = get_store().get_run(outcome["run_id"])
        assert run.graph_state is not None


class TestDecisionsAndResume:
    def test_answering_every_decision_completes_the_run(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        _resolve_all(store, fake_model)

        run = store.list_runs()[0]
        assert run.status is RunStatus.COMPLETED
        assert run.interrupt_count == 3
        assert run.auto_count == 5
        assert not store.pending_interrupts()

    def test_pending_count_falls_by_one_per_decision(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()

        remaining = [3, 2, 1]
        for expected, payload in zip(
            remaining, list(store.pending_interrupts()), strict=True
        ):
            assert len(store.pending_interrupts()) == expected
            action, note = DECISIONS[payload.item.sender]
            submit_decision(payload.interrupt_id, action, note, model=fake_model)

        assert len(store.pending_interrupts()) == 0

    def test_a_completed_run_has_no_leftover_graph_state(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        _resolve_all(store, fake_model)
        assert store.list_runs()[0].graph_state is None

    def test_unknown_interrupt_id_is_rejected(self, fake_model, triage_workflow):
        with pytest.raises(KeyError):
            submit_decision("int_nope", "archive", model=fake_model)


class TestAuditTrail:
    def test_every_action_is_attributed(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        _resolve_all(store, fake_model)

        entries = store.list_audit(limit=500)
        assert entries
        agent_entries = [
            e
            for e in entries
            if e.decision_by is DecidedBy.AGENT and e.action != "run_completed"
        ]
        human_entries = [e for e in entries if e.decision_by is DecidedBy.HUMAN]
        assert len(agent_entries) == 5
        assert len(human_entries) == 3

    def test_human_entries_record_what_the_agent_had_suggested(
        self, fake_model, triage_workflow
    ):
        """"The agent wanted X, I chose Y" is the interesting row in the log."""
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        _resolve_all(store, fake_model)

        for entry in store.list_audit(limit=500):
            if entry.decision_by is DecidedBy.HUMAN:
                assert "agent_suggested" in entry.details
                assert "reason" in entry.details

    def test_the_run_is_closed_out_with_a_summary(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        _resolve_all(store, fake_model)
        assert any(e.action == "run_completed" for e in store.list_audit(limit=500))
        assert store.list_runs()[0].summary


class TestItGetsQuieter:
    """The payoff: the same inbox, the second time, without the questions."""

    def test_second_run_asks_nothing_and_says_why(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        _resolve_all(store, fake_model)
        assert len(store.list_preferences()) == 3

        second = run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)

        assert second["status"] == RunStatus.COMPLETED.value
        assert second["pending_interrupts"] == []
        assert second["memory_count"] == 3
        assert second["auto_count"] == 5

    def test_memory_driven_actions_match_the_human_choices(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        _resolve_all(store, fake_model)
        second = run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)

        entries = [
            e
            for e in store.list_audit(second["run_id"], limit=500)
            if e.decision_by is DecidedBy.MEMORY
        ]
        assert {e.action for e in entries} == {a for a, _ in DECISIONS.values()}


class TestStats:
    def test_dashboard_rollup_reflects_the_run(self, fake_model, triage_workflow):
        run_workflow(triage_workflow.workflow_id, "cron", model=fake_model)
        store = get_store()
        assert store.stats()["pending"] == 3
        assert store.stats()["waiting_runs"] == 1

        _resolve_all(store, fake_model)
        stats = store.stats()
        assert stats["pending"] == 0
        assert stats["human_decisions"] == 3
        assert stats["learned_rules"] == 3
