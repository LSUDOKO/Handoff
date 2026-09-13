#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Turn each active cron workflow into an EventBridge schedule.

    python infra/eventbridge_setup.py --target-arn <agentcore-arn> --role-arn <arn>
    python infra/eventbridge_setup.py --list
    python infra/eventbridge_setup.py --delete inbox-triage-morning

This is what makes "every weekday at 8am" mean the same thing in production as
it did in the chat where the user said it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from handoff.models import TriggerType, WorkflowStatus  # noqa: E402
from handoff.store import get_store  # noqa: E402
from handoff.tools.scheduler import (  # noqa: E402
    create_schedule,
    cron_to_eventbridge,
    delete_schedule,
)
from handoff.tools.workflow_store import seed_examples  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-arn", help="AgentCore Runtime ARN to invoke")
    parser.add_argument("--role-arn", help="IAM role EventBridge Scheduler assumes")
    parser.add_argument("--list", action="store_true", help="Show what would be scheduled")
    parser.add_argument("--delete", metavar="WORKFLOW_ID", help="Remove one schedule")
    args = parser.parse_args()

    seed_examples()
    store = get_store()

    if args.delete:
        print(delete_schedule(args.delete))
        return 0

    cron_workflows = [
        w
        for w in store.list_workflows()
        if w.trigger.type is TriggerType.CRON and w.status is WorkflowStatus.ACTIVE
    ]

    if args.list or not (args.target_arn and args.role_arn):
        if not args.list:
            print("Pass --target-arn and --role-arn to actually create schedules.\n")
        print("Active cron workflows:")
        for workflow in cron_workflows:
            print(
                f"  {workflow.workflow_id:<28} {workflow.trigger.schedule:<14} "
                f"-> {cron_to_eventbridge(workflow.trigger.schedule)} "
                f"[{workflow.trigger.timezone}]"
            )
        return 0

    for workflow in cron_workflows:
        result = create_schedule(workflow, args.target_arn, args.role_arn)
        print(f"  {workflow.workflow_id}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
