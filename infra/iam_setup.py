#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Create the IAM role EventBridge Scheduler assumes to invoke Handoff.

    python infra/iam_setup.py                 # create or update, print the ARN
    python infra/iam_setup.py --target-arn …  # scope the policy to one runtime
    python infra/iam_setup.py --delete

EventBridge Scheduler does not invoke anything with your credentials — it
assumes a role of its own. Without this role, ``eventbridge_setup.py`` fails
with a validation error about the target that reads as though the schedule is
wrong, when the missing piece is the trust policy.

The permission is deliberately one action, ``bedrock-agentcore:InvokeAgentRuntime``.
A cron trigger only ever needs to invoke; it should not be able to deploy,
delete, or read anything else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from handoff import config  # noqa: E402

ROLE_NAME = "handoff-scheduler"
POLICY_NAME = "handoff-invoke-runtime"

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "scheduler.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def invoke_policy(target_arn: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "bedrock-agentcore:InvokeAgentRuntime",
                # A wildcard only until the runtime exists; pass --target-arn to
                # narrow it to the one thing the schedule is allowed to poke.
                "Resource": target_arn or "*",
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-arn", default="", help="AgentCore Runtime ARN to allow")
    parser.add_argument("--delete", action="store_true", help="Remove the role")
    args = parser.parse_args()

    import boto3
    from botocore.exceptions import ClientError

    iam = boto3.client("iam", region_name=config.AWS_REGION)

    if args.delete:
        try:
            iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=POLICY_NAME)
        except ClientError:
            pass
        try:
            iam.delete_role(RoleName=ROLE_NAME)
            print(f"  deleted  {ROLE_NAME}")
        except ClientError as exc:
            print(f"  {exc.response['Error']['Code']}  {ROLE_NAME}")
        return 0

    try:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
            Description="Lets EventBridge Scheduler invoke the Handoff AgentCore runtime",
            Tags=[{"Key": "project", "Value": "handoff"}],
        )["Role"]
        print(f"  created  {ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=ROLE_NAME)["Role"]
        iam.update_assume_role_policy(
            RoleName=ROLE_NAME, PolicyDocument=json.dumps(TRUST_POLICY)
        )
        print(f"  exists   {ROLE_NAME}")

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=POLICY_NAME,
        PolicyDocument=json.dumps(invoke_policy(args.target_arn)),
    )
    print(f"  policy   {POLICY_NAME} -> {args.target_arn or '*'}")

    print(f"\n--role-arn {role['Arn']}")
    print(
        "\nNext:\n"
        "  python infra/eventbridge_setup.py --target-arn <runtime-arn> "
        f"--role-arn {role['Arn']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
