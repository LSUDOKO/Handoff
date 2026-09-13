# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff memory` — what it has learned from you, and what you've told it.

Rules are what the Learning Agent distilled from your decisions; entries are
notes you (or a run) put in a workspace's memory store by hand.
"""

from __future__ import annotations

import argparse

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("memory", help="Learned rules and remembered notes")
    p.set_defaults(handle=handle)
    m = p.add_subparsers(dest="memory_command", metavar="<action>")

    m.add_parser("rules", help="Rules learned from your decisions (the default)")

    p_entries = m.add_parser("entries", help="Notes in the workspace's memory stores")
    p_entries.add_argument("--store", default="", help="Only this store (name or id)")

    p_add = m.add_parser("add", help="Remember a note in the workspace's long-term store")
    p_add.add_argument("text", nargs="+")
    p_add.add_argument("--key", default="", help="A short label (default: the first words)")
    p_add.add_argument("--store", default="", help="Store name or id (default: long-term)")

    p_forget = m.add_parser("forget", help="Delete a rule or a note by id")
    p_forget.add_argument("entry_id", help="A pref_… rule id or a ment_… entry id")

    # The old `handoff rules` keeps working.
    p_rules = sub.add_parser("rules", help="List the rules it has learned from you")
    p_rules.set_defaults(handle=handle_rules)


def handle_rules(args: argparse.Namespace) -> int:
    from handoff.memory.store import list_preferences

    prefs = list_preferences()
    _ui.emit(
        prefs,
        lambda: _ui.table(
            f"{len(prefs)} learned rules",
            ["id", "action", "rule", "matches", "confidence", "applied"],
            [
                [
                    p.preference_id, p.action, p.pattern,
                    p.match_sender or ", ".join(p.match_keywords),
                    f"{p.confidence:.0%}", p.times_applied,
                ]
                for p in prefs
            ],
        ),
    )
    return 0


def _stores():
    from handoff.platform.bootstrap import seed_memory_stores
    from handoff.store import get_store

    workspace = _ui.workspace()
    stores = get_store().list_memory_stores(workspace)
    if not stores:
        seed_memory_stores(workspace)
        stores = get_store().list_memory_stores(workspace)
    return [s for s in stores if s.workspace_id == workspace] or stores


def _store_for(ref: str):
    stores = _stores()
    if ref:
        for store in stores:
            if ref in (store.store_id, store.name):
                return store
        raise KeyError(f"No memory store named '{ref}'")
    for store in stores:
        if store.kind.value == "long_term":
            return store
    if not stores:
        raise KeyError("This workspace has no memory stores")
    return stores[0]


def handle(args: argparse.Namespace) -> int:
    from handoff.platform.models import MemoryEntry
    from handoff.store import get_store

    store = get_store()
    action = args.memory_command or "rules"

    if action == "rules":
        return handle_rules(args)

    if action == "entries":
        workspace = _ui.workspace()
        names = {s.store_id: s.name for s in store.list_memory_stores(None)}
        only = _store_for(args.store).store_id if args.store else ""
        entries = [
            e for e in store.list_memory_entries(only)
            if not e.workspace_id or e.workspace_id == workspace
        ]
        rows = [{**e.model_dump(mode="json"), "store": names.get(e.store_id, e.store_id)} for e in entries]
        _ui.emit(
            rows,
            lambda: _ui.table(
                f"{len(rows)} entries",
                ["id", "store", "key", "content", "source", "when"],
                [[r["entry_id"], r["store"], r["key"], r["content"], r["source"], _ui.when(r["created_at"])] for r in rows],
            ),
        )
        return 0

    if action == "add":
        text = " ".join(args.text).strip()
        if not text:
            raise ValueError("nothing to remember")
        target = _store_for(args.store)
        entry = MemoryEntry(
            store_id=target.store_id,
            workspace_id=_ui.workspace(),
            key=args.key.strip() or " ".join(text.split()[:6]),
            content=text,
            source="cli",
        )
        store.memory_entries.put(entry, "entry_id")
        if _ui.json_mode():
            _ui.print_json(entry)
        else:
            _ui.ok(f"remembered in {target.name} as {entry.entry_id}")
        return 0

    if action == "forget":
        if store.preferences.get("preference_id", args.entry_id) is not None:
            store.preferences.delete("preference_id", args.entry_id)
            kind = "rule"
        elif store.memory_entries.get("entry_id", args.entry_id) is not None:
            store.memory_entries.delete("entry_id", args.entry_id)
            kind = "entry"
        else:
            raise KeyError(f"No rule or entry with id '{args.entry_id}'")
        if _ui.json_mode():
            _ui.print_json({"forgot": args.entry_id, "kind": kind})
        else:
            _ui.ok(f"forgot {kind} {args.entry_id}")
        return 0

    return 2
