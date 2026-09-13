# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff skills` — the standing instructions agents can be given."""

from __future__ import annotations

import argparse
from pathlib import Path

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("skills", help="List, read, toggle or import skills")
    p.set_defaults(handle=handle)
    s = p.add_subparsers(dest="skills_command", metavar="<action>")

    s.add_parser("list", help="Every skill in the workspace (the default)")

    p_show = s.add_parser("show", help="A skill's description and body")
    p_show.add_argument("skill", help="Skill id or name")

    p_enable = s.add_parser("enable", help="Let agents load this skill")
    p_enable.add_argument("skill", help="Skill id or name")

    p_disable = s.add_parser("disable", help="Keep this skill out of every prompt")
    p_disable.add_argument("skill", help="Skill id or name")

    p_import = s.add_parser("import", help="Import Markdown skill files, or a zip of them")
    p_import.add_argument("files", nargs="+", help="SKILL.md files or .zip bundles")


def find(ref: str):
    from handoff.store import get_store

    skills = get_store().list_skills(_ui.workspace())
    for skill in skills:
        if ref in (skill.skill_id, skill.name, skill.qualified):
            return skill
    raise KeyError(f"No skill with id or name '{ref}'")


def _set_enabled(ref: str, enabled: bool) -> int:
    from handoff.store import get_store

    skill = find(ref)
    skill.enabled = enabled
    get_store().skills.put(skill, "skill_id")
    _ui.emit({"skill_id": skill.skill_id, "name": skill.name, "enabled": enabled})
    return 0


def handle(args: argparse.Namespace) -> int:
    from handoff.platform import skills as skills_mod
    from handoff.store import get_store

    action = args.skills_command or "list"

    if action == "list":
        skills = get_store().list_skills(_ui.workspace())
        _ui.emit(
            skills,
            lambda: _ui.table(
                "Skills",
                ["id", "name", "namespace", "on", "description"],
                [[s.skill_id, s.name, s.namespace, _ui.yes_no(s.enabled), s.description] for s in skills],
            ),
        )
        return 0

    if action == "show":
        skill = find(args.skill)
        if _ui.json_mode():
            _ui.print_json(skill)
            return 0
        _ui.console.print(
            _ui.kv_table(
                skill.qualified,
                {
                    "id": skill.skill_id,
                    "description": skill.description,
                    "enabled": _ui.yes_no(skill.enabled),
                    "built-in": _ui.yes_no(skill.builtin),
                    "versions kept": len(skill.history),
                    "updated": _ui.when(skill.updated_at),
                },
            )
        )
        _ui.console.print(_ui.code_panel(skill.body, title="body", lexer="markdown"))
        return 0

    if action == "enable":
        return _set_enabled(args.skill, True)

    if action == "disable":
        return _set_enabled(args.skill, False)

    if action == "import":
        files = []
        for name in args.files:
            path = Path(name)
            if not path.is_file():
                raise FileNotFoundError(f"No such file: {name}")
            files.append((path.name if path.name.upper() != "SKILL.MD" else f"{path.parent.name}/SKILL.md", path.read_bytes()))
        saved = skills_mod.import_files(files, workspace_id=_ui.workspace())
        _ui.emit(
            saved,
            lambda: _ui.table(
                f"imported {len(saved)}",
                ["id", "name", "description"],
                [[s.skill_id, s.name, s.description] for s in saved],
            ),
        )
        return 0 if saved else 1

    return 2
