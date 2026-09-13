# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff ask`, `chat` and `build` — the workspace assistant in a terminal.

Same ``ChatService`` and the same session repository as the browser, so a
conversation started here continues on the Chat page, tool cards and all.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from typing import Any

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p_ask = sub.add_parser("ask", help="One question or instruction to the assistant")
    p_ask.add_argument("text", nargs="+", help="What to say")
    p_ask.add_argument("--new", action="store_true", help="Start a fresh chat instead of continuing")
    p_ask.set_defaults(handle=handle_ask)

    p_chat = sub.add_parser("chat", help="Talk to the assistant in a loop (/new, /quit)")
    p_chat.add_argument("--new", action="store_true", help="Start a fresh chat")
    p_chat.set_defaults(handle=handle_chat)

    p_build = sub.add_parser("build", help="Turn one sentence into a workflow config")
    p_build.add_argument("text", nargs="+", help="The chore, in plain words")
    p_build.add_argument("--activate", action="store_true", help="Save it switched on")
    p_build.add_argument("--run", action="store_true", help="Save it and run it now, watching")
    p_build.set_defaults(handle=handle_build)


# --- following a turn -------------------------------------------------------

#: Spans the browser hides from the reply: the fenced config becomes a card,
#: and Nova's <thinking> narration is for the inspector, not the person.
_HIDDEN_SPANS = (("```json", "```"), ("<thinking>", "</thinking>"))
_BLANKS = re.compile(r"\n{3,}")


def visible_text(raw: str, final: bool = False) -> str:
    """The reply as a person should see it while it streams.

    Hidden spans are dropped once their opening marker is complete. Until
    ``final``, the tail that could still turn into a marker is held back,
    so a fence never flashes on screen before it is recognised.
    """
    out: list[str] = []
    pos = 0
    while True:
        starts = [(raw.find(open_, pos), open_, close) for open_, close in _HIDDEN_SPANS]
        starts = [s for s in starts if s[0] >= 0]
        if not starts:
            tail = raw[pos:]
            if not final:
                hold = 0
                for open_, _ in _HIDDEN_SPANS:
                    for n in range(min(len(open_) - 1, len(tail)), 0, -1):
                        if open_.startswith(tail[-n:]):
                            hold = max(hold, n)
                            break
                tail = tail[: len(tail) - hold] if hold else tail
            out.append(tail)
            break
        start, open_, close = min(starts)
        out.append(raw[pos:start])
        end = raw.find(close, start + len(open_))
        if end < 0:
            break
        pos = end + len(close)
    # Collapsing a run of blank lines never changes its first two, so what
    # is already on screen stays a prefix of what comes next.
    return _BLANKS.sub("\n\n", "".join(out))


def stream_turn(
    channel: str,
    start: Callable[[], int] | None,
    turn: int = 1,
    quiet: bool = False,
    emit_json: bool = True,
) -> dict[str, Any]:
    """Subscribe, start the turn, paint it, return the final event.

    With ``start`` the subscription is primed before the turn begins so no
    early event can slip past. Without it (the workbench mints its run id
    inside ``run``) the bus replays the channel's history instead.
    """
    from handoff import events

    primed: dict[str, Any] | None = None
    if start is None:
        feed = events.subscribe(channel, replay=True, keepalive=0.05)
    else:
        feed = events.subscribe(channel, replay=False, keepalive=0.05)
        primed = next(feed)
        turn = start()

    raw = ""  # every delta, verbatim
    emitted = ""  # the visible part already on screen
    line_open = False
    final: dict[str, Any] = {}
    painting = not (_ui.json_mode() or quiet)

    def show(text: str) -> None:
        nonlocal emitted, line_open
        emitted += text
        if text and painting:
            _ui.write(text)
            line_open = not text.endswith("\n")

    def newline() -> None:
        nonlocal line_open
        if line_open and painting:
            _ui.console.print()
        line_open = False

    def paint(event: dict[str, Any]) -> bool:
        nonlocal raw
        kind = event.get("kind")
        if kind == "keepalive" or event.get("turn") not in (None, turn):
            return False
        if kind == "delta":
            raw += str(event.get("text", ""))
            show(visible_text(raw)[len(emitted):])
        elif kind == "tool_end" and painting:
            newline()
            status = event.get("status", "ok")
            mark = "" if status == "ok" else f" [{status}]"
            _ui.dim(f"→ {event.get('name', 'tool')} ({event.get('ms', 0)} ms){mark}")
        elif kind == "asked" and painting:
            newline()
            _ui.warn(str(event.get("text", "")))
        elif kind in ("done", "error"):
            final.update(event)
            return True
        return False

    try:
        if primed is None or not paint(primed):
            for event in feed:
                if paint(event):
                    break
    finally:
        feed.close()

    if _ui.json_mode():
        if emit_json:
            _ui.print_json(final)
        return final
    if quiet:
        return final

    if final.get("kind") == "error":
        newline()
        _ui.fail(str(final.get("text", "the turn failed")))
        return final

    show(visible_text(raw, final=True)[len(emitted):])
    newline()
    text = str(final.get("text", ""))
    if not emitted.strip() and text.strip():
        _ui.console.print(text, soft_wrap=True, markup=False)
    if final.get("config"):
        _ui.console.print(_ui.code_panel(str(final["config"]), title="workflow config"))
    return final


