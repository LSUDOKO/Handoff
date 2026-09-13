# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""A deterministic stand-in for Bedrock.

Two jobs:

* **Tests.** Assertions about the interrupt gate should fail when the gate
  breaks, not when a model has an off day.
* **Offline demo.** ``HANDOFF_FAKE_MODEL=true`` runs the full graph — tools,
  gate, interrupts, resume, learning — on a plane, in a conference hall with
  bad wifi, or in a CI job with no AWS credentials.

It is stateless on purpose. Rather than counting its own turns, it reads the
message history and works out what has already happened, so it behaves
correctly when Strands replays a turn after an interrupt is resolved.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from typing import Any

from strands.models.model import Model

from handoff.memory.store import find_matching_preference
from handoff.runtime import current_run
from handoff.tools.mock_data import (
    EXPECTED_CLASSIFICATIONS,
    MOCK_EMAILS,
    MOCK_REASONING,
)

_OPTIONS = ["approve_suggested", "file_ticket", "archive", "draft_reply", "skip"]


def _tool_uses(messages: list[dict]) -> list[str]:
    """Names of every tool the assistant has already asked for."""
    names: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for block in message.get("content", []) or []:
            if isinstance(block, dict) and "toolUse" in block:
                names.append(block["toolUse"].get("name", ""))
    return names


def _tool_specs_names(tool_specs: list[dict] | None) -> set[str]:
    return {spec.get("name", "") for spec in (tool_specs or [])}


class FakeModel(Model):
    """Scripted model driving the inbox-triage, builder and learner agents."""

    def __init__(self, **kwargs: Any) -> None:
        self._config: dict[str, Any] = {"model_id": "handoff-fake-model", **kwargs}

    # -- Model interface ---------------------------------------------------

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self._config

    async def structured_output(
        self, output_model: type, prompt: list, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {"output": output_model()}

    async def stream(
        self,
        messages: list[dict],
        tool_specs: list[dict] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        available = _tool_specs_names(tool_specs)
        called = _tool_uses(messages)

        if "submit_action" in available:
            blocks = self._executor_turn(called)
        elif "finalize_run" in available:
            blocks = self._completer_turn(called)
        elif "validate_workflow" in available:
            blocks = self._builder_turn(called, messages)
        elif "store_user_preference" in available:
            blocks = self._learner_turn(called, messages)
        elif "check_trigger" in available:
            blocks = self._trigger_turn(called, messages)
        else:
            blocks = [{"text": "Done."}]

        async for event in self._emit(blocks):
            yield event

    # -- emission ----------------------------------------------------------

    async def _emit(self, blocks: list[dict]) -> AsyncGenerator[dict[str, Any], None]:
        yield {"messageStart": {"role": "assistant"}}

        has_tool_use = False
        for block in blocks:
            if "toolUse" in block:
                has_tool_use = True
                use = block["toolUse"]
                yield {
                    "contentBlockStart": {
                        "start": {
                            "toolUse": {
                                "toolUseId": use["toolUseId"],
                                "name": use["name"],
                            }
                        }
                    }
                }
                yield {
                    "contentBlockDelta": {
                        "delta": {"toolUse": {"input": json.dumps(use["input"])}}
                    }
                }
                yield {"contentBlockStop": {}}
            else:
                yield {"contentBlockStart": {"start": {}}}
                yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
                yield {"contentBlockStop": {}}

        yield {"messageStop": {"stopReason": "tool_use" if has_tool_use else "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }

    # -- scripts -----------------------------------------------------------

    def _trigger_turn(self, called: list[str], messages: list[dict]) -> list[dict]:
        if "check_trigger" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": "fake_trigger",
                        "name": "check_trigger",
                        "input": {"trigger_type": "cron"},
                    }
                }
            ]
        return [{"text": "Trigger confirmed. Proceeding with the run."}]

    def _executor_turn(self, called: list[str]) -> list[dict]:
        if "recall_preferences" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": "fake_recall",
                        "name": "recall_preferences",
                        "input": {
                            "context": "morning inbox triage",
                            "preference_key": "inbox_triage_rules",
                        },
                    }
                }
            ]

        if "fetch_unread_emails" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": "fake_fetch",
                        "name": "fetch_unread_emails",
                        "input": {"query": "is:unread newer_than:12h", "max_results": 20},
                    }
                }
            ]

        if "classify_email" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": f"fake_classify_{email['email_id']}",
                        "name": "classify_email",
                        "input": {
                            "email_id": email["email_id"],
                            "sender": email["sender"],
                            "subject": email["subject"],
                            "snippet": email["snippet"],
                            "category": EXPECTED_CLASSIFICATIONS[email["email_id"]]["category"],
                            "confidence": EXPECTED_CLASSIFICATIONS[email["email_id"]]["confidence"],
                            "suggested_action": EXPECTED_CLASSIFICATIONS[email["email_id"]]["action"],
                            "reasoning": MOCK_REASONING.get(email["email_id"], ""),
                        },
                    }
                }
                for email in MOCK_EMAILS
            ]

        if "submit_action" not in called:
            blocks: list[dict] = []
            for email in MOCK_EMAILS:
                expected = EXPECTED_CLASSIFICATIONS[email["email_id"]]
                ambiguous = expected["category"] == "ambiguous"
                action = expected["action"]
                confidence = expected["confidence"]
                preference_id = ""

                # A real model reads the raised confidence off classify_email's
                # result and stops escalating. Mirror that here so the offline
                # demo shows the same thing: run one asks three questions, run
                # two asks none, because the answers are now rules.
                preference = find_matching_preference(
                    sender=email["sender"],
                    subject=email["subject"],
                    snippet=email["snippet"],
                )
                if preference is not None:
                    action = preference.action
                    confidence = max(confidence, preference.confidence)
                    preference_id = preference.preference_id
                    ambiguous = False

                blocks.append(
                    {
                        "toolUse": {
                            "toolUseId": f"fake_submit_{email['email_id']}",
                            "name": "submit_action",
                            "input": {
                                "action": action,
                                "item_id": email["email_id"],
                                "summary": f"{email['subject']} — from {email['sender_name']}",
                                "confidence": confidence,
                                "reasoning": MOCK_REASONING.get(email["email_id"], ""),
                                "sender": email["sender"],
                                "subject": email["subject"],
                                "snippet": email["snippet"],
                                "options": _OPTIONS,
                                "force_interrupt": ambiguous,
                                "applied_preference": preference_id,
                            },
                        }
                    }
                )
            return blocks

        if "finish_batch" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": "fake_finish_batch",
                        "name": "finish_batch",
                        "input": {},
                    }
                }
            ]

        return [
            {
                "text": (
                    "Every message has an action. Handing off to the completer."
                )
            }
        ]

    def _completer_turn(self, called: list[str]) -> list[dict]:
        if "finalize_run" in called:
            return [{"text": "Run closed out."}]

        # Summarise what actually happened this run, not what usually happens —
        # otherwise run two still claims it asked three questions.
        ctx = current_run()
        auto = ctx.auto_count if ctx else 0
        from_memory = ctx.memory_count if ctx else 0
        asked = ctx.human_count if ctx else 0

        parts = [f"Triaged {len(MOCK_EMAILS)} messages."]
        if auto:
            parts.append(
                f"Handled {auto} on my own: teammate requests filed as tickets, "
                f"newsletters archived, manager mail drafted."
            )
        if from_memory:
            parts.append(
                f"Handled {from_memory} more using rules you set on an earlier run, "
                f"so I didn't need to ask again."
            )
        parts.append(
            f"Escalated {asked} I couldn't call confidently."
            if asked
            else "Nothing needed your input this time."
        )

        return [
            {
                "toolUse": {
                    "toolUseId": "fake_finalize",
                    "name": "finalize_run",
                    "input": {"summary": " ".join(parts)},
                }
            }
        ]

    def _builder_turn(self, called: list[str], messages: list[dict]) -> list[dict]:
        if "discover_mcp_tools" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": "fake_discover",
                        "name": "discover_mcp_tools",
                        "input": {},
                    }
                }
            ]

        config = _demo_workflow_config()
        if "validate_workflow" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": "fake_validate",
                        "name": "validate_workflow",
                        "input": {"config_json": json.dumps(config)},
                    }
                }
            ]

        if "preview_workflow" not in called:
            return [
                {
                    "toolUse": {
                        "toolUseId": "fake_preview",
                        "name": "preview_workflow",
                        "input": {"config_json": json.dumps(config)},
                    }
                }
            ]

        return [
            {
                "text": (
                    "Here's what I'll build:\n\n```json\n"
                    + json.dumps(config, indent=2)
                    + "\n```\n\nSay the word and I'll save it."
                )
            }
        ]

    def _learner_turn(self, called: list[str], messages: list[dict]) -> list[dict]:
        if "store_user_preference" in called:
            return [{"text": "Rule stored. I won't ask about that one again."}]

        text = json.dumps(messages)[-4000:]
        sender = ""
        for email in MOCK_EMAILS:
            if email["sender"] in text:
                sender = email["sender"]
                break
        match = re.search(r"What they chose:\s*([a-z_]+)", text)
        action = match.group(1) if match else "archive"

        return [
            {
                "toolUse": {
                    "toolUseId": "fake_learn",
                    "name": "store_user_preference",
                    "input": {
                        "pattern": f"Always {action.replace('_', ' ')} mail from {sender or 'this sender'}",
                        "action": action,
                        "match_sender": sender,
                        "confidence": 0.92,
                    },
                }
            }
        ]


