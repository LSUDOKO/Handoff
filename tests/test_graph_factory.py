# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The workflow graph: shape, wiring, and the edge condition that saves money."""

from __future__ import annotations

from handoff.graph.factory import (
    _trigger_fired,
    build_executor_agent,
    build_workflow_graph,
)
from handoff.graph.hooks.hitl import HITLGate


class TestGraphShape:
    def test_builds_the_three_node_pipeline(self, fake_model, triage_workflow):
        graph = build_workflow_graph(triage_workflow, fake_model)
        assert set(graph.nodes) == {"trigger", "executor", "completer"}

    def test_entry_point_is_the_trigger(self, fake_model, triage_workflow):
        graph = build_workflow_graph(triage_workflow, fake_model)
        assert {n.node_id for n in graph.entry_points} == {"trigger"}

    def test_edges_run_in_one_direction(self, fake_model, triage_workflow):
        graph = build_workflow_graph(triage_workflow, fake_model)
        edges = {(e.from_node.node_id, e.to_node.node_id) for e in graph.edges}
        assert edges == {("trigger", "executor"), ("executor", "completer")}

    def test_builds_without_a_workflow_config(self, fake_model):
        """A bare graph must still build — used by the AgentCore smoke test."""
        graph = build_workflow_graph(None, fake_model)
        assert len(graph.nodes) == 3


class TestExecutorAgent:
    def test_carries_the_tools_the_loop_needs(self, fake_model, triage_workflow):
        agent = build_executor_agent(triage_workflow, fake_model)
        names = set(agent.tool_names)
        assert {
            "recall_preferences",
            "fetch_unread_emails",
            "classify_email",
            "submit_action",
        } <= names

    def test_browser_tool_only_loads_when_the_workflow_asks_for_it(
        self, fake_model, triage_workflow
    ):
        assert "check_competitor_pricing" not in build_executor_agent(
            triage_workflow, fake_model
        ).tool_names

        triage_workflow.mcp_tools = ["browser"]
        assert "check_competitor_pricing" in build_executor_agent(
            triage_workflow, fake_model
        ).tool_names

    def test_gate_is_attached_to_the_executor(self, fake_model, triage_workflow):
        gate = HITLGate(threshold=0.7)
        agent = build_executor_agent(triage_workflow, fake_model, gate)
        from strands.hooks import BeforeToolCallEvent

        callbacks = agent.hooks.get_callbacks_for(
            BeforeToolCallEvent(agent=agent, selected_tool=None, tool_use={}, invocation_state={})
        )
        assert any(getattr(cb, "__self__", None) is gate for cb in callbacks)


class TestTriggerEdgeCondition:
    """An empty webhook should not cost a model invocation, let alone a ticket."""

    class _State:
        def __init__(self, results):
            self.results = results

    def test_passes_when_the_trigger_fired(self):
        assert _trigger_fired(self._State({"trigger": '{"triggered": true}'}))

    def test_blocks_when_the_trigger_did_not_fire(self):
        assert not _trigger_fired(self._State({"trigger": '{"triggered": false}'}))

    def test_passes_when_there_is_no_trigger_result_yet(self):
        assert _trigger_fired(self._State({}))
