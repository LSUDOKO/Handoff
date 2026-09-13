# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Adapting a host runtime's authenticated tools into Strands tools."""

from __future__ import annotations

import json

import pytest

from handoff.host.tools import (
    HostTool,
    _wanted,
    describe,
    load_host_tools,
)


class Definition:
    def __init__(self, name, description="", input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}}


class FakeTools:
    def __init__(self, definitions, result=None, raises=False):
        self._definitions = definitions
        self._result = result if result is not None else {"content": [{"type": "text", "text": "done"}]}
        self._raises = raises
        self.calls = []

    def list(self):
        return self._definitions

    def call(self, name, args):
        self.calls.append((name, args))
        if self._raises:
            raise RuntimeError("integration disconnected")
        return self._result


class FakeStream:
    def __init__(self):
        self.messages = []

    def progress(self, text, **kwargs):
        self.messages.append(text)

    intent = progress


class FakeCtx:
    def __init__(self, tools):
        self.tools = tools
        self.stream = FakeStream()


async def _call(tool: HostTool, payload: dict):
    events = [
        event
        async for event in tool.stream(
            {"toolUseId": "t1", "name": tool.tool_name, "input": payload}, {}
        )
    ]
    return events[-1].tool_result


class TestSelection:
    def test_declared_integrations_select_their_tools(self):
        ctx = FakeCtx(
            FakeTools([Definition("gmail_search"), Definition("linear_create_issue")])
        )
        assert {t.tool_name for t in load_host_tools(ctx, ["gmail"])} == {"gmail_search"}

    def test_undeclared_integrations_are_left_out(self):
        """The executor shouldn't see tools its workflow never asked for."""
        ctx = FakeCtx(FakeTools([Definition("notion_create_page")]))
        assert load_host_tools(ctx, ["gmail"]) == []

    def test_naming_differences_still_match(self):
        """`search_messages` and `gmail_search` are both Gmail."""
        ctx = FakeCtx(FakeTools([Definition("search_messages"), Definition("create_draft")]))
        assert len(load_host_tools(ctx, ["gmail"])) == 2

    def test_human_input_is_reserved_for_the_gate(self):
        """The model must not be able to interrupt on a whim."""
        ctx = FakeCtx(FakeTools([Definition("request_human_input"), Definition("gmail_search")]))
        names = {t.tool_name for t in load_host_tools(ctx, [])}
        assert "request_human_input" not in names

    def test_no_integrations_declared_means_everything(self):
        ctx = FakeCtx(FakeTools([Definition("a_tool"), Definition("b_tool")]))
        assert len(load_host_tools(ctx, [])) == 2

    def test_an_unreachable_host_yields_no_tools_rather_than_raising(self):
        class Broken:
            def list(self):
                raise RuntimeError("nats down")

        assert load_host_tools(FakeCtx(Broken()), ["gmail"]) == []

    @pytest.mark.parametrize(
        "name,integration,expected",
        [
            ("gmail_archive", "gmail", True),
            ("linear_create_issue", "linear", True),
            ("slack_post_message", "slack", True),
            ("notion_page", "gmail", False),
        ],
    )
    def test_hint_matching(self, name, integration, expected):
        assert _wanted(name, [integration]) is expected


class TestSpec:
    def test_the_schema_reaches_the_model(self):
        schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        tool = HostTool(FakeTools([]), "gmail_search", "Search mail", schema)
        spec = tool.tool_spec
        assert spec["name"] == "gmail_search"
        assert spec["description"] == "Search mail"
        assert spec["inputSchema"]["json"] == schema

    def test_a_missing_description_still_produces_a_usable_spec(self):
        tool = HostTool(FakeTools([]), "some_tool", "", {})
        assert "some_tool" in tool.tool_spec["description"]


class TestInvocation:
    async def test_arguments_reach_the_daemon(self):
        tools = FakeTools([])
        tool = HostTool(tools, "gmail_search", "", {})
        await _call(tool, {"query": "is:unread"})
        assert tools.calls == [("gmail_search", {"query": "is:unread"})]

    async def test_text_content_is_unwrapped_for_the_model(self):
        tools = FakeTools([], result={"content": [{"type": "text", "text": "3 messages"}]})
        result = await _call(HostTool(tools, "gmail_search", "", {}), {})
        assert result["status"] == "success"
        assert result["content"][0]["text"] == "3 messages"

    async def test_a_plain_dict_result_is_passed_through_as_json(self):
        tools = FakeTools([], result={"id": "ISS-1", "url": "https://linear.app/x"})
        result = await _call(HostTool(tools, "linear_create_issue", "", {}), {})
        assert json.loads(result["content"][0]["text"])["id"] == "ISS-1"

    async def test_an_mcp_error_is_reported_as_an_error(self):
        tools = FakeTools([], result={"isError": True, "content": [{"type": "text", "text": "nope"}]})
        result = await _call(HostTool(tools, "gmail_archive", "", {}), {})
        assert result["status"] == "error"

    async def test_a_dead_integration_becomes_a_tool_error_not_a_crash(self):
        """One broken integration must not take down the whole inbox run."""
        tools = FakeTools([], raises=True)
        result = await _call(HostTool(tools, "gmail_archive", "", {}), {})
        assert result["status"] == "error"
        assert "disconnected" in result["content"][0]["text"]


class TestDescribe:
    def test_says_what_is_connected(self):
        ctx = FakeCtx(FakeTools([Definition("gmail_search")]))
        assert "gmail_search" in describe(load_host_tools(ctx, ["gmail"]))

    def test_is_explicit_when_nothing_is_connected(self):
        text = describe([])
        assert "No integrations are connected" in text
        assert "nothing was carried out" in text
