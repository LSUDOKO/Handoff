# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The Builder Agent — turns a sentence into a workflow you can read.

This is the conversational half of Handoff. The user describes a recurring
chore; the Builder works out which integrations it needs, when it should fire,
and — the part that matters — where the line sits between what it may do alone
and what it must ask about.

It is a separate agent from the executor on purpose. Designing a workflow and
running one need different context, different tools and different failure
modes; collapsing them into a single agent makes both worse.
"""

from __future__ import annotations

import json
import re
from typing import Any

from strands import Agent

from handoff import config
from handoff.tools.mcp_discovery import (
    discover_mcp_tools,
    preview_workflow,
    validate_workflow,
)
from handoff.tools.scheduler import describe_schedule
from handoff.tools.workflow_store import list_workflows, save_workflow

BUILDER_PROMPT = """You are Handoff's Builder.

Someone describes a chore they do over and over. You turn it into a workflow
config they can read, version and hand to a teammate.

How to work:

1. Call discover_mcp_tools first. Design around what they actually have. If
   something they need isn't connected, design it anyway and tell them plainly
   which integration to connect.
2. Work out the trigger. "Every morning" means a cron expression — call
   describe_schedule and read it back in words so they can catch a mistake
   without parsing cron.
3. Decide what runs automatically and what stops for them. This is the most
   important judgement you make, so make it explicitly:
   - Automatic: unambiguous, reversible, or low-stakes. Archiving a newsletter.
     Filing a ticket from a named teammate's clear request.
   - Ask first: anything irreversible, anything involving an unknown party,
     anything where being wrong costs more than being slow. Sending mail on
     their behalf. Deleting. Spending money.
   If they didn't say where the line goes, propose one and say why.
4. Call validate_workflow, then preview_workflow, and show them the preview
   before saving anything.
5. Only call save_workflow once they've agreed to what the preview says.

Ask a clarifying question when the answer would change the config — the
schedule, the destination, what counts as "urgent". Don't interrogate them
about things you can sensibly default and mention.

The config schema:

{
  "workflow_id": "kebab-case-id",
  "name": "Human readable name",
  "description": "One line",
  "trigger": {"type": "cron|webhook|event|manual", "schedule": "0 8 * * 1-5",
              "timezone": "America/New_York"},
  "mcp_tools": ["gmail", "linear", "slack"],
  "steps": [
    {"id": "fetch", "action": "gmail.search_threads", "params": {...}},
    {"id": "classify", "action": "llm_classify", "input_from": "fetch",
     "categories": [...]},
    {"id": "auto_actions", "rules": [
      {"category": "...", "action": "...", "auto": true}
    ]},
    {"id": "human_gate", "category": "ambiguous", "action": "interrupt",
     "present": ["email_summary", "sender", "suggested_action"],
     "options": ["file_ticket", "archive", "draft_reply", "skip"]}
  ],
  "completion": {"notify": "slack", "channel": "#channel",
                 "message": "Done. {auto_count} handled, {interrupt_count} for you."},
  "memory": {"learn_from_decisions": true, "preference_key": "unique_key"}
}

When you present a config, put it in a ```json fenced block so the interface
can pick it up."""


_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def create_builder_agent(model: Any = None) -> Agent:
    """Construct the Builder Agent."""
    return Agent(
        model=model if model is not None else config.get_model(),
        tools=[
            discover_mcp_tools,
            describe_schedule,
            validate_workflow,
            preview_workflow,
            save_workflow,
            list_workflows,
        ],
        system_prompt=BUILDER_PROMPT,
        name="builder",
        description="Turns a natural-language description into a workflow config",
        callback_handler=None,
    )


def extract_config(text: str) -> dict[str, Any] | None:
    """Pull the first fenced JSON workflow config out of an agent reply."""
    match = _JSON_BLOCK.search(text or "")
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) and "workflow_id" in parsed else None


class BuilderSession:
    """A stateful chat with the Builder, as the UI's /chat route uses it."""

    def __init__(self, model: Any = None) -> None:
        self.agent = create_builder_agent(model)
        self.last_config: dict[str, Any] | None = None

    def send(self, message: str) -> dict[str, Any]:
        """Send one user turn; return the reply and any config it produced."""
        result = self.agent(message)
        text = str(result)
        cfg = extract_config(text)
        if cfg is not None:
            self.last_config = cfg
        return {
            "reply": text,
            "config": cfg,
            "has_config": cfg is not None,
        }

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self.agent.messages)
