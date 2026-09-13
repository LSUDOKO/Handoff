#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Create the AgentCore Memory store that holds learned preferences.

    python infra/memory_setup.py

Prints the memory id — put it in .env as AGENTCORE_MEMORY_ID and set
USE_AGENTCORE_MEMORY=true.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from handoff import config  # noqa: E402

NAME = "handoff_preferences"


def main() -> int:
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)

    for memory in client.list_memories().get("memories", []):
        if memory.get("id", "").startswith(NAME):
            print(f"Already exists: {memory['id']}")
            return 0

    response = client.create_memory(
        name=NAME,
        description="Rules Handoff learned from the user's decisions",
        eventExpiryDuration=90,
        memoryStrategies=[
            {
                "userPreferenceMemoryStrategy": {
                    "name": "handoff_user_preferences",
                    "namespaces": ["/preferences/{actorId}"],
                }
            },
            {
                "semanticMemoryStrategy": {
                    "name": "handoff_semantic",
                    "namespaces": ["/decisions/{actorId}"],
                }
            },
        ],
    )

    memory_id = response["memory"]["id"]
    print(f"Creating {memory_id} …")
    for _ in range(60):
        status = client.get_memory(memoryId=memory_id)["memory"]["status"]
        if status == "ACTIVE":
            break
        time.sleep(5)

    print(f"\nAGENTCORE_MEMORY_ID={memory_id}")
    print("USE_AGENTCORE_MEMORY=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
