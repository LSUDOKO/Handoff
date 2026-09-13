# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""AgentCore Browser access for workflows that must read a real web page.

Only used when ``USE_MOCK_TOOLS=false``. Snapshots are kept in the local state
directory so a run can diff against what the page looked like last week.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha1
from typing import Any

from handoff import config

_PRICE_RE = re.compile(r"\$\s?([0-9][0-9,]*)(?:\s*/\s*(mo|month|yr|year))?", re.I)


def _snapshot_path(url: str):
    key = sha1(url.encode()).hexdigest()[:16]
    return config.ensure_state_dir() / f"snapshot_{key}.json"


def load_previous_snapshot(url: str) -> dict[str, Any]:
    """Return the last snapshot taken of ``url``, or an empty shell."""
    path = _snapshot_path(url)
    if not path.exists():
        return {"url": url, "tiers": [], "captured_at": ""}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"url": url, "tiers": [], "captured_at": ""}


def save_snapshot(url: str, snapshot: dict[str, Any]) -> None:
    _snapshot_path(url).write_text(json.dumps(snapshot, indent=2))


def _extract_tiers(text: str) -> list[dict[str, Any]]:
    """Pull plausible pricing tiers out of page text.

    Deliberately crude: the workflow's job is to notice *that* something moved
    and hand the diff to a human, not to perfectly model someone's pricing page.
    """
    tiers: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 120:
            continue
        match = _PRICE_RE.search(line)
        if not match:
            continue
        name = _PRICE_RE.sub("", line).strip(" -–—:·|")
        if not name:
            continue
        period = (match.group(2) or "mo").lower()
        tiers.append(
            {
                "name": name[:60],
                "price": int(match.group(1).replace(",", "")),
                "period": "mo" if period.startswith("mo") else "yr",
            }
        )
    return tiers


def capture_pricing(url: str) -> dict[str, Any]:
    """Load ``url`` in an AgentCore Browser session and extract its pricing.

    Falls back to a plain HTTP fetch when the Browser tool is unavailable, so a
    missing AgentCore session degrades to a worse reading rather than a crash.
    """
    text = ""
    try:
        from bedrock_agentcore.tools.browser_client import browser_session

        with browser_session(config.AWS_REGION) as client:
            text = client.navigate_and_extract_text(url)  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"[handoff] AgentCore Browser unavailable ({exc}); falling back to HTTP")
        try:
            import httpx

            html = httpx.get(url, timeout=20.0, follow_redirects=True).text
            text = re.sub(r"<[^>]+>", "\n", html)
        except Exception as fetch_exc:  # pragma: no cover - network
            print(f"[handoff] page fetch failed: {fetch_exc}")
            text = ""

    snapshot = {
        "url": url,
        "captured_at": datetime.now(UTC).isoformat(),
        "tiers": _extract_tiers(text),
    }
    save_snapshot(url, snapshot)
    return snapshot
