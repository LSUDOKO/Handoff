# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff workspace` — workspaces as files: list, export, import, remove, switch."""

from __future__ import annotations

import argparse
from pathlib import Path

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("workspace", help="Export or import a workspace.yml / bundle, switch the default")
    p.set_defaults(handle=handle)
    w = p.add_subparsers(dest="ws_command", metavar="<action>")

    w.add_parser("list", help="List workspaces (the default)")

    p_export = w.add_parser("export", help="Write workspace.yml (or a .zip bundle) to a path")
    p_export.add_argument("path", help="Where to write; .zip for a bundle, anything else for YAML")
    p_export.add_argument(
        "--workspace", dest="export_workspace", default="",
        help="Workspace id (default: the selected or default workspace)",
    )

    p_import = w.add_parser("import", help="Create a workspace from a workspace.yml or bundle")
    p_import.add_argument("path")

    p_remove = w.add_parser("remove", help="Delete a workspace and everything scoped to it")
    p_remove.add_argument("workspace_id")

    p_switch = w.add_parser("switch", help="Make a workspace the default one every command acts on")
    p_switch.add_argument("workspace_id")


def handle(args: argparse.Namespace) -> int:
    from handoff.platform import workspace_yaml
    from handoff.store import get_store

    store = get_store()
    action = args.ws_command or "list"

    if action == "list":
        spaces = store.list_workspaces()
        _ui.emit(
            spaces,
            lambda: _ui.table(
                "Workspaces",
                ["id", "name", "default", "color", "description"],
                [[w.workspace_id, w.name, _ui.yes_no(w.is_default), w.color, w.description] for w in spaces],
            ),
        )
        return 0

    if action == "export":
        workspace_id = args.export_workspace or _ui.workspace()
        if store.get_workspace(workspace_id) is None:
            raise KeyError(f"No workspace with id '{workspace_id}'")
        target = Path(args.path)
        if target.suffix == ".zip":
            target.write_bytes(workspace_yaml.bundle(workspace_id))
        else:
            target.write_text(workspace_yaml.to_yaml(workspace_id))
        if _ui.json_mode():
            _ui.print_json({"wrote": str(target), "workspace_id": workspace_id})
        else:
            _ui.ok(f"wrote {target}")
        return 0

    if action == "import":
        source = Path(args.path)
        if not source.is_file():
            raise FileNotFoundError(f"No such file: {args.path}")
        result = workspace_yaml.import_document(source.read_bytes(), source.name)
        if _ui.json_mode():
            _ui.print_json(result)
        else:
            _ui.ok(
                f"imported '{result['name']}' as {result['workspace_id']}: "
                f"{result['workflows']} workflows, {result['skills']} skills, {result['agents']} agents"
            )
        return 0

    if action == "remove":
        result = workspace_yaml.remove(args.workspace_id)
        if _ui.json_mode():
            _ui.print_json({"removed": args.workspace_id, **result})
        else:
            _ui.ok(f"removed '{result['name']}' and {result['removed']} things scoped to it")
        return 0

    if action == "switch":
        from handoff.platform import credentials as creds

        chosen = store.get_workspace(args.workspace_id)
        if chosen is None:
            raise KeyError(f"No workspace with id '{args.workspace_id}'")
        for space in store.workspaces.all():
            wanted = space.workspace_id == chosen.workspace_id
            if space.is_default != wanted:
                space.is_default = wanted
                store.workspaces.put(space, "workspace_id")
        creds.apply_credentials(chosen.workspace_id)
        if _ui.json_mode():
            _ui.print_json({"default": chosen.workspace_id, "name": chosen.name})
        else:
            _ui.ok(f"{chosen.name} is now the default workspace")
        return 0

    return 2