def _chat(fresh: bool):
    from handoff.chat import get_chat_service

    svc = get_chat_service()
    workspace = _ui.workspace()
    chat = None if fresh else svc.latest(workspace)
    return svc, chat or svc.create(workspace)


def send_and_follow(
    text: str, fresh: bool = False, quiet: bool = False, emit_json: bool = True
) -> dict[str, Any]:
    svc, chat = _chat(fresh)
    return stream_turn(
        f"chat:{chat.chat_id}", lambda: svc.send(chat.chat_id, text), quiet=quiet, emit_json=emit_json
    )


# --- commands ---------------------------------------------------------------


def handle_ask(args: argparse.Namespace) -> int:
    final = send_and_follow(" ".join(args.text), fresh=args.new)
    return 1 if final.get("kind") == "error" else 0


def handle_chat(args: argparse.Namespace) -> int:
    from rich.prompt import Prompt

    svc, chat = _chat(args.new)
    _ui.dim(f"chat {chat.chat_id} — /new for a fresh one, /quit to leave")
    while True:
        try:
            text = Prompt.ask("[bold]you[/]", console=_ui.console).strip()
        except (EOFError, KeyboardInterrupt):
            _ui.console.print()
            return 0
        if not text:
            continue
        if text in ("/quit", "/exit", "/q"):
            return 0
        if text == "/new":
            chat = svc.create(_ui.workspace())
            _ui.dim(f"new chat {chat.chat_id}")
            continue
        final = stream_turn(f"chat:{chat.chat_id}", lambda t=text, c=chat: svc.send(c.chat_id, t))
        if final.get("kind") == "error":
            _ui.dim("say it again, or /new")


def _activate(config_json: str) -> dict[str, Any]:
    """Save a config switched on, through the voice tool when it exists."""
    try:
        from handoff.chat.voice_tools import activate_workflow
    except ImportError:
        from handoff.tools.workflow_store import save_workflow

        return save_workflow(config_json, activate=True)
    return activate_workflow(config_json)


def handle_build(args: argparse.Namespace) -> int:
    from handoff.cli import runs
    from handoff.store import get_store
    from handoff.tools.workflow_store import save_workflow

    sentence = " ".join(args.text).strip()
    final = send_and_follow(f"{sentence.rstrip('.')}. Show the config.", fresh=True, emit_json=False)
    summary: dict[str, Any] = {"turn": final, "saved": False, "workflow_id": "", "config": None}
    if final.get("kind") == "error":
        if _ui.json_mode():
            _ui.print_json(summary)
        return 1
    config_json = final.get("config") or ""
    if not config_json:
        if _ui.json_mode():
            _ui.print_json(summary)
        else:
            _ui.warn("the assistant did not produce a config — try `handoff chat` and refine it")
        return 1
    summary["config"] = json.loads(config_json)

    workflow_id = ""
    if args.activate or args.run:
        result = _activate(config_json) if args.activate else save_workflow(config_json, activate=False)
        if result.get("error") or result.get("errors") or not result.get("workflow_id"):
            problems = result.get("error") or "; ".join(result.get("errors") or []) or "not saved"
            summary["errors"] = problems
            if _ui.json_mode():
                _ui.print_json(summary)
            else:
                _ui.fail(f"couldn't save it: {problems}")
            return 1
        workflow_id = str(result["workflow_id"])
        summary.update(saved=True, workflow_id=workflow_id, status="active" if args.activate else "draft")
        if not _ui.json_mode():
            _ui.ok(f"saved {workflow_id} ({summary['status']})")

    code = 0
    if args.run:
        workflow = get_store().get_workflow(workflow_id)
        if workflow is None:
            raise KeyError(f"No workflow with id '{workflow_id}'")
        outcome = runs.start_and_watch(workflow, "manual")
        summary["outcome"] = dict(outcome)
        code = 1 if outcome.get("status") == "failed" else 0
        if not _ui.json_mode():
            runs.print_outcome(outcome)

    if _ui.json_mode():
        _ui.print_json(summary)
    return code
