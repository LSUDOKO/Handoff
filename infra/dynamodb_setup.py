#!/usr/bin/env python3
# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Create the DynamoDB table Handoff uses when USE_DYNAMODB=true.

    python infra/dynamodb_setup.py
    python infra/dynamodb_setup.py --delete
    python infra/dynamodb_setup.py --delete-legacy   # the old three-table layout

One table holds every collection, partitioned by collection name: ``pk`` is the
collection ("runs", "skills", "usage"), ``sk`` is the item's id. Handoff keeps
fourteen small collections that are only ever read by id or listed whole, and
each has its own id attribute — so one table per collection would be fourteen
things to provision, while several collections sharing a table keyed on one id
field cannot work at all.

On-demand billing, so an idle deployment costs nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from handoff import config  # noqa: E402

#: The pre-single-table layout, kept only so an existing deployment can clean up.
LEGACY_TABLES = ("handoff_workflows", "handoff_audit", "handoff_interrupts")


def create(client, name: str) -> None:
    try:
        client.create_table(
            TableName=name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[{"Key": "project", "Value": "handoff"}],
        )
        print(f"  creating {name} (pk: collection, sk: item id)")
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
    parser.add_argument("--delete", action="store_true", help="Tear the table down")
    parser.add_argument(
        "--delete-legacy",
        action="store_true",
        help="Remove the old handoff_workflows/audit/interrupts tables",
    )
    args = parser.parse_args()

    import boto3

    client = boto3.client("dynamodb", region_name=config.AWS_REGION)
    print(f"DynamoDB in {config.AWS_REGION}:")

    if args.delete_legacy:
        for name in LEGACY_TABLES:
            delete(client, name)
        return 0

    if args.delete:
        delete(client, config.DDB_TABLE)
        return 0

    create(client, config.DDB_TABLE)
    print(f"\nSet USE_DYNAMODB=true and DDB_TABLE={config.DDB_TABLE} in .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
