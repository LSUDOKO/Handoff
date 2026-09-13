# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The theme is data: fonts, palette and brand live in two files."""

from __future__ import annotations

from pathlib import Path

STATIC = Path("src/handoff/web/static")
TPL = Path("src/handoff/web/templates")


def test_tokens_define_kelbro_palette_and_fonts():
    css = (STATIC / "tokens.css").read_text()
    assert "Instrument Sans" in css and "JetBrains Mono" in css and "Comfortaa" in css
    assert "--accent:" in css and "--accent-ink:" in css and "--wash:" in css
    assert "oklch(0.965 0.008 85)" in css  # light ground
    assert "oklch(0.16 0.006 85)" in css  # dark ground
    assert "oklch(0.9 0.035 70)" in css  # champagne accent
    assert "--ease-out-expo:" in css and "--ease-spring:" in css


def test_base_loads_google_fonts_and_wordmark():
    html = (TPL / "base.html").read_text()
    assert "fonts.googleapis.com/css2?family=Instrument+Sans" in html
    assert "Comfortaa" in html
    assert 'class="wordmark"' in html


def test_components_use_the_accent_and_glass_surfaces():
    css = (STATIC / "ui.css").read_text()
    assert "var(--accent-ink)" in css and "backdrop-filter" in css
    assert "startViewTransition" in (STATIC / "app.js").read_text()
