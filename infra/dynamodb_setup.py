#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Create the DynamoDB tables Handoff uses when USE_DYNAMODB=true.

    python infra/dynamodb_setup.py [--delete]

On-demand billing, so an idle deployment costs nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from handoff import config  # noqa: E402

TABLES = [
    (config.DDB_WORKFLOWS_TABLE, "workflow_id"),
    (config.DDB_AUDIT_TABLE, "entry_id"),
    (config.DDB_INTERRUPTS_TABLE, "interrupt_id"),
]


def create(client, name: str, key: str) -> None:
    try:
        client.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
            Tags=[{"Key": "project", "Value": "handoff"}],
        )
        print(f"  creating {name} (key: {key})")
        client.get_waiter("table_exists").wait(TableName=name)
        print(f"  ready    {name}")
    except client.exceptions.ResourceInUseException:
        print(f"  exists   {name}")


def delete(client, name: str) -> None:
    try:
        client.delete_table(TableName=name)
        print(f"  deleted  {name}")
    except client.exceptions.ResourceNotFoundException:
        print(f"  missing  {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="Tear the tables down")
    args = parser.parse_args()

    import boto3

    client = boto3.client("dynamodb", region_name=config.AWS_REGION)
    print(f"DynamoDB tables in {config.AWS_REGION}:")
    for name, key in TABLES:
        if args.delete:
            delete(client, name)
        else:
            create(client, name, key)

    if not args.delete:
        print("\nSet USE_DYNAMODB=true in .env to start using them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
