#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Create or update the Handoff AgentCore Runtime from the image in ECR.

    python infra/agentcore_runtime.py                 # role + runtime, wait until READY
    python infra/agentcore_runtime.py --invoke        # then smoke-test it
    python infra/agentcore_runtime.py --status
    python infra/agentcore_runtime.py --delete

This talks to the control plane directly with boto3. The Python starter
toolkit's `agentcore configure` / `launch` pair is deprecated in favour of an
npm CLI, prompts interactively, and wants a config file the toolkit no longer
writes — a deploy script that shells out to it "succeeds" while launching
nothing. Three API calls are easier to reason about than either CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from handoff import config  # noqa: E402

RUNTIME_NAME = "handoff"
ROLE_NAME = "handoff-runtime"
POLICY_NAME = "handoff-runtime-access"
ECR_REPO = "handoff"


def account_id() -> str:
    import boto3

    return boto3.client("sts").get_caller_identity()["Account"]


def runtime_env() -> dict[str, str]:
    """What the deployed agent must know that the image must not carry.

    The container filesystem is ephemeral, so the deployment has to be told to
    use DynamoDB and AgentCore Memory or it loses every run between calls.
    These travel as environment variables at launch rather than baked into
    the image because the memory id and table name belong to one account, and
    an image is a thing you might publish.
    """
    settings = {
        "HANDOFF_MODEL_PROVIDER": "bedrock",
        "AWS_REGION": config.AWS_REGION,
        "BEDROCK_MODEL_ID": config.BEDROCK_MODEL_ID,
        "BEDROCK_FALLBACK_MODEL_ID": config.BEDROCK_FALLBACK_MODEL_ID,
        "USE_DYNAMODB": str(config.USE_DYNAMODB).lower(),
        "DDB_TABLE": config.DDB_TABLE,
        "USE_AGENTCORE_MEMORY": str(config.USE_AGENTCORE_MEMORY).lower(),
        "AGENTCORE_MEMORY_ID": config.AGENTCORE_MEMORY_ID,
        "USE_MOCK_TOOLS": str(config.USE_MOCK_TOOLS).lower(),
        "HANDOFF_STATE_DIR": "/tmp/handoff-state",
    }
    return {k: v for k, v in settings.items() if v}


# --- IAM -------------------------------------------------------------------


def trust_policy(account: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{config.AWS_REGION}:{account}:*"
                    },
                },
            }
        ],
    }


