# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Agents you author yourself.

Handoff ships three agents with opinions baked in — Builder, Executor,
Learner. This is for the fourth one you need and nobody anticipated: a
prompt, a set of tools, some skills, and a model. It becomes a real Strands
``Agent``, gated by the same interrupt hook as everything else, so an agent
you wrote in a text box is as safe as one that shipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from handoff.platform.models import CustomAgent
from handoff.platform.skills import compose
from handoff.store import get_store

#: Tools a custom agent may be given, and what each is for. Deliberately a
#: allow-list: an agent you assembled in a form should not reach anything the
#: UI didn't offer you.
AVAILABLE_TOOLS: dict[str, str] = {
    "fetch_unread_emails": "Read unread mail",
    "get_email_body": "Read one message in full",
    "classify_email": "Record a classification",
    "submit_action": "Act on an item (gated by the human decision gate)",
    "finish_batch": "Ask about everything set aside, at the end of a pass",
    "recall_preferences": "Read rules the user set earlier",
    "store_user_preference": "Write a rule for future runs",
    "check_competitor_pricing": "Read a pricing page and diff it",
    "read_audit_log": "Read what past runs did",
    "notify_user": "Send a message to the user",
    "create_artifact": "Save a document this run produced",
    "describe_schedule": "Explain a cron expression in words",
}

BUILTIN_AGENTS: list[dict[str, Any]] = [
    {
        "name": "Inbox Executor",
        "description": "The agent that triages. Handles what it can judge; asks about the rest.",
        "system_prompt": "",
        "tools": [
            "recall_preferences",
            "fetch_unread_emails",
            "get_email_body",
            "classify_email",
            "submit_action",
            "finish_batch",
        ],
    },
    {
        "name": "Digest Writer",
        "description": "Reads a run's audit trail and writes a short summary document.",
        "system_prompt": (
            "You summarise what an automated run did, for someone who wasn't "
            "watching.\n\n"
            "Read the audit log, then write a short digest and save it with "
            "create_artifact. Lead with what was handled without them, then "
            "what needed a decision and why. Be concrete about counts. Do not "
            "pad it — this is read at a glance over coffee."
        ),
        "tools": ["read_audit_log", "create_artifact", "notify_user"],
    },
]


def resolve_tools(names: list[str]) -> list[Any]:
    """Turn tool names into the actual ``@tool`` functions."""
    from handoff.graph.nodes.classifier import classify_email
    from handoff.graph.nodes.executor import (
        check_competitor_pricing,
        fetch_unread_emails,
        get_email_body,
    )
    from handoff.graph.nodes.gate import finish_batch, submit_action
    from handoff.memory.store import recall_preferences, store_user_preference
    from handoff.platform.artifacts import create_artifact
    from handoff.tools.audit_log import read_audit_log
    from handoff.tools.notify import notify_user
    from handoff.tools.scheduler import describe_schedule

    registry = {
        "fetch_unread_emails": fetch_unread_emails,
        "get_email_body": get_email_body,
        "classify_email": classify_email,
        "submit_action": submit_action,
        "finish_batch": finish_batch,
        "recall_preferences": recall_preferences,
        "store_user_preference": store_user_preference,
        "check_competitor_pricing": check_competitor_pricing,
        "read_audit_log": read_audit_log,
        "notify_user": notify_user,
        "create_artifact": create_artifact,
        "describe_schedule": describe_schedule,
    }
    return [registry[n] for n in names if n in registry]


def build(definition: CustomAgent, model: Any = None, gate: Any = None) -> Any:
    """Turn a stored definition into a live Strands ``Agent``."""
    from strands import Agent

    from handoff import config

    prompt = definition.system_prompt.strip()
    skills_block = compose(definition.skills, definition.workspace_id or None)
    if skills_block:
        prompt = f"{prompt}\n\n{skills_block}".strip()

    return Agent(
        model=model if model is not None else config.get_model(),
        tools=resolve_tools(definition.tools),
        system_prompt=prompt or "You are a helpful agent.",
        hooks=[gate] if gate is not None else [],
        name=definition.name,
        description=definition.description,
        callback_handler=None,
    )


def save(definition: CustomAgent) -> CustomAgent:
    definition.updated_at = datetime.now(UTC)
    get_store().custom_agents.put(definition, "agent_id")
    return definition


def seed_builtin_agents(workspace_id: str = "") -> list[CustomAgent]:
    store = get_store()
    existing = {a.name for a in store.custom_agents.all()}
    created: list[CustomAgent] = []
    for spec in BUILTIN_AGENTS:
        if spec["name"] in existing:
            continue
        agent = CustomAgent(
            workspace_id=workspace_id,
            name=spec["name"],
            description=spec["description"],
            system_prompt=spec["system_prompt"],
            tools=spec["tools"],
            builtin=True,
        )
        store.custom_agents.put(agent, "agent_id")
        created.append(agent)
    return created
