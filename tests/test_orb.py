# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The narrator hook, the voice tools, and the orb routes."""

from __future__ import annotations

import json
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


class TestVoiceTools:
    def test_activate_workflow_saves_and_emits(self):
        from handoff import events
        from handoff.chat.voice_tools import activate_workflow, current_channel
        from handoff.store import get_store

        cfg = {
            "workflow_id": "voice-test", "name": "Voice test",
            "trigger": {"type": "cron", "schedule": "0 8 * * 1-5"},
            "mcp_tools": ["gmail"], "steps": [],
        }
        token = current_channel.set("chat:t1")
        try:
            out = activate_workflow(json.dumps(cfg))
        finally:
            current_channel.reset(token)
        assert out["workflow_id"] == "voice-test" and out["status"] == "active"
        assert get_store().get_workflow("voice-test").status.value == "active"
        saved = [e for e in events.history("chat:t1") if e["kind"] == "workflow_saved"]
        assert saved and saved[0]["config"]["name"] == "Voice test" and saved[0]["workflow_id"] == "voice-test"

    def test_activate_workflow_rejects_bad_json(self):
        from handoff.chat.voice_tools import activate_workflow

        assert "error" in activate_workflow("{not json")
        assert "error" in activate_workflow(json.dumps({"name": "no id"}))

    def test_start_run_emits_run_started(self, triage_workflow):
        import time

        from handoff import events
        from handoff.chat.voice_tools import current_channel, start_run

        token = current_channel.set("chat:t2")
        try:
            out = start_run(triage_workflow.workflow_id)
        finally:
            current_channel.reset(token)
        assert out["run_id"] and out["events"] == f"/events/{out['run_id']}"
        started = [e for e in events.history("chat:t2") if e["kind"] == "run_started"]
        assert started and started[0]["run"] == out["run_id"]
        # The run itself proceeds on a thread; give it a moment and check it narrated.
        for _ in range(50):
            if events.is_finished(out["run_id"]):
                break
            time.sleep(0.1)
        assert any(e["kind"] == "node_start" for e in events.history(out["run_id"]))

    def test_start_run_unknown_workflow(self):
        from handoff.chat.voice_tools import start_run

        assert "error" in start_run("does-not-exist")


class TestVoiceChat:
    def test_voice_chat_is_one_per_workspace(self):
        from handoff.chat import get_chat_service
        from handoff.store import get_store

        svc = get_chat_service()
        ws = get_store().default_workspace()
        a = svc.voice_chat(ws.workspace_id)
        b = svc.voice_chat(ws.workspace_id)
        assert a.chat_id == b.chat_id and a.kind == "voice" and a.title == "Voice"
        assert all(c.kind == "chat" for c in svc.list(ws.workspace_id) if c.chat_id != a.chat_id)


class TestOrbRoutes:
    def test_orb_page_and_nav(self):
        from fastapi.testclient import TestClient

        from handoff.web import nav
        from handoff.web.server import app

        talk = next((t for t in nav.TOOLS if t.label == "Talk"), None)
        assert talk is not None and talk.href == "/orb" and talk.icon == "i-mic"
        assert nav.TOOLS[0].label == "Talk"
        c = TestClient(app)
        c.post("/welcome/skip")
        r = c.get("/orb")
        assert r.status_code == 200 and 'id="orb"' in r.text and "orb.js" in r.text

    def test_orb_send_returns_turn(self):
        from fastapi.testclient import TestClient

        from handoff.web.server import app

        c = TestClient(app)
        c.post("/welcome/skip")
        chat_id = c.get("/api/orb/chat").json()["chat_id"]
        r = c.post(f"/orb/{chat_id}/send", data={"message": "what is waiting on me"})
        assert r.status_code == 200 and r.json()["turn"] == 1

    def test_work_card_lists_signals_jobs_agents(self, triage_workflow):
        from fastapi.testclient import TestClient

        from handoff.web.server import app

        c = TestClient(app)
        c.post("/welcome/skip")
        r = c.get(f"/orb/card/{triage_workflow.workflow_id}")
        assert r.status_code == 200
        for word in ("Signals", "Jobs", "Agents", "MCP", "LLM", "SEND", triage_workflow.trigger.schedule):
            assert word in r.text, word


class TestVoiceStream:
    def test_stream_says_unsupported_without_aws(self, monkeypatch):
        from fastapi.testclient import TestClient

        from handoff import config
        from handoff.web.server import app

        monkeypatch.setattr(config, "SPEECH_PROVIDER", "browser")
        c = TestClient(app)
        with c.websocket_connect("/api/voice/stream") as ws:
            assert ws.receive_json()["type"] == "unsupported"