def _demo_workflow_config() -> dict[str, Any]:
    """The config the fake Builder 'writes' — matches workflows/examples."""
    return {
        "workflow_id": "inbox-triage-morning",
        "name": "Morning Inbox Triage",
        "description": "Triage unread mail, file real asks, archive noise, ask about the rest.",
        "trigger": {"type": "cron", "schedule": "0 8 * * 1-5", "timezone": "America/New_York"},
        "mcp_tools": ["gmail", "linear", "slack"],
        "steps": [
            {
                "id": "fetch_emails",
                "action": "gmail.search_threads",
                "params": {"query": "is:unread newer_than:12h"},
            },
            {
                "id": "classify",
                "action": "llm_classify",
                "input_from": "fetch_emails",
                "categories": ["teammate_request", "newsletter", "manager", "automated", "ambiguous"],
            },
            {
                "id": "auto_actions",
                "rules": [
                    {"category": "teammate_request", "action": "linear.create_issue", "auto": True},
                    {"category": "newsletter", "action": "gmail.archive", "auto": True},
                    {"category": "manager", "action": "gmail.create_draft", "auto": True},
                    {"category": "automated", "action": "linear.create_issue", "auto": True},
                ],
            },
            {
                "id": "human_gate",
                "category": "ambiguous",
                "action": "interrupt",
                "present": ["email_summary", "sender", "suggested_action"],
                "options": ["file_ticket", "archive", "draft_reply", "skip"],
            },
        ],
        "completion": {
            "notify": "slack",
            "channel": "#daily-triage",
            "message": "Morning triage complete. {auto_count} handled, {interrupt_count} decided by you.",
        },
        "memory": {"learn_from_decisions": True, "preference_key": "inbox_triage_rules"},
    }
