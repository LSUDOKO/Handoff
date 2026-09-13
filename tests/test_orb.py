# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The narrator hook, the voice tools, and the orb routes."""

from __future__ import annotations

from typing import Any

from handoff.testing.fake_model import FakeModel


class OneToolModel(FakeModel):
    """Calls the first tool it is offered once, then says done."""

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        names = [s.get("name") for s in (tool_specs or [])]
        called = any(
            "toolUse" in b for m in messages if m.get("role") == "assistant"
            for b in m.get("content", []) if isinstance(b, dict)
        )
        if names and not called:
            blocks: list[dict[str, Any]] = [{"toolUse": {"toolUseId": "t1", "name": names[0], "input": {}}}]
        else:
            blocks = [{"text": "Done."}]
        async for event in self._emit(blocks):
            yield event


class TestRunNarrator:
    def test_tool_events_carry_node_and_timing(self):
        from strands import Agent, tool

        from handoff import events
        from handoff.graph.hooks.narrator import Narrator

        @tool
        def ping() -> str:
            """Reply pong."""
            return "pong"

        narrator = Narrator("run:test", node="executor")
        agent = Agent(model=OneToolModel(), tools=[ping], hooks=[narrator], callback_handler=None)
        agent("call ping")

        kinds = [e["kind"] for e in events.history("run:test")]
        assert kinds[0] == "node_start" and kinds[-1] == "node_end"
        assert "tool_start" in kinds and "tool_end" in kinds
        end = next(e for e in events.history("run:test") if e["kind"] == "tool_end")
        assert end["node"] == "executor" and end["name"] == "ping" and end["status"] == "ok"
        assert end["ms"] >= 0 and "pong" in end["output"]
        assert narrator.steps and narrator.steps[0]["name"] == "ping"

    def test_workflow_graph_narrates_every_node(self, triage_workflow):
        """The real graph, offline: trigger, executor and completer all report."""
        from handoff import events
        from handoff.agents.executor import WorkflowRunner

        outcome = WorkflowRunner(triage_workflow, model=FakeModel()).start("manual")
        run_id = outcome["run_id"]
        nodes = {e["node"] for e in events.history(run_id) if e["kind"] == "node_start"}
        assert {"trigger", "executor"} <= nodes
        tools = [e["name"] for e in events.history(run_id) if e["kind"] == "tool_end"]
        assert "fetch_unread_emails" in tools
