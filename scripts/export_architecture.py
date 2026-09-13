# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Render docs/architecture.excalidraw to SVG and PNG with Excalidraw's own
exporter, loaded in a headless browser through Playwright."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "architecture.excalidraw"
PAGE = """<!doctype html><html><body><script type="module">
  window.__status = "loading";
  try {
    const mod = await import("https://esm.sh/@excalidraw/excalidraw@0.18.0?deps=react@19.1.0,react-dom@19.1.0");
    window.__exportToSvg = mod.exportToSvg; window.__status = "ready";
  } catch (e) { window.__status = "error: " + e.message; }
</script></body></html>"""


def main() -> int:
    doc = json.loads(SRC.read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1800, "height": 1000})
        page.set_content(PAGE, wait_until="networkidle")
        for _ in range(60):
            status = page.evaluate("window.__status")
            if status != "loading":
                break
            page.wait_for_timeout(1000)
        if status != "ready":
            print(status)
            return 1
        svg = page.evaluate(
            """async (doc) => { const svg = await window.__exportToSvg({ elements: doc.elements,
                 appState: { ...doc.appState, exportBackground: true, exportPadding: 32 }, files: doc.files });
                 return svg.outerHTML; }""",
            doc,
        )
        (ROOT / "docs" / "architecture.svg").write_text(svg)
        shot = browser.new_page(viewport={"width": 1800, "height": 1000}, device_scale_factor=2)
        shot.set_content(f"<body style='margin:0;background:#fff'>{svg}</body>", wait_until="networkidle")
        shot.wait_for_timeout(1500)
        shot.locator("svg").first.screenshot(path=str(ROOT / "docs" / "architecture.png"))
        browser.close()
    print("wrote docs/architecture.svg and docs/architecture.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
