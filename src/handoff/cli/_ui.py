# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""One console for every subcommand, and the ``--json`` switch they all obey.

Human output goes through ``rich`` so tables line up and long ids don't
wrap into soup. JSON output deliberately bypasses it: a console wraps at
its width, and a wrapped JSON document is not JSON any more.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console(highlight=False, emoji=False)
err_console = Console(stderr=True, highlight=False, emoji=False)

_state: dict[str, Any] = {"json": False, "workspace": "", "stdout": None}

#: Width to lay tables out at when output is piped: wide enough that ids
#: never fold, which is what a grep on the other end needs.
PIPE_WIDTH = 160


# --- global switches --------------------------------------------------------


def set_json_mode(enabled: bool) -> None:
    _state["json"] = bool(enabled)


def bind_stdout(stream: Any) -> None:
    """Remember where JSON goes, before ``--json`` redirects everything else."""
    _state["stdout"] = stream
    if not getattr(stream, "isatty", lambda: False)():
        console.width = PIPE_WIDTH
    if not sys.stderr.isatty():
        err_console.width = PIPE_WIDTH


def out(text: str) -> None:
    """Write to the real stdout — the channel scripts read."""
    stream = _state["stdout"] or sys.stdout
    stream.write(text if text.endswith("\n") else text + "\n")
    stream.flush()


def json_mode() -> bool:
    return bool(_state["json"])


def set_workspace(workspace_id: str) -> None:
    _state["workspace"] = workspace_id or ""


def workspace() -> str:
    """The workspace every scoped command acts on.

    ``--workspace`` wins; otherwise the store's default. Resolved lazily so
    commands that never touch the store (``version``, ``doctor``) don't
    create one as a side effect.
    """
    from handoff.store import get_store

    store = get_store()
    chosen = _state["workspace"]
    if chosen:
        if store.get_workspace(chosen) is None:
            raise KeyError(f"No workspace with id '{chosen}'")
        return chosen
    return store.default_workspace().workspace_id


# --- output -----------------------------------------------------------------


def dump(value: Any) -> Any:
    """Anything the store hands back, as plain JSON-able data."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: dump(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [dump(v) for v in value]
    return value


def print_json(data: Any) -> None:
    out(json.dumps(dump(data), indent=2, default=str))


def emit(data: Any, table: Callable[[], Table] | None = None) -> None:
    """JSON in ``--json`` mode; otherwise the table (or a plain rendering)."""
    if json_mode():
        print_json(data)
        return
    if table is not None:
        console.print(table())
        return
    data = dump(data)
    if isinstance(data, dict):
        console.print(kv_table("", data))
    elif isinstance(data, list):
        for item in data:
            console.print(escape(str(item)))
    else:
        console.print(escape(str(data)))


def table(title: str, columns: list[str], rows: list[list[Any]]) -> Table:
    grid = Table(title=title or None, box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    for index, column in enumerate(columns):
        # The first column is an id or a name; it must survive intact.
        grid.add_column(column, overflow="fold", no_wrap=index == 0)
    for row in rows:
        grid.add_row(*[escape(cell if isinstance(cell, str) else str(cell)) for cell in row])
    return grid


def kv_table(title: str, mapping: dict[str, Any]) -> Table:
    """Two columns, no header — how a single record reads best."""
    grid = Table(title=title or None, box=None, show_header=False, pad_edge=False)
    grid.add_column(style="dim", no_wrap=True)
    grid.add_column(overflow="fold")
    for key, value in mapping.items():
        if isinstance(value, dict | list):
            value = json.dumps(value, default=str)
        grid.add_row(escape(str(key)), escape("" if value is None else str(value)))
    return grid


def code_panel(text: str, title: str = "", lexer: str = "json") -> Panel:
    return Panel(Syntax(text, lexer, word_wrap=True), title=title or None, border_style="dim")


def ok(message: str) -> None:
    console.print(f"[green]✓[/] {escape(message)}")


def warn(message: str) -> None:
    console.print(f"[yellow]![/] {escape(message)}")


def fail(message: str) -> None:
    err_console.print(f"[red]✗[/] {escape(message)}")


def dim(message: str) -> None:
    console.print(f"[dim]{escape(message)}[/]")


def write(text: str) -> None:
    """A fragment of streamed text: no newline, no wrapping, no markup."""
    console.print(text, end="", soft_wrap=True, markup=False, highlight=False)


def stamp(event: dict[str, Any]) -> str:
    """``HH:MM:SS`` for an events-bus event, in local time."""
    t = event.get("t")
    when = datetime.fromtimestamp(float(t)) if t else datetime.now(UTC).astimezone()
    return when.strftime("%H:%M:%S")


def when(value: datetime | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def yes_no(flag: bool) -> str:
    return "yes" if flag else "no"
