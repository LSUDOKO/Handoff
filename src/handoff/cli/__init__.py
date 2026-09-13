# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff` on the command line: everything the web UI does, from a terminal.

One argparse tree, built from a module per command group. Each module
exposes ``register(subparsers)`` and ``handle(args) -> int``; the parser is
also what generates the docs' CLI reference, so a command that isn't
registered here doesn't exist as far as the documentation is concerned.

Exit codes: 0 ok, 1 something failed, 2 not found or a bad argument.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from handoff.cli import _ui

#: Help order. Everyday commands first, plumbing last.
_GROUP_MODULES = (
    "handoff.cli.chat",
    "handoff.cli.runs",
    "handoff.cli.workflows",
    "handoff.cli.agents",
    "handoff.cli.mcp",
    "handoff.cli.skills",
    "handoff.cli.memory",
    "handoff.cli.creds",
    "handoff.cli.schedules",
    "handoff.cli.settings",
    "handoff.cli.speech",
    "handoff.cli.workspace",
    "handoff.cli.ops",
)


def _modules() -> list[ModuleType]:
    import importlib

    return [importlib.import_module(name) for name in _GROUP_MODULES]


def build_parser() -> argparse.ArgumentParser:
    """The command tree. Exposed so the docs can render a reference from it."""
    parser = argparse.ArgumentParser(
        prog="handoff",
        description="Describe it. Hand it off. It runs.",
        epilog="Run `handoff <command> --help` for the options of one command.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON instead of tables"
    )
    parser.add_argument(
        "--workspace", default="", metavar="ID", help="Act on this workspace (default: the default one)"
    )
    parser.add_argument(
        "--state-dir", default="", metavar="PATH",
        help="Where runs, rules and settings live (sets HANDOFF_STATE_DIR)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for module in _modules():
        module.register(sub)
    return parser


def _repoint_state(path: str) -> None:
    """Honour ``--state-dir`` whether or not config was already imported.

    A local directory means local storage: the flag also switches DynamoDB
    and AgentCore Memory off, so a scratch run can never touch the live
    table by accident.
    """
    os.environ["HANDOFF_STATE_DIR"] = path
    os.environ["USE_DYNAMODB"] = "false"
    os.environ["USE_AGENTCORE_MEMORY"] = "false"
    if "handoff.config" in sys.modules:
        from handoff import config, store

        config.STATE_DIR = Path(path)
        config.USE_DYNAMODB = False
        config.USE_AGENTCORE_MEMORY = False
        store.reset_store()


def _setup() -> None:
    """What every store-backed command needs before it starts.

    The same first-run bootstrap the web server does, so the terminal and
    the browser see the same workflows, agents and tool servers.
    """
    from handoff import config
    from handoff.platform.bootstrap import bootstrap

    config.configure_observability()
    bootstrap()


def _shutdown() -> None:
    """Close MCP subprocesses a command may have opened, or the exit hangs."""
    if "handoff.mcp.servers" in sys.modules:
        from handoff.mcp import servers

        servers.shutdown()
    if "handoff.platform.mcp_service" in sys.modules:
        from handoff.platform import mcp_service

        for server_id, client in list(mcp_service._CLIENTS.items()):
            try:
                client.stop(None, None, None)
            except Exception:
                pass
            mcp_service._CLIENTS.pop(server_id, None)


def _report(exc: BaseException) -> None:
    if os.environ.get("HANDOFF_DEBUG"):
        raise exc
    message = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
    if _ui.json_mode():
        _ui.print_json({"error": str(message)})
    else:
        _ui.fail(str(message) or exc.__class__.__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        # argparse has already printed usage or help; turn its exit into a code.
        return exc.code if isinstance(exc.code, int) else 1

    if args.state_dir:
        _repoint_state(args.state_dir)
    _ui.bind_stdout(sys.stdout)
    _ui.set_json_mode(args.json)
    _ui.set_workspace(args.workspace)

    handle = getattr(args, "handle", None)
    if handle is None:
        parser.print_help()
        return 2

    # With --json, stdout carries exactly one JSON document. Anything else a
    # run prints on the way — the console notifier, a tool's warning — is
    # moved to stderr so a script can parse what it asked for.
    quiet = contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext()
    try:
        with quiet:
            if getattr(args, "setup", True):
                _setup()
            return int(handle(args) or 0)
    except KeyboardInterrupt:
        _ui.console.print()
        return 130
    except (LookupError, ValueError, FileNotFoundError, NotADirectoryError) as exc:
        _report(exc)
        return 2
    except Exception as exc:
        _report(exc)
        return 1
    finally:
        _shutdown()


__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
