#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Deploy Handoff to Bedrock AgentCore Runtime.

    python infra/deploy_agentcore.py --check     # what's missing before I can deploy
    python infra/deploy_agentcore.py             # build, push, launch
    python infra/deploy_agentcore.py --invoke    # smoke-test the deployed agent

Every step is printed as the command it runs, so a deploy that fails halfway
can be finished by hand.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from handoff import config  # noqa: E402

ECR_REPO = "handoff"
AGENT_NAME = "handoff"


def which(tool: str) -> str | None:
    """Find an executable, including one installed in the venv we run under.

    ``shutil.which`` only searches PATH, so invoking this script as
    ``.venv/bin/python infra/deploy_agentcore.py`` without activating the venv
    reports the agentcore CLI missing when it is installed right beside the
    interpreter running this line.
    """
    beside = Path(sys.executable).parent / tool
    if beside.is_file():
        return str(beside)
    return shutil.which(tool)


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, text=True, capture_output=False)


def capture(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout.strip()


def preflight() -> list[str]:
    """Everything that must be true before a deploy can work."""
    problems: list[str] = []

    for tool, hint in [
        ("aws", "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"),
        ("docker", "https://docs.docker.com/get-docker/"),
    ]:
        if which(tool) is None:
            problems.append(f"{tool} is not installed — {hint}")

    if shutil.which("aws"):
        try:
            identity = json.loads(capture(["aws", "sts", "get-caller-identity"]))
            print(f"  AWS account {identity['Account']} as {identity['Arn']}")
        except subprocess.CalledProcessError:
            problems.append(
                "No usable AWS credentials — run `aws configure` or `aws sso login`"
            )

    try:
        import bedrock_agentcore  # noqa: F401
    except ImportError:
        problems.append("bedrock-agentcore not installed — pip install bedrock-agentcore")

    return problems


def account_id() -> str:
    return json.loads(capture(["aws", "sts", "get-caller-identity"]))["Account"]


def ecr_uri() -> str:
    return f"{account_id()}.dkr.ecr.{config.AWS_REGION}.amazonaws.com/{ECR_REPO}"


def build_and_push() -> str:
    uri = ecr_uri()

    print("\n[1/4] ECR repository")
    run(
        ["aws", "ecr", "create-repository", "--repository-name", ECR_REPO,
         "--region", config.AWS_REGION],
        check=False,
    )

    print("\n[2/4] Docker login")
    password = capture(["aws", "ecr", "get-login-password", "--region", config.AWS_REGION])
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", uri.split("/")[0]],
        input=password,
        text=True,
        check=True,
    )

    print("\n[3/4] Build (linux/arm64 — AgentCore Runtime requires it)")
    run(
        ["docker", "buildx", "build", "--platform", "linux/arm64",
         "-t", f"{uri}:latest", "--push", str(ROOT)]
    )

    print(f"\n  pushed {uri}:latest")
    return uri


def launch() -> str:
    """Create or update the Runtime from the pushed image.

    Delegates to ``infra/agentcore_runtime.py``, which talks to the control
    plane directly. The Python starter toolkit's ``configure``/``launch`` pair
    is deprecated, prompts interactively, and reports success while launching
    nothing when its config file is missing — which is how an earlier version
    of this script printed "Deployed." over an empty account.
    """
    print("\n[4/4] AgentCore Runtime")
    if not config.USE_DYNAMODB:
        print(
            "  note: USE_DYNAMODB is false — the deployed agent will keep state on\n"
            "        an ephemeral container filesystem and lose it between calls.\n"
            "        Run infra/dynamodb_setup.py and set USE_DYNAMODB=true."
        )
    from agentcore_runtime import deploy  # noqa: E402  (sibling script)

    return deploy()


def invoke(arn: str) -> None:
    from agentcore_runtime import invoke as call

    print("\nSmoke test — status:")
    print(json.dumps(call(arn, {"type": "status"}), indent=2)[:1500])
    print("\nSmoke test — one scheduled run:")
    print(json.dumps(call(arn, {"type": "tick", "workflow_id": "inbox-triage-morning"}), indent=2)[:1500])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Preflight only")
    parser.add_argument("--invoke", action="store_true", help="Smoke-test the deployment")
    parser.add_argument("--skip-build", action="store_true", help="Launch without rebuilding")
    args = parser.parse_args()

    print(f"Handoff deploy — region {config.AWS_REGION}\n")
    problems = preflight()

    if problems:
        print("\nNot ready to deploy:")
        for problem in problems:
            print(f"  - {problem}")
        print("\nHandoff still runs locally without any of this:")
        print("  python scripts/run_local.py --serve")
        return 1

    print("\nPreflight passed.")
    if args.check:
        return 0

    if args.invoke:
        import boto3
        from agentcore_runtime import find_runtime

        existing = find_runtime(
            boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)
        )
        if existing is None:
            print("No runtime to invoke — deploy first.")
            return 1
        invoke(existing["agentRuntimeArn"])
        return 0

    if not args.skip_build:
        build_and_push()
    arn = launch()
    invoke(arn)

    print(
        "\nDeployed. Next:\n"
        f"  python infra/eventbridge_setup.py --target-arn {arn} \\\n"
        "      --role-arn $(python infra/iam_setup.py | grep -o 'arn:aws:iam::[^ ]*')\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
