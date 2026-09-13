#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Create the Lambda that turns an EventBridge tick into a Runtime invocation.

    python infra/lambda_setup.py --runtime-arn <agentcore-runtime-arn>
    python infra/lambda_setup.py --delete

EventBridge Scheduler cannot target AgentCore Runtime directly — CreateSchedule
rejects it with "bedrock-agentcore is not a supported service for a target".
It can target Lambda, and Lambda can call InvokeAgentRuntime, so the schedule
fires a twelve-line function that forwards its input payload unchanged. The
payload is the same ``{"type": "tick", "workflow_id": ...}`` the runtime
accepts from anything else, so the bridge adds no vocabulary of its own.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from handoff import config  # noqa: E402

FUNCTION_NAME = "handoff-tick"
ROLE_NAME = "handoff-tick"
SCHEDULER_ROLE = "handoff-scheduler"

HANDLER_SOURCE = '''\
import json
import os
import uuid

import boto3

RUNTIME_ARN = os.environ["RUNTIME_ARN"]
client = boto3.client("bedrock-agentcore")


def handler(event, context):
    """Forward a schedule tick to the Handoff runtime, unchanged."""
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=uuid.uuid4().hex + uuid.uuid4().hex[:8],
        payload=json.dumps(event).encode(),
        contentType="application/json",
        accept="application/json",
    )
    body = response["response"].read()
    print(body[:2000].decode("utf-8", "replace"))
    return {"ok": True, "bytes": len(body)}
'''


def bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("handler.py", HANDLER_SOURCE)
    return buf.getvalue()


def ensure_role(iam, account: str, runtime_arn: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "bedrock-agentcore:InvokeAgentRuntime",
                "Resource": [runtime_arn, f"{runtime_arn}/runtime-endpoint/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"arn:aws:logs:{config.AWS_REGION}:{account}:log-group:/aws/lambda/{FUNCTION_NAME}:*",
            },
        ],
    }
    try:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Lets the Handoff tick Lambda invoke the AgentCore runtime",
            Tags=[{"Key": "project", "Value": "handoff"}],
        )["Role"]
        print(f"  created  role {ROLE_NAME}")
        time.sleep(10)  # IAM propagation before Lambda tries to assume it
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=ROLE_NAME)["Role"]
        print(f"  exists   role {ROLE_NAME}")
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="invoke-runtime", PolicyDocument=json.dumps(policy))
    return role["Arn"]


def allow_scheduler(iam, function_arn: str) -> None:
    """The scheduler role gets exactly one more permission: invoke this function."""
    iam.put_role_policy(
        RoleName=SCHEDULER_ROLE,
        PolicyName="handoff-invoke-tick",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": function_arn}
                ],
            }
        ),
    )
    print(f"  policy   {SCHEDULER_ROLE} may invoke {FUNCTION_NAME}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", help="AgentCore Runtime ARN to forward ticks to")
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    import boto3
    from botocore.exceptions import ClientError

    iam = boto3.client("iam")
    lam = boto3.client("lambda", region_name=config.AWS_REGION)
    account = boto3.client("sts").get_caller_identity()["Account"]
    print(f"Tick bridge — {config.AWS_REGION}\n")

    if args.delete:
        for call in (
            lambda: lam.delete_function(FunctionName=FUNCTION_NAME),
            lambda: iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName="invoke-runtime"),
            lambda: iam.delete_role(RoleName=ROLE_NAME),
        ):
            try:
                call()
            except ClientError as exc:
                print(f"  {exc.response['Error']['Code']}")
        print("  deleted")
        return 0

    if not args.runtime_arn:
        parser.error("--runtime-arn is required")

    role_arn = ensure_role(iam, account, args.runtime_arn)
    code = bundle()
    env = {"Variables": {"RUNTIME_ARN": args.runtime_arn}}

    try:
        fn = lam.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="handler.handler",
            Code={"ZipFile": code},
            Description="Forwards EventBridge ticks to the Handoff AgentCore runtime",
            Timeout=300,
            MemorySize=256,
            Environment=env,
            Tags={"project": "handoff"},
        )
        print(f"  created  {FUNCTION_NAME}")
    except lam.exceptions.ResourceConflictException:
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=code)
        lam.get_waiter("function_updated").wait(FunctionName=FUNCTION_NAME)
        fn = lam.update_function_configuration(
            FunctionName=FUNCTION_NAME, Role=role_arn, Environment=env, Timeout=300
        )
        print(f"  updated  {FUNCTION_NAME}")

    lam.get_waiter("function_active").wait(FunctionName=FUNCTION_NAME)
    allow_scheduler(iam, fn["FunctionArn"])

    print(f"\nLAMBDA_ARN={fn['FunctionArn']}")
    print(
        "\nNext:\n"
        f"  python infra/eventbridge_setup.py --target-arn {fn['FunctionArn']} "
        f"--role-arn arn:aws:iam::{account}:role/{SCHEDULER_ROLE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
