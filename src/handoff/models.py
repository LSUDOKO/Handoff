# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Pydantic models — the vocabulary the three agents, the gate, and the UI share."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --- Enums -----------------------------------------------------------------


class TriggerType(StrEnum):
    CRON = "cron"
    WEBHOOK = "webhook"
    EVENT = "event"
    MANUAL = "manual"


class WorkflowStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DRAFT = "draft"


class RunStatus(StrEnum):
    RUNNING = "running"
    WAITING_ON_HUMAN = "waiting_on_human"
    COMPLETED = "completed"
    FAILED = "failed"


class EmailCategory(StrEnum):
    TEAMMATE_REQUEST = "teammate_request"
    NEWSLETTER = "newsletter"
    MANAGER = "manager"
    AUTOMATED = "automated"
    AMBIGUOUS = "ambiguous"


class DecidedBy(StrEnum):
    AGENT = "agent"
    HUMAN = "human"
    MEMORY = "memory"


# --- Items flowing through a workflow --------------------------------------


class ClassifiedEmail(BaseModel):
    """One inbox item after the executor agent has reasoned about it."""

    email_id: str
    sender: str
    sender_name: str = ""
    subject: str
    snippet: str = ""
    category: EmailCategory = EmailCategory.AMBIGUOUS
    confidence: float = 0.0
    suggested_action: str = ""
    reasoning: str = ""

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


# --- The interrupt gate's payload ------------------------------------------


class AgentAnalysis(BaseModel):
    suggested_action: str = ""
    confidence: float = 0.0
    reasoning: str = ""


class InterruptItem(BaseModel):
    summary: str = ""
    sender: str = ""
    subject: str = ""
    snippet: str = ""
    item_id: str = ""


class InterruptPayload(BaseModel):
    """Everything the decision screen needs, and nothing it doesn't.

    Produced by the HITL hook, persisted by the interrupt store, rendered by
    ``ui/templates/decision.html``, and echoed back into the audit log.
    """

    interrupt_id: str = Field(default_factory=lambda: new_id("int"))
    strands_interrupt_id: str = ""
    interrupt_name: str = ""
    run_id: str = ""
    workflow_id: str = ""
    tool: str = ""
    reason: str = ""
    item: InterruptItem = Field(default_factory=InterruptItem)
    agent_analysis: AgentAnalysis = Field(default_factory=AgentAnalysis)
    options: list[str] = Field(
        default_factory=lambda: ["approve_suggested", "archive", "draft_reply", "file_ticket", "skip"]
    )
    timestamp: datetime = Field(default_factory=_now)
    resolved: bool = False
    decision: UserDecision | None = None
    #: True when this question was deferred during the pass and raised with
    #: its siblings as a single batch interrupt at the end of the run.
    batch: bool = False


class UserDecision(BaseModel):
    """What the human clicked, plus the note they optionally typed."""

    interrupt_id: str
    chosen_action: str
    user_note: str = ""
    decided_by: DecidedBy = DecidedBy.HUMAN
    timestamp: datetime = Field(default_factory=_now)


# --- Workflow configuration (what the Builder Agent emits) -----------------


class WorkflowTrigger(BaseModel):
    type: TriggerType = TriggerType.MANUAL
    schedule: str = ""
    timezone: str = "UTC"
    path: str = ""


class WorkflowCompletion(BaseModel):
    notify: str = "console"
    channel: str = ""
    message: str = "Run complete. {auto_count} handled, {interrupt_count} decided."


class WorkflowMemory(BaseModel):
    learn_from_decisions: bool = True
    preference_key: str = "default_rules"


class WorkflowConfig(BaseModel):
    """The artifact the whole product revolves around: a readable, versionable
    description of an autonomous job, including where the human gate sits."""

    workflow_id: str
    name: str
    description: str = ""
    status: WorkflowStatus = WorkflowStatus.DRAFT
    trigger: WorkflowTrigger = Field(default_factory=WorkflowTrigger)
    mcp_tools: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    completion: WorkflowCompletion = Field(default_factory=WorkflowCompletion)
    memory: WorkflowMemory = Field(default_factory=WorkflowMemory)
    confidence_threshold: float | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# --- Audit + runs ----------------------------------------------------------


class AuditEntry(BaseModel):
    """One line of the "what did the robot do last night" log."""

    entry_id: str = Field(default_factory=lambda: new_id("aud"))
    run_id: str
    workflow_id: str
    timestamp: datetime = Field(default_factory=_now)
    action: str
    item_id: str = ""
    decision_by: DecidedBy = DecidedBy.AGENT
    confidence: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    workflow_id: str
    status: RunStatus = RunStatus.RUNNING
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    trigger_type: TriggerType = TriggerType.MANUAL
    auto_count: int = 0
    interrupt_count: int = 0
    memory_count: int = 0
    summary: str = ""
    pending_interrupt_ids: list[str] = Field(default_factory=list)
    #: Serialized Strands Graph state, so a run paused on a human decision can
    #: be resumed in a different process (or after a restart).
    graph_state: dict[str, Any] | None = None


class LearnedPreference(BaseModel):
    """A rule the Learning Agent distilled from one human decision."""

    preference_id: str = Field(default_factory=lambda: new_id("pref"))
    preference_key: str
    pattern: str
    match_sender: str = ""
    match_keywords: list[str] = Field(default_factory=list)
    action: str
    confidence: float = 0.9
    source_interrupt_id: str = ""
    note: str = ""
    created_at: datetime = Field(default_factory=_now)
    times_applied: int = 0


InterruptPayload.model_rebuild()
