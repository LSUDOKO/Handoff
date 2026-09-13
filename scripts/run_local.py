#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Run Handoff locally — no AWS account required.

    python scripts/run_local.py                    # one run, printed as it goes
    python scripts/run_local.py --serve            # start the web UI on :8000
    python scripts/run_local.py --demo             # the full story, end to end
    python scripts/run_local.py --offline          # force the scripted model

--demo is the one to watch: it runs the workflow, shows what it handled alone,
answers the escalations for you, then runs it again to show it doesn't ask the
same questions twice.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RULE = "─" * 72


def _provider_ready() -> tuple[bool, str]:
    """Can the configured provider actually make a call?

    Checked here rather than deep in a run so the fallback to the scripted
    model is announced up front, not discovered as a stack trace.
    """
    from handoff import config

    provider = config.active_provider()
    if provider == "fake":
        return True, "fake"
    if provider == "groq":
        return bool(config.GROQ_API_KEY), provider
    if provider == "anthropic":
        return bool(config.ANTHROPIC_API_KEY), provider
    try:
        import boto3

        return boto3.Session().get_credentials() is not None, provider
    except Exception:
        return False, provider


def banner(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def show_run(outcome, store) -> None:
    print(f"  status          {outcome['status']}")
    print(f"  handled alone   {outcome['auto_count']}")
    print(f"  from your rules {outcome['memory_count']}")
    print(f"  waiting on you  {len(outcome['pending_interrupts'])}")

    for payload in store.pending_interrupts():
        if payload.run_id != outcome["run_id"]:
            continue
        print(f"\n  ── {payload.item.subject}")
        print(f"     from {payload.item.sender}")
        print(f"     {payload.agent_analysis.confidence:.0%} sure of "
              f"{payload.agent_analysis.suggested_action or 'nothing'}")
        print(f"     {payload.agent_analysis.reasoning}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default="inbox-triage-morning")
    parser.add_argument("--serve", action="store_true", help="Start the web UI")
    parser.add_argument("--demo", action="store_true", help="Run the full story")
    parser.add_argument("--offline", action="store_true", help="Force the scripted model")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    ready, provider = _provider_ready()
    if args.offline or not ready:
        if not args.offline:
            print(f"Provider '{provider}' has no usable credentials — using the scripted offline model.")
            print("Run `python -m handoff.cli doctor` to see what's missing.\n")
        os.environ["HANDOFF_FAKE_MODEL"] = "true"
        from handoff import config

        config.USE_FAKE_MODEL = True
        config.get_model.cache_clear()
    else:
        print(f"Reasoning on {provider}: {__import__('handoff.config', fromlist=['x']).active_model_id()}\n")

    from handoff import config
    from handoff.agents.executor import run_workflow, submit_decision
    from handoff.store import get_store
    from handoff.tools.workflow_store import seed_examples

    config.configure_observability()
    seed_examples()
    store = get_store()

    if args.serve:
        import uvicorn

        print(f"Handoff UI → http://localhost:{args.port}")
        uvicorn.run("handoff.web.server:app", host="127.0.0.1", port=args.port)
        return 0

    banner("RUN 1 — it works the inbox on its own")
    first = run_workflow(args.workflow, "cron")
    show_run(first, store)

    if not args.demo:
        print(f"\nAnswer them at: {config.UI_BASE_URL}/decide/<id>")
        print("Or run with --demo to watch the whole loop.")
        return 0

    banner("YOU DECIDE — the three it couldn't call")
    answers = {
        "partnerships@vendor.com": ("archive", "Cold outreach. Never worth a ticket."),
        "hr@company.com": ("skip", "I already read it."),
        "cfo@company.com": ("file_ticket", "Track the freeze so we don't forget."),
    }
    for payload in list(store.pending_interrupts()):
        action, note = answers.get(payload.item.sender, ("skip", ""))
        print(f"  {payload.item.sender:<28} → {action}")
        submit_decision(payload.interrupt_id, action, note)

    print("\n  Rules it wrote down:")
    for rule in store.list_preferences():
        print(f"    {rule.action:<12} {rule.pattern}")

    banner("RUN 2 — same inbox, and now it doesn't ask")
    second = run_workflow(args.workflow, "cron")
    show_run(second, store)
    print(f"\n  {second['summary']}")

    banner("The point")
    print(
        f"  Run 1 asked you {first['human_count'] or len(first['pending_interrupts'])} questions.\n"
        f"  Run 2 asked you {len(second['pending_interrupts'])}.\n"
        f"  Nothing irreversible happened without you saying so."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
