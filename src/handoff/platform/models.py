# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Data models for the platform layer.

Everything here is persisted through the same JSON/DynamoDB store the core
uses, so a workspace, a credential and a workflow run all survive a restart
the same way.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from handoff.models import new_id


def _now() -> datetime:
    return datetime.now(UTC)


def slugify(text: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or fallback


# --- Workspaces -------------------------------------------------------------


class Workspace(BaseModel):
    """A named container: its own workflows, agents, memory and connections.

    Separate workspaces exist so "my inbox" and "the team's on-call rota"
    don't share learned rules or credentials. A rule you set for your own mail
    should not start acting on a shared account.
    """

    workspace_id: str = Field(default_factory=lambda: new_id("ws"))
    name: str
    description: str = ""
    icon: str = "◆"
    #: Sidebar dot. One of amber, blue, green, red, purple, grey.
    color: str = "amber"
    is_default: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# --- Credentials ------------------------------------------------------------


class CredentialKind(StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth"
    WEBHOOK = "webhook"
    TOKEN = "token"


class CredentialStatus(StrEnum):
    CONNECTED = "connected"
    NEEDS_ATTENTION = "needs_attention"
    DISCONNECTED = "disconnected"


class Credential(BaseModel):
    """One connection to an outside service.

    The secret is never returned to the browser — ``masked`` is what the UI
    shows, and ``fingerprint`` lets you tell two keys apart without seeing
    either. The value itself is read only by the tool that needs it.
    """

    credential_id: str = Field(default_factory=lambda: new_id("cred"))
    workspace_id: str = ""
    provider: str
    label: str = ""
    kind: CredentialKind = CredentialKind.API_KEY
    secret: str = ""
    status: CredentialStatus = CredentialStatus.DISCONNECTED
    last_checked: datetime | None = None
    last_error: str = ""
    created_at: datetime = Field(default_factory=_now)

    @property
    def masked(self) -> str:
        if not self.secret:
            return ""
        if len(self.secret) <= 8:
            return "•" * len(self.secret)
        return f"{self.secret[:4]}{'•' * 8}{self.secret[-4:]}"

    @property
    def fingerprint(self) -> str:
        if not self.secret:
            return ""
        return hashlib.sha256(self.secret.encode()).hexdigest()[:8]

    def redacted(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"secret"})
        data["masked"] = self.masked
        data["fingerprint"] = self.fingerprint
        return data


# --- MCP servers ------------------------------------------------------------


class MCPServerConfig(BaseModel):
    """A tool server this workspace can reach.

    Mirrors the built-in registry's shape so a server you add by hand and one
    that ships with Handoff are the same kind of thing to the executor.
    """

    server_id: str = Field(default_factory=lambda: new_id("mcp"))
    workspace_id: str = ""
    name: str
    description: str = ""
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    required_env: list[str] = Field(default_factory=list)
    enabled: bool = True
    builtin: bool = False
    last_error: str = ""
    tool_names: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


# --- Skills -----------------------------------------------------------------


class Skill(BaseModel):
    """A named piece of instruction an agent can be given.

    Markdown with a name and a description, exactly like the skills the
    hosting conventions use: the description is what an agent reads to decide
    whether the body is worth loading.
    """

    skill_id: str = Field(default_factory=lambda: new_id("skill"))
    workspace_id: str = ""
    namespace: str = "workspace"
    name: str
    description: str = ""
    body: str = ""
    enabled: bool = True
    builtin: bool = False
    #: Previous versions, newest first, so an edit can be compared and undone.
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def qualified(self) -> str:
        return f"{self.namespace}:{self.name}"


# --- Author-your-own agents -------------------------------------------------


class CustomAgent(BaseModel):
    """An agent you defined in the UI rather than one that ships with Handoff.

    It is a Strands ``Agent`` like any other — a system prompt, a set of
    tools, optionally some skills folded into the prompt, and a model.
    """

    agent_id: str = Field(default_factory=lambda: new_id("agent"))
    workspace_id: str = ""
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    model_override: str = ""
    temperature: float | None = None
    max_steps: int = 12
    enabled: bool = True
    builtin: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# --- Memory -----------------------------------------------------------------


class MemoryKind(StrEnum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class MemoryStore(BaseModel):
    """A named store. Short-term is one run's working notes; long-term is
    what the agent is allowed to carry into the next run."""

    store_id: str = Field(default_factory=lambda: new_id("mem"))
    workspace_id: str = ""
    name: str
    kind: MemoryKind = MemoryKind.LONG_TERM
    strategy: str = "narrative"
    description: str = ""
    created_at: datetime = Field(default_factory=_now)


class MemoryEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: new_id("ment"))
    store_id: str = ""
    workspace_id: str = ""
    key: str = ""
    content: str = ""
    source: str = ""
    created_at: datetime = Field(default_factory=_now)


# --- Schedules --------------------------------------------------------------


class Schedule(BaseModel):
    """A cron trigger the daemon fires. Distinct from the workflow's own
    declared trigger: this is the live, switchable instance of it."""

    schedule_id: str = Field(default_factory=lambda: new_id("sched"))
    workspace_id: str = ""
    workflow_id: str
    cron: str
    timezone: str = "UTC"
    enabled: bool = True
    last_run_at: datetime | None = None
    last_run_id: str = ""
    next_run_at: datetime | None = None
    run_count: int = 0
    created_at: datetime = Field(default_factory=_now)


# --- Artifacts --------------------------------------------------------------


class Artifact(BaseModel):
    """Something a run produced that is worth keeping and looking at."""

    artifact_id: str = Field(default_factory=lambda: new_id("art"))
    workspace_id: str = ""
    run_id: str = ""
    name: str
    kind: str = "text"
    content: str = ""
    produced_by: str = ""
    created_at: datetime = Field(default_factory=_now)

    @property
    def size(self) -> int:
        return len(self.content)


# --- Sessions (the deep trace) ----------------------------------------------


class SessionStep(BaseModel):
    """One thing that happened inside a run, in order.

    Model calls and tool calls both land here, which is what makes the
    inspector useful: you can see the reasoning turn that *led to* a tool
    call sitting directly above it.
    """

    step_id: str = Field(default_factory=lambda: new_id("step"))
    index: int = 0
    kind: str = "tool"
    node: str = ""
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    output: str = ""
    status: str = "ok"
    gated: bool = False
    duration_ms: int = 0
    at: datetime = Field(default_factory=_now)


class Session(BaseModel):
    """The inspectable record of one run."""

    session_id: str = Field(default_factory=lambda: new_id("sess"))
    run_id: str = ""
    workspace_id: str = ""
    workflow_id: str = ""
    steps: list[SessionStep] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None

    @property
    def tool_calls(self) -> int:
        return sum(1 for s in self.steps if s.kind == "tool")

    @property
    def model_calls(self) -> int:
        return sum(1 for s in self.steps if s.kind == "model")


# --- Usage ------------------------------------------------------------------


class UsageRecord(BaseModel):
    """Tokens spent, so the cost of an agent that runs every morning is a
    number you can look at rather than a surprise at the end of the month."""

    usage_id: str = Field(default_factory=lambda: new_id("use"))
    workspace_id: str = ""
    run_id: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    at: datetime = Field(default_factory=_now)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# --- Chat --------------------------------------------------------------------


class Chat(BaseModel):
    """One conversation with the workspace's assistant.

    The messages themselves are the Strands session — persisted through a
    SessionRepository backed by the same store — so a chat survives a restart
    and lives in DynamoDB when deployed. This row is the index entry: what to
    show in the list, and which agent the thread belongs to.
    """

    chat_id: str = Field(default_factory=lambda: new_id("chat"))
    workspace_id: str = ""
    agent_id: str = "handoff"
    title: str = "New chat"
    preview: str = ""
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ChatMessage(BaseModel):
    """A Strands session message, stored one row per message."""

    row_id: str = ""
    chat_id: str = ""
    agent_id: str = "handoff"
    message_id: int = 0
    message: dict[str, Any] = Field(default_factory=dict)
    redact_message: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""


class ChatAgentState(BaseModel):
    """The Strands SessionAgent record: state and conversation-manager state."""

    row_id: str = ""
    chat_id: str = ""
    agent_id: str = "handoff"
    state: dict[str, Any] = Field(default_factory=dict)
    conversation_manager_state: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


# --- Agent workbench -----------------------------------------------------------


class AgentRun(BaseModel):
    """One run of an agent from the workbench: prompt in, result and trace out."""

    run_id: str = Field(default_factory=lambda: new_id("arun"))
    agent_id: str = ""
    workspace_id: str = ""
    prompt: str = ""
    status: str = "running"  # running | completed | failed
    result: str = ""
    error: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
