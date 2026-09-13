#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Load the example workflow configs into the store."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from handoff.tools.workflow_store import seed_examples  # noqa: E402


def main() -> int:
    seeded = seed_examples()
    if not seeded:
        print("Examples already loaded.")
        return 0
    for workflow in seeded:
        print(f"  {workflow.workflow_id:<28} {workflow.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
