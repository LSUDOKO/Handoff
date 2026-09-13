# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The user-facing docs: eight markdown sources, one renderer, a generated CLI reference."""

from __future__ import annotations

import argparse
import re


def test_index_and_render():
    from handoff import docs

    slugs = [d["slug"] for d in docs.index()]
    assert slugs == docs.ORDER
    for entry in docs.index():
        assert entry["title"] and entry["summary"], entry["slug"]

    page = docs.render("the-gate")
    assert page["title"] and "<h2" in page["html"] and page["outline"]
    assert page["slug"] == "the-gate" and page["raw"].startswith("# ")


def test_every_doc_renders_with_an_outline_of_h2_and_h3():
    from handoff import docs

    for slug in docs.ORDER:
        page = docs.render(slug)
        assert page["outline"], slug
        assert {item["depth"] for item in page["outline"]} <= {2, 3}, slug
        for item in page["outline"]:
            assert f'id="{item["id"]}"' in page["html"], (slug, item)


def test_every_doc_is_real_prose():
    """60–150 lines each, starting with a title and a summary paragraph."""
    from handoff import docs

    for slug in docs.ORDER:
        raw = (docs.DOCS_DIR / f"{slug}.md").read_text()
        lines = raw.splitlines()
        assert 60 <= len(lines) <= 150, (slug, len(lines))
        assert lines[0].startswith("# ")
        assert "lorem" not in raw.lower() and "TODO" not in raw


def test_unknown_slug_raises():
    import pytest

    from handoff import docs

    with pytest.raises(KeyError):
        docs.render("nope")


def test_cli_doc_includes_every_subcommand():
    """The reference is generated from the parser, so it lists whatever it has."""
    from handoff import docs
    from handoff.cli import build_parser

    html = docs.render("cli")["html"]
    expected = [" ".join(path) for path, _, _ in docs.walk_parser(build_parser())]
    assert expected, "the parser has no subcommands?"
    for name in ("workflows", "run", "decide"):
        assert name in expected
    for name in expected:
        assert f"handoff {name}" in html, name
    assert "<h2" in html and 'id="reference"' in html


def test_walk_parser_recurses_into_nested_subparsers():
    from handoff import docs

    parser = argparse.ArgumentParser(prog="x")
    sub = parser.add_subparsers(dest="command")
    a = sub.add_parser("alpha", help="First group")
    a_sub = a.add_subparsers(dest="alpha_command")
    a_sub.add_parser("one", help="Nested one").add_argument("--flag", help="A flag")
    deep = a_sub.add_parser("two", help="Nested two")
    deep_sub = deep.add_subparsers(dest="deep_command")
    deep_sub.add_parser("three", help="Third level")
    sub.add_parser("beta", help="Second group").add_argument("thing", help="A positional")

    paths = [" ".join(path) for path, _, _ in docs.walk_parser(parser)]
    assert paths == ["alpha", "alpha one", "alpha two", "alpha two three", "beta"]

    reference = docs.cli_reference(parser, prog="x")
    assert "### x alpha two three" in reference
    assert "Third level" in reference and "--flag" in reference and "thing" in reference
    assert not re.search(r"\{[a-z_,]+\}", reference), "argparse choice braces leaked into the doc"
