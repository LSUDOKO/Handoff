# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff mcp` — tool servers: what's available, what each offers, poke one."""

from __future__ import annotations

import argparse
import json

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("mcp", help="Tool servers: list, describe, call, probe, add, remove")
    p.set_defaults(handle=handle)
    m = p.add_subparsers(dest="mcp_command", metavar="<action>")

    m.add_parser("list", help="Built-in registry plus servers you added (the default)")

    p_tools = m.add_parser("tools", help="The tools one server offers, with their schemas")
    p_tools.add_argument("server", help="Server name or id")

    p_call = m.add_parser("call", help="Call one tool and print what came back")
    p_call.add_argument("server", help="Server name or id")
    p_call.add_argument("tool")
    p_call.add_argument("--args", default="{}", metavar="JSON", help="Arguments as a JSON object")

    p_probe = m.add_parser("probe", help="Connect, list tools, record the outcome")
    p_probe.add_argument("server", help="Server name or id")

    p_add = m.add_parser("add", help="Register a server by command (stdio) or URL (http)")
    p_add.add_argument("name")
    p_add.add_argument("--command", default="", help="Executable for a stdio server")
    p_add.add_argument("--args", nargs="*", default=[], help="Arguments for the command")
    p_add.add_argument("--url", default="", help="Endpoint of a streamable-http server")
    p_add.add_argument("--env", nargs="*", default=[], metavar="VAR", help="Env vars it needs set")
    p_add.add_argument("--description", default="")

    p_remove = m.add_parser("remove", help="Forget a server you added")
    p_remove.add_argument("server", help="Server name or id")

    p_enable = m.add_parser("enable", help="Offer a server's tools to agents again")
    p_enable.add_argument("server", help="Server name or id")

    p_disable = m.add_parser("disable", help="Stop offering a server's tools to agents")
    p_disable.add_argument("server", help="Server name or id")


def _stored(ref: str):
    from handoff.store import get_store

    for server in get_store().mcp_servers.all():
        if ref in (server.server_id, server.name):
            return server
    return None


def find(ref: str):
    """A stored server; a registry entry not yet installed is installed first."""
    from handoff.mcp.servers import MCP_SERVERS
    from handoff.platform import mcp_service

    server = _stored(ref)
    if server is not None:
        return server
    if ref in MCP_SERVERS:
        return mcp_service.install_from_registry(ref, _ui.workspace())
    raise KeyError(f"No tool server named '{ref}'")


def _set_enabled(ref: str, enabled: bool) -> int:
    from handoff.store import get_store

    server = find(ref)
    server.enabled = enabled
    get_store().mcp_servers.put(server, "server_id")
    _ui.emit({"server_id": server.server_id, "name": server.name, "enabled": enabled})
    return 0


def list_rows() -> list[dict]:
    from handoff.platform import mcp_service
    from handoff.store import get_store

    stored = {s.name: s for s in get_store().mcp_servers.all()}
    rows = []
    for row in mcp_service.registry_catalogue():
        server = stored.get(row["name"])
        rows.append(
            {
                **row,
                "server_id": server.server_id if server else "",
                "enabled": server.enabled if server else False,
                "ready": mcp_service.is_ready(server) if server else bool(row["configured"]),
                "tools": server.tool_names if server else row["actions"],
                "last_error": server.last_error if server else "",
                "builtin": True,
            }
        )
    registry_names = {r["name"] for r in rows}
    for name, server in stored.items():
        if name in registry_names:
            continue
        rows.append(
            {
                "name": name,
                "description": server.description,
                "actions": server.tool_names,
                "transport": server.transport,
                "configured": mcp_service.is_ready(server),
                "requires": server.required_env,
                "installed": True,
                "server_id": server.server_id,
                "enabled": server.enabled,
                "ready": mcp_service.is_ready(server),
                "tools": server.tool_names,
                "last_error": server.last_error,
                "builtin": server.builtin,
            }
        )
    return rows


def handle(args: argparse.Namespace) -> int:
    from handoff.platform import mcp_service
    from handoff.platform.models import MCPServerConfig
    from handoff.store import get_store

    action = args.mcp_command or "list"

    if action == "list":
        rows = list_rows()
        _ui.emit(
            rows,
            lambda: _ui.table(
                "Tool servers",
                ["name", "transport", "configured", "enabled", "needs", "tools"],
                [
                    [
                        r["name"], r["transport"], _ui.yes_no(r["configured"]), _ui.yes_no(r["enabled"]),
                        ", ".join(r["requires"]) or "-", ", ".join(r["tools"]),
                    ]
                    for r in rows
                ],
            ),
        )
        return 0

    if action == "tools":
        server = find(args.server)
        tools = mcp_service.describe_tools(server)
        _ui.emit(
            tools,
            lambda: _ui.table(
                f"{server.name}: {len(tools)} tools",
                ["tool", "description", "example"],
                [[t["name"], t["description"], t["example"]] for t in tools],
            ),
        )
        return 0

    if action == "call":
        server = find(args.server)
        try:
            arguments = json.loads(args.args or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"--args is not valid JSON: {exc}") from None
        if not isinstance(arguments, dict):
            raise ValueError("--args must be a JSON object")
        result = mcp_service.invoke(server, args.tool, arguments)
        if _ui.json_mode():
            _ui.print_json(result)
        else:
            _ui.console.print(result["text"], soft_wrap=True, markup=False)
        return 1 if result.get("status") == "error" else 0

    if action == "probe":
        server = mcp_service.probe(find(args.server))
        if _ui.json_mode():
            _ui.print_json(server)
        elif server.last_error:
            _ui.fail(f"{server.name}: {server.last_error}")
        else:
            _ui.ok(f"{server.name}: {len(server.tool_names)} tools — {', '.join(server.tool_names)}")
        return 1 if server.last_error else 0

    if action == "add":
        if not args.command and not args.url:
            raise ValueError("give --command for a stdio server or --url for an http one")
        if _stored(args.name) is not None:
            raise ValueError(f"a server named '{args.name}' already exists")
        server = MCPServerConfig(
            workspace_id=_ui.workspace(),
            name=args.name,
            description=args.description,
            transport="http" if args.url else "stdio",
            command=args.command,
            args=list(args.args),
            url=args.url,
            required_env=list(args.env),
        )
        get_store().mcp_servers.put(server, "server_id")
        if _ui.json_mode():
            _ui.print_json(server)
        else:
            _ui.ok(f"added {server.name} ({server.server_id}) — `handoff mcp probe {server.name}` to test it")
        return 0

    if action == "remove":
        server = _stored(args.server)
        if server is None:
            raise KeyError(f"No tool server named '{args.server}'")
        if server.builtin:
            raise ValueError(
                f"{server.name} ships with Handoff and would come back on the next start; "
                f"`handoff mcp disable {server.name}` instead"
            )
        get_store().mcp_servers.delete("server_id", server.server_id)
        if _ui.json_mode():
            _ui.print_json({"removed": server.server_id, "name": server.name})
        else:
            _ui.ok(f"removed {server.name}")
        return 0

    if action == "enable":
        return _set_enabled(args.server, True)

    if action == "disable":
        return _set_enabled(args.server, False)

    return 2
