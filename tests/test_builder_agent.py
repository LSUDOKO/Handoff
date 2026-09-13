# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The Builder: does a sentence become a config that actually validates?"""

from __future__ import annotations

import json

from handoff.agents.builder import BuilderSession, create_builder_agent, extract_config
from handoff.store import get_store
from handoff.tools.mcp_discovery import (
    discover_mcp_tools,
    preview_workflow,
    render_preview,
    validate_workflow,
)
from handoff.tools.scheduler import cron_to_eventbridge, describe_schedule
from handoff.tools.workflow_store import save_workflow


class TestBuilderConversation:
    def test_produces_a_config_from_a_description(self, fake_model):
        session = BuilderSession(fake_model)
        result = session.send(
            "Every weekday at 8am, triage my inbox. Real asks become Linear "
            "tickets, newsletters get archived, anything unclear ask me."
        )
        assert result["has_config"]
        assert result["config"]["workflow_id"] == "inbox-triage-morning"

    def test_the_generated_config_validates(self, fake_model):
        config = BuilderSession(fake_model).send("triage my inbox")["config"]
        assert validate_workflow(json.dumps(config))["valid"]

    def test_the_generated_config_contains_a_human_gate(self, fake_model):
        """A builder that never inserts a gate has missed the point."""
        config = BuilderSession(fake_model).send("triage my inbox")["config"]
        gates = [s for s in config["steps"] if s.get("action") == "interrupt"]
        assert gates and gates[0]["options"]

    def test_agent_has_the_tools_it_needs(self, fake_model):
        names = set(create_builder_agent(fake_model).tool_names)
        assert {
            "discover_mcp_tools",
            "validate_workflow",
            "preview_workflow",
            "save_workflow",
        } <= names


class TestExtractConfig:
    def test_pulls_a_fenced_json_block(self):
        text = 'Here you go:\n```json\n{"workflow_id": "x", "name": "X"}\n```\nOK?'
        assert extract_config(text)["workflow_id"] == "x"

    def test_ignores_prose_without_a_block(self):
        assert extract_config("I need to know your timezone first.") is None

    def test_ignores_json_that_is_not_a_workflow(self):
        assert extract_config('```json\n{"foo": 1}\n```') is None

    def test_survives_malformed_json(self):
        assert extract_config('```json\n{"workflow_id": \n```') is None


class TestValidation:
    @staticmethod
    def _valid():
        return {
            "workflow_id": "x",
            "name": "X",
            "trigger": {"type": "cron", "schedule": "0 8 * * 1-5"},
            "mcp_tools": ["gmail"],
            "steps": [{"id": "human_gate", "action": "interrupt"}],
        }

    def test_accepts_a_well_formed_config(self):
        assert validate_workflow(json.dumps(self._valid()))["valid"]

    def test_rejects_invalid_json(self):
        result = validate_workflow("{not json")
        assert not result["valid"] and "Invalid JSON" in result["errors"][0]

    def test_rejects_a_missing_trigger(self):
        config = self._valid()
        del config["trigger"]
        result = validate_workflow(json.dumps(config))
        assert not result["valid"]
        assert any("trigger" in e for e in result["errors"])

    def test_rejects_a_malformed_cron_expression(self):
        config = self._valid()
        config["trigger"]["schedule"] = "0 8 *"
        result = validate_workflow(json.dumps(config))
        assert not result["valid"]
        assert any("3 fields" in e for e in result["errors"])

    def test_rejects_an_unknown_integration(self):
        config = self._valid()
        config["mcp_tools"] = ["telepathy"]
        assert not validate_workflow(json.dumps(config))["valid"]

    def test_warns_when_a_workflow_has_no_human_gate(self):
        config = self._valid()
        config["steps"] = [{"id": "do_everything", "action": "gmail.send"}]
        result = validate_workflow(json.dumps(config))
        assert result["valid"]
        assert any("No human gate" in w for w in result["warnings"])

    def test_warns_about_unconfigured_integrations(self):
        result = validate_workflow(json.dumps(self._valid()))
        assert any("not configured" in w for w in result["warnings"])


class TestPreview:
    def test_reads_back_in_plain_language(self, fake_model):
        config = BuilderSession(fake_model).send("triage my inbox")["config"]
        text = preview_workflow(json.dumps(config))
        assert "Morning Inbox Triage" in text
        assert "0 8 * * 1-5" in text
        assert "Asks you about:" in text
        assert "Handles on its own:" in text

    def test_says_so_when_nothing_is_gated(self):
        text = render_preview(
            {"name": "Silent", "trigger": {"type": "manual"}, "steps": [], "mcp_tools": []}
        )
        assert "never interrupts you" in text


class TestSchedule:
    def test_weekday_cron_converts_to_eventbridge(self):
        assert cron_to_eventbridge("0 8 * * 1-5") == "cron(0 8 ? * 2-6 *)"

    def test_daily_cron_uses_a_wildcard_day_of_month(self):
        assert cron_to_eventbridge("30 9 * * *") == "cron(30 9 * * ? *)"

    def test_describes_a_schedule_in_words(self):
        result = describe_schedule("0 8 * * 1-5", "America/New_York")
        assert result["valid"]
        assert "08:00" in result["readable"]
        assert "every weekday" in result["readable"]

    def test_rejects_a_malformed_expression(self):
        assert not describe_schedule("nonsense")["valid"]


class TestSaving:
    def test_saves_a_valid_workflow_as_a_draft(self, fake_model):
        config = BuilderSession(fake_model).send("triage my inbox")["config"]
        result = save_workflow(json.dumps(config))
        assert result["saved"]
        assert result["status"] == "draft"
        assert get_store().get_workflow(config["workflow_id"]) is not None

    def test_activate_flag_marks_it_active(self, fake_model):
        config = BuilderSession(fake_model).send("triage my inbox")["config"]
        assert save_workflow(json.dumps(config), activate=True)["status"] == "active"

    def test_refuses_to_save_an_invalid_config(self):
        result = save_workflow(json.dumps({"name": "no id"}))
        assert not result["saved"] and result["errors"]


class TestDiscovery:
    def test_lists_the_integration_registry(self):
        tools = discover_mcp_tools()
        names = {t["name"] for t in tools}
        assert {"gmail", "linear", "slack", "browser"} <= names
        assert all("actions" in t and "configured" in t for t in tools)
