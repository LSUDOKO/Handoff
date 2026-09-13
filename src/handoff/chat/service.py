# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The chat service: one Strands agent per chat, streamed to the browser.

A turn runs on a worker thread and narrates itself over the events bus —
text as it streams, each tool call as it starts and finishes, the final
text with any workflow config it produced, and any decisions the turn left
waiting. The page subscribes over SSE and paints as events arrive.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

from strands import Agent
from strands.session.repository_session_manager import RepositorySessionManager

from handoff import config, events
from handoff.agents.builder import BUILDER_PROMPT, extract_config
from handoff.chat import tools as chat_tools
from handoff.chat.repository import StoreSessionRepository
from handoff.graph.hooks.narrator import Narrator
from handoff.memory.store import recall_preferences, store_user_preference
from handoff.platform.artifacts import create_artifact
from handoff.platform.models import Chat, UsageRecord
from handoff.store import get_store
from handoff.tools.mcp_discovery import discover_mcp_tools, preview_workflow, validate_workflow
from handoff.tools.scheduler import describe_schedule
from handoff.tools.workflow_store import list_workflows, save_workflow

AGENT_ID = "handoff"

ASSISTANT_PROMPT = """You are Handoff — the assistant for this workspace.

You do two kinds of work:

1. Operate the workspace. People ask what happened, what's waiting on them,
   and to run things. Use workspace_overview, recent_runs, pending_decisions,
   run_workflow_now and decide for that. Prefer doing to describing: if they
   ask you to run the inbox triage, run it and say what to watch.

2. Build workflows. When someone describes a recurring chore, follow the
   Builder's method below.

Tone: brief, concrete, no filler. Say what you did, what it means, and what
(if anything) needs them. If a decision is waiting, describe it in one line
and offer the options rather than deciding for them — unless they have told
you what to do, in which case call decide.

--- Builder's method ---
""" + BUILDER_PROMPT.split("\n", 1)[1]

_FENCE = re.compile(r"```json\s*\{.*?\}\s*```", re.S)
_BLANKS = re.compile(r"\n{3,}")
#: Nova narrates its reasoning inside <thinking> tags before answering. That
#: is useful to the model and noise to the person; the inspector still has it.
_THINKING = re.compile(r"<thinking>.*?</thinking>\s*", re.S | re.I)


def _without_config(text: str) -> str:
    """The reply minus its fenced config (shown as a card) and thinking tags."""
    return _BLANKS.sub("\n\n", _FENCE.sub("", _THINKING.sub("", text))).strip()


def _channel(chat_id: str) -> str:
    return f"chat:{chat_id}"


def _ready_mcp_tools() -> list[Any]:
    """Tools from every enabled MCP server whose credentials are present.

    A server that needs a key that isn't set is left out rather than offered
    and failed — the assistant should say "connect Linear" not "Linear errored".
    """
    import os

    from handoff.mcp.servers import load_agent_tools

    names = [
        s.name
        for s in get_store().mcp_servers.all()
        if s.enabled and all(os.environ.get(k) for k in (s.required_env or []))
    ]
    if not names:
        return []
    try:
        return load_agent_tools(names)
    except Exception as exc:
        print(f"[handoff] MCP tools unavailable for chat: {exc}")
        return []


