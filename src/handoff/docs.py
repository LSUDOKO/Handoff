# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The user-facing docs, rendered from ``docs/site/*.md``.

One source, two readers: the static site (``site/build.py``) and the ``/docs``
pages inside the app both call :func:`render`. Each markdown file starts with
a ``# Title`` line and a one-paragraph summary; the order pages appear in is
:data:`ORDER`, not the filesystem.

The CLI page is special: its prose is written by hand, but the reference at
the end is generated from the live argparse tree, so the doc cannot drift
from the commands that actually exist.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ORDER = [
    "getting-started",
    "talk",
    "workflows",
    "the-gate",
    "integrations",
    "cli",
    "deploy",
    "architecture",
]

_EXTENSIONS = ["fenced_code", "tables", "toc", "attr_list"]


def _locate_docs() -> Path:
    """``<repo>/docs/site`` from a source checkout, else the same path under cwd."""
    from_package = Path(__file__).resolve().parents[2] / "docs" / "site"
    if from_package.is_dir():
        return from_package
    from_cwd = Path.cwd() / "docs" / "site"
    return from_cwd if from_cwd.is_dir() else from_package


DOCS_DIR: Path = _locate_docs()

_INLINE = re.compile(r"[`*_]|\[([^\]]+)\]\([^)]*\)")


def _plain(text: str) -> str:
    """Strip inline markdown from a one-line summary."""
    return _INLINE.sub(lambda m: m.group(1) or "", text).strip()


def _read(slug: str) -> str:
    if slug not in ORDER:
        raise KeyError(slug)
    path = DOCS_DIR / f"{slug}.md"
    if not path.exists():
        raise KeyError(slug)
    return path.read_text(encoding="utf-8")


def _title_and_summary(raw: str) -> tuple[str, str]:
    lines = raw.splitlines()
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            body_start = i + 1
            break
    summary: list[str] = []
    for line in lines[body_start:]:
        if not line.strip():
            if summary:
                break
            continue
        if line.startswith("#"):
            break
        summary.append(line.strip())
    return title, _plain(" ".join(summary))


def index() -> list[dict[str, Any]]:
    """Every page, in reading order: ``{"slug", "title", "summary"}``."""
    out: list[dict[str, Any]] = []
    for slug in ORDER:
        try:
            raw = _read(slug)
        except KeyError:
            continue
        title, summary = _title_and_summary(raw)
        out.append({"slug": slug, "title": title or slug, "summary": summary})
    return out


def _flatten(tokens: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    for token in tokens:
        if token["level"] in (2, 3):
            out.append({"id": token["id"], "text": token["name"], "depth": token["level"]})
        _flatten(token.get("children", []), out)


def render(slug: str) -> dict[str, Any]:
    """Render one page: ``{"slug", "title", "html", "outline", "raw"}``.

    ``outline`` lists the h2 and h3 headings with the ids the HTML carries,
    so a page can draw a table of contents that links into the content.
    """
    import markdown

    raw = _read(slug)
    if slug == "cli":
        raw = raw.rstrip() + "\n\n" + cli_reference()
    md = markdown.Markdown(extensions=_EXTENSIONS)
    html = md.convert(raw)
    outline: list[dict[str, Any]] = []
    _flatten(getattr(md, "toc_tokens", []), outline)
    title, _ = _title_and_summary(raw)
    return {"slug": slug, "title": title or slug, "html": html, "outline": outline, "raw": raw}


# --- the generated CLI reference -------------------------------------------


def _subcommands(parser: argparse.ArgumentParser) -> Iterator[tuple[str, argparse.ArgumentParser, str]]:
    """Each subcommand of ``parser`` once, with its help text (aliases collapse)."""
    for action in parser._actions:  # noqa: SLF001 - argparse has no public walk
        if not isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            continue
        helps = {choice.dest: choice.help or "" for choice in action._choices_actions}  # noqa: SLF001
        seen: set[int] = set()
        for name, sub in action.choices.items():
            if id(sub) in seen:
                continue
            seen.add(id(sub))
            yield name, sub, helps.get(name, "")


def walk_parser(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], argparse.ArgumentParser, str]]:
    """Depth-first over every command at every level: ``(path, parser, help)``."""
    for name, sub, help_text in _subcommands(parser):
        full = (*path, name)
        yield full, sub, help_text
        yield from walk_parser(sub, full)


def _argument_rows(sub: argparse.ArgumentParser) -> list[str]:
    rows: list[str] = []
    for action in sub._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction | argparse._HelpAction):  # noqa: SLF001
            continue
        if action.help == argparse.SUPPRESS:
            continue
        if action.option_strings:
            name = ", ".join(action.option_strings)
            if action.nargs != 0 and action.metavar is not False:
                name += f" <{(action.metavar or action.dest).lower()}>"
        else:
            name = f"<{action.metavar or action.dest}>"
            if action.nargs in ("?", "*"):
                name = f"[{name}]"
            elif action.nargs == "+":
                name += "…"
        parts = [str(action.help or "").strip()]
        if action.choices and not isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            parts.append("one of " + ", ".join(f"`{c}`" for c in action.choices))
        if (
            action.default not in (None, argparse.SUPPRESS, "", False, [])
            and action.nargs != 0
        ):
            parts.append(f"default `{action.default}`")
        rows.append(f"- `{name}` — {'; '.join(p for p in parts if p)}".rstrip(" —"))
    return rows


_CHOICES = re.compile(r"\{[^}]*\}")


def _usage(sub: argparse.ArgumentParser, prog: str, path: tuple[str, ...]) -> str:
    """One usage line with ``prog`` and the command path, choice braces collapsed."""
    usage = sub.format_usage().strip()
    usage = re.sub(r"^usage:\s*", "", usage)
    usage = re.sub(r"\s+", " ", usage)
    usage = _CHOICES.sub("<command>", usage)
    head = " ".join((prog, *path))
    # argparse spells the prog of a nested parser as "handoff workspace"; make
    # sure the line starts with exactly the path we are documenting.
    tail = usage.split(" ", len(path) + 1)[len(path) + 1 :]
    return f"{head} {tail[0]}".strip() if tail else head


def cli_reference(parser: argparse.ArgumentParser | None = None, prog: str = "handoff") -> str:
    """Markdown for every command in the parser, one ``###`` per command."""
    if parser is None:
        from handoff.cli import build_parser

        parser = build_parser()

    lines = [
        "## Reference",
        "",
        "Generated from the installed command tree, so it lists exactly the commands "
        f"this version of `{prog}` has.",
        "",
    ]
    if parser.description:
        lines += [f"`{prog}` — {parser.description}", ""]
    top = _argument_rows(parser)
    if top:
        lines += ["Global options:", "", *top, ""]

    for path, sub, help_text in walk_parser(parser):
        lines.append(f"### {prog} {' '.join(path)}")
        lines.append("")
        if help_text:
            lines += [help_text.rstrip(".") + ".", ""]
        if sub.description and sub.description != help_text:
            lines += [sub.description.strip(), ""]
        lines += ["```", _usage(sub, prog, path), "```", ""]
        children = [name for name, _, _ in _subcommands(sub)]
        if children:
            lines += ["Subcommands: " + ", ".join(f"`{c}`" for c in children), ""]
        rows = _argument_rows(sub)
        if rows:
            lines += rows
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
