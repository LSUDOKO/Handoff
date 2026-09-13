# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""A Strands ``SessionRepository`` backed by the Handoff store.

Strands persists an agent's conversation through a repository of three record
types — the session, the agent within it, and the messages. Pointing that at
our store means a chat is durable the same way everything else is: a JSON file
on the desktop, DynamoDB when deployed, one code path for both.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType

from handoff.platform.models import ChatAgentState, ChatMessage
from handoff.store import get_store


def _row_id(chat_id: str, agent_id: str, message_id: int | None = None) -> str:
    return f"{chat_id}:{agent_id}" + (f":{message_id:06d}" if message_id is not None else "")


class StoreSessionRepository(SessionRepository):
    """Sessions are our Chat rows; agents and messages get their own rows."""

    # -- session ---------------------------------------------------------------

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        # The Chat row is created by the service before the agent exists, so
        # there is nothing to write here; the session id *is* the chat id.
        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        chat = get_store().get_chat(session_id)
        if chat is None:
            return None
        return Session(session_id=session_id, session_type=SessionType.AGENT)

    # -- agent ---------------------------------------------------------------

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        self.update_agent(session_id, session_agent)

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        row = get_store().chat_agents.get("row_id", _row_id(session_id, agent_id))
        if row is None:
            return None
        return SessionAgent(
            agent_id=row.agent_id,
            state=row.state,
            conversation_manager_state=row.conversation_manager_state,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def update_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        data = asdict(session_agent)
        get_store().chat_agents.put(
            ChatAgentState(
                row_id=_row_id(session_id, session_agent.agent_id),
                chat_id=session_id,
                agent_id=session_agent.agent_id,
                state=data.get("state") or {},
                conversation_manager_state=data.get("conversation_manager_state") or {},
                created_at=str(data.get("created_at") or ""),
                updated_at=str(data.get("updated_at") or ""),
            ),
            "row_id",
        )

    # -- messages ------------------------------------------------------------

    def create_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        self.update_message(session_id, agent_id, session_message)

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        row = get_store().chat_messages.get("row_id", _row_id(session_id, agent_id, message_id))
        return self._to_session_message(row) if row else None

    def update_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        data = asdict(session_message)
        get_store().chat_messages.put(
            ChatMessage(
                row_id=_row_id(session_id, agent_id, session_message.message_id),
                chat_id=session_id,
                agent_id=agent_id,
                message_id=session_message.message_id,
                message=data["message"],
                redact_message=data.get("redact_message"),
                created_at=str(data.get("created_at") or ""),
                updated_at=str(data.get("updated_at") or ""),
            ),
            "row_id",
        )

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        rows = get_store().list_chat_messages(session_id, agent_id)[offset:]
        if limit is not None:
            rows = rows[:limit]
        return [self._to_session_message(r) for r in rows]

    # -- multi-agent (unused; chats are single agents) -----------------------

    def create_multi_agent(self, session_id: str, multi_agent: Any, **kwargs: Any) -> None:
        return None

    def read_multi_agent(self, session_id: str, multi_agent_id: str, **kwargs: Any) -> dict | None:
        return None

    def update_multi_agent(self, session_id: str, multi_agent: Any, **kwargs: Any) -> None:
        return None

    @staticmethod
    def _to_session_message(row: ChatMessage) -> SessionMessage:
        return SessionMessage(
            message=row.message,  # type: ignore[arg-type]
            message_id=row.message_id,
            redact_message=row.redact_message,  # type: ignore[arg-type]
            created_at=row.created_at or SessionMessage.from_message({}, 0).created_at,
            updated_at=row.updated_at or SessionMessage.from_message({}, 0).updated_at,
        )