def access_policy(account: str) -> dict:
    region = config.AWS_REGION
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PullImage",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                "Resource": f"arn:aws:ecr:{region}:{account}:repository/{ECR_REPO}",
            },
            {
                "Sid": "EcrLogin",
                "Effect": "Allow",
                "Action": "ecr:GetAuthorizationToken",
                "Resource": "*",
            },
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "logs:DescribeLogGroups",
                ],
                "Resource": f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/*",
            },
            {
                "Sid": "Telemetry",
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "cloudwatch:PutMetricData",
                ],
                "Resource": "*",
            },
            {
                "Sid": "Reasoning",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                "Resource": "*",
            },
            {
                "Sid": "Identity",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                "Resource": "*",
            },
            {
                "Sid": "Memory",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:ListMemoryRecords",
                    "bedrock-agentcore:GetMemoryRecord",
                    "bedrock-agentcore:GetMemory",
                ],
                "Resource": f"arn:aws:bedrock-agentcore:{region}:{account}:memory/*",
            },
            {
                "Sid": "Storage",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Query",
                    "dynamodb:DescribeTable",
                ],
                "Resource": f"arn:aws:dynamodb:{region}:{account}:table/{config.DDB_TABLE}",
            },
        ],
    }


def ensure_role(account: str) -> str:
    import boto3

    iam = boto3.client("iam")
    try:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy(account)),
            Description="Execution role for the Handoff AgentCore Runtime",
            Tags=[{"Key": "project", "Value": "handoff"}],
        )["Role"]
        print(f"  created  role {ROLE_NAME}")
        created = True
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=ROLE_NAME)["Role"]
        iam.update_assume_role_policy(
            RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust_policy(account))
        )
        print(f"  exists   role {ROLE_NAME}")
        created = False

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=POLICY_NAME,
        PolicyDocument=json.dumps(access_policy(account)),
    )
    if created:
        # IAM is eventually consistent; a runtime created in the same second
        # as its role fails with "cannot assume role".
        time.sleep(10)
    return role["Arn"]


# --- Runtime ---------------------------------------------------------------


def image_uri(account: str) -> str:
    return f"{account}.dkr.ecr.{config.AWS_REGION}.amazonaws.com/{ECR_REPO}:latest"


def find_runtime(client) -> dict | None:
    for rt in client.list_agent_runtimes().get("agentRuntimes", []):
        if rt.get("agentRuntimeName") == RUNTIME_NAME:
            return rt
    return None


def wait_ready(client, runtime_id: str, timeout: int = 600) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        status = client.get_agent_runtime(agentRuntimeId=runtime_id)["status"]
        if status != last:
            print(f"  status   {status}")
            last = status
        if status == "READY":
            return status
        if status.endswith("FAILED"):
            detail = client.get_agent_runtime(agentRuntimeId=runtime_id)
            raise SystemExit(f"runtime {status}: {detail.get('failureReason', detail)}")
        time.sleep(8)
    raise SystemExit("timed out waiting for the runtime to become READY")


def deploy() -> str:
    import boto3

    account = account_id()
    role_arn = ensure_role(account)
    client = boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)

    artifact = {"containerConfiguration": {"containerUri": image_uri(account)}}
    env = runtime_env()
    existing = find_runtime(client)

    if existing is None:
        print(f"  creating runtime {RUNTIME_NAME} from {image_uri(account)}")
        result = client.create_agent_runtime(
            agentRuntimeName=RUNTIME_NAME,
            description="Handoff — autonomous workflows with a human decision gate",
            agentRuntimeArtifact=artifact,
            roleArn=role_arn,
            networkConfiguration={"networkMode": "PUBLIC"},
            protocolConfiguration={"serverProtocol": "HTTP"},
            environmentVariables=env,
            clientToken=str(uuid.uuid4()),
            tags={"project": "handoff"},
        )
    else:
        print(f"  updating runtime {RUNTIME_NAME} ({existing['agentRuntimeId']})")
        result = client.update_agent_runtime(
            agentRuntimeId=existing["agentRuntimeId"],
            description="Handoff — autonomous workflows with a human decision gate",
            agentRuntimeArtifact=artifact,
            roleArn=role_arn,
            networkConfiguration={"networkMode": "PUBLIC"},
            protocolConfiguration={"serverProtocol": "HTTP"},
            environmentVariables=env,
            clientToken=str(uuid.uuid4()),
        )

    runtime_id = result["agentRuntimeId"]
    wait_ready(client, runtime_id)
    arn = result["agentRuntimeArn"]
    print(f"\nAGENTCORE_RUNTIME_ARN={arn}")
    return arn


def invoke(arn: str, payload: dict) -> dict:
    import boto3

    client = boto3.client("bedrock-agentcore", region_name=config.AWS_REGION)
    response = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=uuid.uuid4().hex + uuid.uuid4().hex[:8],
        payload=json.dumps(payload).encode(),
        contentType="application/json",
        accept="application/json",
    )
    body = response["response"].read() if hasattr(response.get("response"), "read") else response.get("response")
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body.decode() if isinstance(body, bytes) else str(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invoke", action="store_true", help="Smoke-test after deploy")
    parser.add_argument("--status", action="store_true", help="Show the runtime")
    parser.add_argument("--delete", action="store_true", help="Delete the runtime")
    args = parser.parse_args()

    import boto3

    print(f"AgentCore Runtime — {config.AWS_REGION}\n")
    control = boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)

    if args.status:
        rt = find_runtime(control)
        print(json.dumps(rt, indent=2, default=str) if rt else "  no runtime named handoff")
        return 0

    if args.delete:
        rt = find_runtime(control)
        if rt:
            control.delete_agent_runtime(agentRuntimeId=rt["agentRuntimeId"])
            print(f"  deleted  {rt['agentRuntimeArn']}")
        else:
            print("  nothing to delete")
        return 0

    arn = deploy()

    if args.invoke:
        print("\nSmoke test — status:")
        print(json.dumps(invoke(arn, {"type": "status"}), indent=2)[:1500])

    print(
        "\nNext:\n"
        f"  python infra/eventbridge_setup.py --target-arn {arn} "
        "--role-arn arn:aws:iam::<account>:role/handoff-scheduler"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
