# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The docs inside the app render the same sources as the site."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from handoff.web.server import app

    c = TestClient(app)
    c.post("/welcome/skip")
    return c


def test_docs_index_redirects_to_the_first_guide():
    r = _client().get("/docs", follow_redirects=False)
    assert r.status_code in (302, 303, 307) and r.headers["location"] == "/docs/getting-started"


def test_a_guide_renders_with_nav_and_outline():
    r = _client().get("/docs/the-gate")
    assert r.status_code == 200
    assert 'class="doc-nav"' in r.text and 'class="doc-outline"' in r.text
    assert "<h2" in r.text and "getting-started" in r.text


def test_unknown_guide_is_404():
    assert _client().get("/docs/nope").status_code == 404


def test_sidebar_links_to_the_docs():
    r = _client().get("/activity")
    assert 'href="/docs"' in r.text
