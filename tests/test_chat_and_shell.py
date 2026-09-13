# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Chat persistence, the sidebar model, and the workbench preflight."""

from __future__ import annotations

from strands.session.repository_session_manager import RepositorySessionManager
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType

from handoff.chat.repository import StoreSessionRepository
from handoff.chat.service import ChatService
from handoff.platform.models import CustomAgent, Workspace
from handoff.store import get_store
from handoff.web import nav


def _workspace() -> Workspace:
    store = get_store()
    ws = Workspace(name="Ops", color="green")
    store.workspaces.put(ws, "workspace_id")
    return ws


class TestStoreSessionRepository:
    def test_messages_round_trip_through_the_store(self):
        svc = ChatService()
        chat = svc.create(_workspace().workspace_id, "t")
        repo = StoreSessionRepository()
        repo.create_session(Session(session_id=chat.chat_id, session_type=SessionType.AGENT))
        repo.create_agent(chat.chat_id, SessionAgent(agent_id="handoff", state={}, conversation_manager_state={}))

        for i, text in enumerate(["hello", "hi there"]):
            role = "user" if i % 2 == 0 else "assistant"
            repo.create_message(
                chat.chat_id, "handoff",
                SessionMessage.from_message({"role": role, "content": [{"text": text}]}, i),
            )

        listed = repo.list_messages(chat.chat_id, "handoff")
        assert [m.message["content"][0]["text"] for m in listed] == ["hello", "hi there"]
        assert repo.read_message(chat.chat_id, "handoff", 1).message["role"] == "assistant"
        assert repo.read_agent(chat.chat_id, "handoff").agent_id == "handoff"

    def test_strands_session_manager_restores_history(self):
        """The real thing: a second RepositorySessionManager sees the first's messages."""
        svc = ChatService()
        chat = svc.create(_workspace().workspace_id, "t")
        repo = StoreSessionRepository()

        first = RepositorySessionManager(session_id=chat.chat_id, session_repository=repo)
        assert first.session.session_id == chat.chat_id

        # Write a message the way the manager would for an agent.
        repo.create_agent(chat.chat_id, SessionAgent(agent_id="handoff", state={}, conversation_manager_state={}))
        repo.create_message(
            chat.chat_id, "handoff",
            SessionMessage.from_message({"role": "user", "content": [{"text": "remember me"}]}, 0),
        )
        second = RepositorySessionManager(session_id=chat.chat_id, session_repository=repo)
        assert second.session_repository.list_messages(chat.chat_id, "handoff")[0].message["content"][0]["text"] == "remember me"

    def test_history_renders_tool_calls_as_cards_with_results(self):
        svc = ChatService()
        chat = svc.create(_workspace().workspace_id, "t")
        repo = StoreSessionRepository()
        msgs = [
            {"role": "user", "content": [{"text": "run it"}]},
            {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "recent_runs", "input": {"limit": 2}}}]},
            {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "status": "success", "content": [{"text": "[]"}]}}]},
            {"role": "assistant", "content": [{"text": "Nothing has run yet.\n\n```json\n{\"workflow_id\": \"x\", \"name\": \"X\"}\n```"}]},
        ]
        for i, m in enumerate(msgs):
            repo.create_message(chat.chat_id, "handoff", SessionMessage.from_message(m, i))

        blocks = svc.history(chat.chat_id)
        kinds = [b["kind"] for b in blocks]
        assert kinds == ["user", "tool", "assistant"]
        assert blocks[1]["output"] == "[]" and blocks[1]["status"] == "ok"
        assert blocks[2]["config"] and "```" not in blocks[2]["text"]

    def test_deleting_a_chat_removes_its_rows(self):
        svc = ChatService()
        chat = svc.create(_workspace().workspace_id, "t")
        repo = StoreSessionRepository()
        repo.create_message(chat.chat_id, "handoff", SessionMessage.from_message({"role": "user", "content": [{"text": "x"}]}, 0))
        svc.delete(chat.chat_id)
        assert svc.get(chat.chat_id) is None
        assert repo.list_messages(chat.chat_id, "handoff") == []


class TestSidebar:
    def test_active_workspace_unfolds_its_subnav(self):
        store = get_store()
        a = Workspace(name="A")
        b = Workspace(name="B")
        store.workspaces.put(a, "workspace_id")
        store.workspaces.put(b, "workspace_id")

        built = nav.build(f"/platform/{b.workspace_id}/runs", [a, b], b.workspace_id)
        rows = {r.id: r for r in built["workspaces"]}
        assert rows[b.id if hasattr(b, "id") else b.workspace_id].active
        assert not rows[a.workspace_id].active
        assert rows[a.workspace_id].sub == []
        labels = [i.label for i in rows[b.workspace_id].sub]
        assert labels[:3] == ["Overview", "Activity", "Chat"]
        runs = next(i for i in rows[b.workspace_id].sub if i.label == "Runs")
        assert runs.is_active(f"/platform/{b.workspace_id}/runs")

    def test_global_tool_activation_is_by_prefix(self):
        built = nav.build("/inspector/run_1", [], None)
        active = [t["item"].label for t in built["tools"] if t["active"]]
        assert active == ["Inspector"]


class TestWorkbenchPreflight:
    def test_lists_the_credentials_the_tools_need(self):
        from handoff.platform import workbench

        agent = CustomAgent(name="t", tools=["fetch_unread_emails", "notify_user", "read_audit_log"])
        needed = {row["provider"] for row in workbench.preflight(agent)}
        assert needed == {"gmail", "slack"}
