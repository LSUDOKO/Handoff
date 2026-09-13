# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff agents` — the agents you authored, and running one on a prompt."""

from __future__ import annotations

import argparse

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("agents", help="List, inspect or run the workspace's agents")
    p.set_defaults(handle=handle)
    a = p.add_subparsers(dest="agents_command", metavar="<action>")

    a.add_parser("list", help="Every agent in the workspace (the default)")

    p_show = a.add_parser("show", help="An agent's prompt, tools and what it needs connected")
    p_show.add_argument("agent", help="Agent id or name")

    p_run = a.add_parser("run", help="Run an agent on a prompt and watch it work")
    p_run.add_argument("agent", help="Agent id or name")
    p_run.add_argument("prompt", nargs="+", help="What to ask it")


def find(ref: str):
    """By id first, then by name — people type names."""
    from handoff.store import get_store

    agents = get_store().list_custom_agents(_ui.workspace())
    for agent in agents:
        if agent.agent_id == ref:
            return agent
    for agent in agents:
        if agent.name.lower() == ref.lower():
            return agent
    raise KeyError(f"No agent with id or name '{ref}'")


def handle(args: argparse.Namespace) -> int:
    from handoff.platform import workbench
    from handoff.store import get_store

    action = args.agents_command or "list"

    if action == "list":
        agents = get_store().list_custom_agents(_ui.workspace())
        _ui.emit(
            agents,
            lambda: _ui.table(
                "Agents",
                ["id", "name", "tools", "on", "built-in", "description"],
                [
                    [a.agent_id, a.name, len(a.tools), _ui.yes_no(a.enabled), _ui.yes_no(a.builtin), a.description]
                    for a in agents
                ],
            ),
        )
        return 0

    if action == "show":
        agent = find(args.agent)
        needs = workbench.preflight(agent)
        if _ui.json_mode():
            _ui.print_json({**agent.model_dump(mode="json"), "preflight": needs})
            return 0
        _ui.console.print(
            _ui.kv_table(
                agent.name,
                {
                    "id": agent.agent_id,
                    "description": agent.description,
                    "tools": ", ".join(agent.tools) or "none",
                    "skills": ", ".join(agent.skills) or "none",
                    "model": agent.model_override or "workspace default",
                    "enabled": _ui.yes_no(agent.enabled),
                    "built-in": _ui.yes_no(agent.builtin),
                    "needs": ", ".join(
                        f"{n['label']} ({'connected' if n['connected'] else n['status']})" for n in needs
                    ) or "no credentials",
                },
            )
        )
        if agent.system_prompt.strip():
            _ui.console.print(_ui.code_panel(agent.system_prompt.strip(), title="system prompt", lexer="markdown"))
        return 0

    if action == "run":
        from handoff.cli.chat import stream_turn

        agent = find(args.agent)
        if not agent.enabled:
            raise ValueError(f"{agent.name} is disabled")
        record = workbench.run(agent, " ".join(args.prompt))
        if not _ui.json_mode():
            _ui.dim(f"run {record.run_id} on {record.model}")
        final = stream_turn(workbench.channel(record.run_id), start=None, turn=1)
        return 1 if final.get("kind") == "error" else 0

    return 2
