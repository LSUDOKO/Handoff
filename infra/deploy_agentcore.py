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

    if which("agentcore") is None:
        problems.append(
            "agentcore CLI missing — pip install bedrock-agentcore-starter-toolkit"
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


def launch() -> None:
    print("\n[4/4] AgentCore Runtime")
    run(
        [which("agentcore") or "agentcore", "configure", "--entrypoint", "src/handoff/app.py",
         "--name", AGENT_NAME, "--region", config.AWS_REGION],
        check=False,
    )
    run([which("agentcore") or "agentcore", "launch"], check=False)


def invoke() -> None:
    print("\nSmoke test — status:")
    run([which("agentcore") or "agentcore", "invoke", json.dumps({"type": "status"})], check=False)
    print("\nSmoke test — one scheduled run:")
    run(
        [which("agentcore") or "agentcore", "invoke",
         json.dumps({"type": "tick", "workflow_id": "inbox-triage-morning"})],
        check=False,
    )


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
        invoke()
        return 0

    if not args.skip_build:
        build_and_push()
    launch()
    invoke()

    print(
        "\nDeployed. Next:\n"
        "  1. python infra/memory_setup.py        # AgentCore Memory for learned rules\n"
        "  2. python infra/dynamodb_setup.py      # durable workflow + audit storage\n"
        "  3. python infra/eventbridge_setup.py --target-arn <arn> --role-arn <arn>\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
