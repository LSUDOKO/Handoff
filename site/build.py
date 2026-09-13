#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Build the static site: the landing page, the docs, assets and screenshots.

    python site/build.py                 # -> site/dist
    python site/build.py --out <dir>

Standard library plus ``handoff.docs``. The landing page is copied as it is;
each ``docs/site/*.md`` is rendered through ``handoff.docs.render`` into
``site/templates/doc.html`` by plain string replacement of ``{{title}}``,
``{{description}}``, ``{{content}}``, ``{{outline}}``, ``{{nav}}``,
``{{pager}}``, ``{{sitenav}}`` and ``{{footer}}``. The site nav and footer are
lifted from ``index.html`` so every page shares one copy of each.

The orb comes from the app (``src/handoff/web/static/orb.js``) when it exists,
otherwise from ``site/assets/orb-fallback.js``, so the hero always has one.
Asset links are stamped with a content hash so ``_headers`` can cache them
for a year. Exit status 1 if any doc fails to render.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "src"))

APP_ORB = ROOT / "src" / "handoff" / "web" / "static" / "orb.js"
FALLBACK_ORB = SITE / "assets" / "orb-fallback.js"
SCREENS = ROOT / "docs" / "screens"

HEADERS = """\
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/screens/*
  Cache-Control: public, max-age=604800
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: DENY
"""

REDIRECTS = """\
/docs /docs/getting-started 302
/docs/ /docs/getting-started 302
"""


def _between(text: str, start: str, end: str) -> str:
    """The block of ``text`` between two marker comments, markers excluded."""
    i = text.index(start) + len(start)
    j = text.index(end, i)
    return text[i:j].strip("\n")


def _activate(fragment: str, tab: str) -> str:
    """Mark one ``data-tab`` link as the current page."""
    return fragment.replace(f'data-tab="{tab}"', f'data-tab="{tab}" aria-current="page"', 1)


def _stamp(page: str, stamps: dict[str, str]) -> str:
    """Append ``?v=<hash>`` to every ``/assets/<name>`` reference."""
    for name, digest in stamps.items():
        page = page.replace(f'/assets/{name}"', f'/assets/{name}?v={digest}"')
    return page


def _doc_nav(pages: list[dict], current: str) -> str:
    rows = []
    for entry in pages:
        aria = ' aria-current="page"' if entry["slug"] == current else ""
        rows.append(
            f'      <li><a href="/docs/{entry["slug"]}"{aria}>{html.escape(entry["title"])}</a></li>'
        )
    return "\n".join(rows)


def _outline(items: list[dict]) -> str:
    return "\n".join(
        f'      <li class="depth-{item["depth"]}"><a href="#{item["id"]}">{html.escape(item["text"])}</a></li>'
        for item in items
    )


def _pager(pages: list[dict], current: str) -> str:
    slugs = [p["slug"] for p in pages]
    i = slugs.index(current)
    out = []
    if i > 0:
        prev = pages[i - 1]
        out.append(
            f'      <a class="prev" href="/docs/{prev["slug"]}"><span class="label">Previous</span>'
            f'<span class="name">{html.escape(prev["title"])}</span></a>'
        )
    if i < len(pages) - 1:
        nxt = pages[i + 1]
        out.append(
            f'      <a class="next" href="/docs/{nxt["slug"]}"><span class="label">Next</span>'
            f'<span class="name">{html.escape(nxt["title"])}</span></a>'
        )
    return "\n".join(out)


def build(out: Path) -> tuple[int, int, list[str]]:
    """Write the site into ``out``. Returns (files written, failures, notes)."""
    from handoff import docs

    notes: list[str] = []
    count = 0

    for sub in ("assets", "docs", "screens"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir(parents=True, exist_ok=True)

    # -- assets ------------------------------------------------------------
    for src in sorted((SITE / "assets").iterdir()):
        if src.name.startswith(".") or src == FALLBACK_ORB or not src.is_file():
            continue
        shutil.copy2(src, out / "assets" / src.name)
        count += 1
    if APP_ORB.exists():
        shutil.copy2(APP_ORB, out / "assets" / "orb.js")
        notes.append("orb.js: the app's WebGL orb")
    else:
        shutil.copy2(FALLBACK_ORB, out / "assets" / "orb.js")
        notes.append("orb.js: canvas fallback (src/handoff/web/static/orb.js not present)")
    count += 1
    stamps = {
        p.name: hashlib.sha1(p.read_bytes()).hexdigest()[:8]
        for p in sorted((out / "assets").iterdir())
    }

    # -- landing page ------------------------------------------------------
    index_src = (SITE / "index.html").read_text(encoding="utf-8")
    nav = _between(index_src, "<!-- nav:start -->", "<!-- nav:end -->")
    footer = _between(index_src, "<!-- footer:start -->", "<!-- footer:end -->")
    (out / "index.html").write_text(_stamp(_activate(index_src, "product"), stamps), encoding="utf-8")
    count += 1

    # -- docs --------------------------------------------------------------
    template = (SITE / "templates" / "doc.html").read_text(encoding="utf-8")
    pages = docs.index()
    failures = 0
    for entry in pages:
        slug = entry["slug"]
        try:
            page = docs.render(slug)
        except Exception as exc:  # noqa: BLE001 - report every failure, then exit 1
            print(f"  FAIL docs/{slug}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
            continue
        rendered = (
            template.replace("{{title}}", html.escape(page["title"]))
            .replace("{{description}}", html.escape(entry["summary"]))
            .replace("{{sitenav}}", _activate(nav, "docs"))
            .replace("{{footer}}", footer)
            .replace("{{nav}}", _doc_nav(pages, slug))
            .replace("{{outline}}", _outline(page["outline"]))
            .replace("{{pager}}", _pager(pages, slug))
            .replace("{{content}}", page["html"])
        )
        (out / "docs" / f"{slug}.html").write_text(_stamp(rendered, stamps), encoding="utf-8")
        count += 1

    # -- screenshots -------------------------------------------------------
    for png in sorted(SCREENS.glob("*.png")):
        shutil.copy2(png, out / "screens" / png.name)
        count += 1

    # -- Cloudflare Pages control files -------------------------------------
    (out / "_headers").write_text(HEADERS, encoding="utf-8")
    (out / "_redirects").write_text(REDIRECTS, encoding="utf-8")
    count += 2

    return count, failures, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Handoff static site.")
    parser.add_argument("--out", default=str(SITE / "dist"), help="Output directory (default: site/dist)")
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    count, failures, notes = build(out)

    rel = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"{count} files → {rel}" + (f"  ({'; '.join(notes)})" if notes else ""))
    if failures:
        print(f"{failures} doc(s) failed to render", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
