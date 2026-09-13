# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`python site/build.py --out <dir>` produces the whole static site."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def dist(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    r = subprocess.run(
        [sys.executable, str(ROOT / "site" / "build.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr
    assert re.search(r"\b\d+ files\b", r.stdout), r.stdout
    return out


def test_build_produces_index_docs_and_assets(dist):
    assert (dist / "index.html").exists()
    assert (dist / "docs" / "getting-started.html").exists()
    assert (dist / "assets" / "site.css").exists() and (dist / "assets" / "orb.js").exists()
    assert "Describe it. Hand it off. It runs." in (dist / "index.html").read_text()


def test_build_renders_every_doc_and_copies_screens(dist):
    sys.path.insert(0, str(ROOT / "src"))
    from handoff import docs

    for slug in docs.ORDER:
        assert (dist / "docs" / f"{slug}.html").exists(), slug
    screens = sorted(p.name for p in (ROOT / "docs" / "screens").glob("*.png"))
    assert screens
    for name in screens:
        assert (dist / "screens" / name).exists(), name


def test_build_writes_headers_and_redirects(dist):
    headers = (dist / "_headers").read_text()
    assert "/assets/*" in headers and "Cache-Control" in headers
    redirects = (dist / "_redirects").read_text()
    assert "/docs /docs/getting-started 302" in redirects


def test_doc_pages_share_nav_outline_and_stylesheet(dist):
    page = (dist / "docs" / "the-gate.html").read_text()
    assert "assets/site.css" in page and "assets/site.js" in page
    assert 'class="doc-outline"' in page and 'class="doc-nav"' in page
    assert 'href="/docs/getting-started"' in page and 'href="/docs/architecture"' in page
    assert 'aria-current="page"' in page
    assert "<h2" in page and "{{" not in page


def test_orb_contract_is_available_on_the_landing_page(dist):
    index = (dist / "index.html").read_text()
    orb = (dist / "assets" / "orb.js").read_text()
    assert "assets/orb.js" in index and 'id="orb"' in index
    assert "HandoffOrb" in orb and "mount" in orb and "setState" in orb and "setLevel" in orb
    assert 'data-video=""' in index


def test_no_placeholders_and_a_gutter_for_phones(dist):
    for path in [dist / "index.html", *sorted((dist / "docs").glob("*.html"))]:
        text = path.read_text()
        assert "lorem" not in text.lower(), path.name
        assert not re.search(r"\{\{\s*\w+\s*\}\}", text), path.name  # no unfilled placeholder
        assert 'name="viewport"' in text, path.name
    css = (dist / "assets" / "site.css").read_text()
    assert "prefers-reduced-motion" in css
    assert "prefers-color-scheme: dark" in css and '[data-theme="dark"]' in css
    assert "oklch(0.965 0.008 85)" in css and "oklch(0.16 0.006 85)" in css
    assert "oklch(0.9 0.035 70)" in css