class ChatService:
    """Chats for a workspace, and the agent behind each one."""

    def __init__(self) -> None:
        self._repo = StoreSessionRepository()
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    # -- chats -----------------------------------------------------------------

    def create(self, workspace_id: str, title: str = "New chat") -> Chat:
        chat = Chat(workspace_id=workspace_id, title=title)
        get_store().save_chat(chat)
        return chat

    def get(self, chat_id: str) -> Chat | None:
        return get_store().get_chat(chat_id)

    def list(self, workspace_id: str) -> list[Chat]:
        return get_store().list_chats(workspace_id)

    def latest(self, workspace_id: str) -> Chat | None:
        chats = self.list(workspace_id)
        return chats[0] if chats else None

    def delete(self, chat_id: str) -> None:
        get_store().delete_chat(chat_id)

    def rename(self, chat_id: str, title: str) -> None:
        chat = self.get(chat_id)
        if chat is not None:
            chat.title = title.strip()[:80] or chat.title
            chat.updated_at = datetime.now(UTC)
            get_store().save_chat(chat)

    def is_busy(self, chat_id: str) -> int | None:
        return self._active.get(chat_id)

    # -- history --------------------------------------------------------------------

    def history(self, chat_id: str) -> list[dict[str, Any]]:
        """The thread as render-ready blocks: user text, assistant text, tool cards."""
        blocks: list[dict[str, Any]] = []
        cards: dict[str, dict[str, Any]] = {}
        for row in get_store().list_chat_messages(chat_id, AGENT_ID):
            message = row.message or {}
            role = message.get("role")
            for block in message.get("content", []) or []:
                if not isinstance(block, dict):
                    continue
                if "text" in block and block["text"].strip():
                    text = block["text"]
                    if role == "assistant":
                        cfg = extract_config(text)
                        blocks.append(
                            {
                                "kind": "assistant",
                                "text": _without_config(text),
                                "config": json.dumps(cfg, indent=2) if cfg else "",
                                "config_attr": json.dumps(json.dumps(cfg, indent=2)) if cfg else "null",
                            }
                        )
                    else:
                        blocks.append({"kind": "user", "text": text})
                elif "toolUse" in block:
                    use = block["toolUse"]
                    card = {
                        "kind": "tool",
                        "tool_id": use.get("toolUseId", ""),
                        "name": use.get("name", "tool"),
                        "input": json.dumps(use.get("input", {}), indent=2, default=str),
                        "output": "",
                        "status": "ok",
                    }
                    cards[card["tool_id"]] = card
                    blocks.append(card)
                elif "toolResult" in block:
                    res = block["toolResult"]
                    card = cards.get(res.get("toolUseId", ""))
                    if card is None:
                        continue
                    out = ""
                    for c in res.get("content", []) or []:
                        if isinstance(c, dict):
                            if "text" in c:
                                out += c["text"]
                            elif "json" in c:
                                out += json.dumps(c["json"], indent=2, default=str)
                    card["output"] = out[:4000]
                    card["status"] = "error" if res.get("status") == "error" else "ok"
        return blocks

    # -- agent ----------------------------------------------------------------------

    def _agent(self, chat_id: str, turn: int, callback: Any = None) -> Agent:
        tools: list[Any] = [
            chat_tools.workspace_overview,
            chat_tools.recent_runs,
            chat_tools.pending_decisions,
            chat_tools.run_workflow_now,
            chat_tools.decide,
            recall_preferences,
            store_user_preference,
            create_artifact,
            discover_mcp_tools,
            describe_schedule,
            validate_workflow,
            preview_workflow,
            save_workflow,
            list_workflows,
        ]
        tools += _ready_mcp_tools()
        profile = get_store().get_profile()
        about = (
            f"\n\nAbout the person: {profile.full_name or 'unnamed'}"
            f"{' <' + profile.email + '>' if profile.email else ''}, timezone {profile.timezone}. "
            "Use that timezone for every schedule unless they say otherwise."
        )
        return Agent(
            model=config.get_model(),
            tools=tools,
            system_prompt=ASSISTANT_PROMPT + about,
            agent_id=AGENT_ID,
            name="Handoff",
            description="The workspace assistant",
            callback_handler=callback,
            session_manager=RepositorySessionManager(session_id=chat_id, session_repository=self._repo),
            hooks=[Narrator(_channel(chat_id), turn)],
        )

    # -- turns -------------------------------------------------------------------------

    def send(self, chat_id: str, text: str) -> int:
        """Start a turn on a worker thread. Returns the turn number to follow."""
        chat = self.get(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        with self._lock:
            if chat_id in self._active:
                raise RuntimeError("A reply is still in progress")
            turn = chat.turns + 1
            self._active[chat_id] = turn

        if chat.turns == 0 and chat.title == "New chat":
            chat.title = (text.strip().splitlines()[0])[:60]
        chat.preview = text.strip()[:120]
        chat.turns = turn
        chat.updated_at = datetime.now(UTC)
        get_store().save_chat(chat)

        threading.Thread(
            target=self._run_turn, args=(chat, turn, text), name=f"chat-{chat_id}", daemon=True
        ).start()
        return turn

    def _run_turn(self, chat: Chat, turn: int, text: str) -> None:
        channel = _channel(chat.chat_id)
        store = get_store()
        before = {p.interrupt_id for p in store.pending_interrupts()}
        started = time.monotonic()
        events.emit(channel, "turn_start", "thinking", turn=turn)
        full = ""
        usage: dict[str, int] = {}

        def on_event(**kw: Any) -> None:
            nonlocal full
            data = kw.get("data")
            if isinstance(data, str) and data:
                full += data
                events.emit(channel, "delta", data, turn=turn)

        try:
            # The sync entry point runs the event loop on its own thread with a
            # copied context, which is what keeps OpenTelemetry's span tokens
            # attached and detached in the same Context. Driving stream_async
            # from a bare asyncio.run here tripped exactly that.
            agent = self._agent(chat.chat_id, turn, on_event)
            result = agent(text)
            metrics = getattr(result, "metrics", None)
            acc = getattr(metrics, "accumulated_usage", None) or {}
            usage = {
                "input": int(acc.get("inputTokens", 0) or 0),
                "output": int(acc.get("outputTokens", 0) or 0),
            }
            if not full:
                full = str(result)
        except Exception as exc:
            events.emit(channel, "error", f"{exc}", turn=turn)
            with self._lock:
                self._active.pop(chat.chat_id, None)
            return

        cfg = extract_config(full)
        after = [p for p in store.pending_interrupts() if p.interrupt_id not in before]
        if after:
            events.emit(
                channel, "asked", f"{len(after)} decision(s) waiting",
                turn=turn, interrupt_ids=[p.interrupt_id for p in after],
            )

        if usage.get("input") or usage.get("output"):
            store.usage.put(
                UsageRecord(
                    workspace_id=chat.workspace_id,
                    run_id=chat.chat_id,
                    provider=config.active_provider(),
                    model=config.active_model_id(),
                    input_tokens=usage.get("input", 0),
                    output_tokens=usage.get("output", 0),
                ),
                "usage_id",
            )
            chat.input_tokens += usage.get("input", 0)
            chat.output_tokens += usage.get("output", 0)
        chat.preview = (_without_config(full) or chat.preview)[:120]
        chat.updated_at = datetime.now(UTC)
        store.save_chat(chat)

        events.emit(
            channel,
            "done",
            _without_config(full),
            turn=turn,
            config=json.dumps(cfg, indent=2) if cfg else "",
            usage=usage,
            ms=int((time.monotonic() - started) * 1000),
        )
        with self._lock:
            self._active.pop(chat.chat_id, None)


_service: ChatService | None = None


def get_chat_service() -> ChatService:
    global _service
    if _service is None:
        _service = ChatService()
    return _service
