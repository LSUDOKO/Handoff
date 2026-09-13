# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The DynamoDB backend, without DynamoDB.

The single-table layout exists because the obvious alternative is broken in a
way that unit tests never catch: several collections sharing a table keyed on
one id field write fine for whichever collection owns that key and fail for
every other one. These tests drive the collection against a stand-in table so
the partitioning is checked on every run, not only when someone sets
USE_DYNAMODB=true.
"""

from __future__ import annotations

from typing import Any

import pytest

from handoff.models import AuditEntry, WorkflowRun
from handoff.platform.models import Skill
from handoff.store import DynamoCollection


class FakeTable:
    """Enough of boto3's Table to exercise keys, queries and pagination."""

    #: Items returned per query page, so pagination is actually traversed.
    PAGE = 2

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    def put_item(self, Item: dict) -> None:  # noqa: N803 - boto3's casing
        if "pk" not in Item or "sk" not in Item:
            raise AssertionError(f"write without a full key: {sorted(Item)}")
        self.rows[(Item["pk"], Item["sk"])] = Item

    def get_item(self, Key: dict) -> dict:  # noqa: N803
        item = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def delete_item(self, Key: dict) -> None:  # noqa: N803
        self.rows.pop((Key["pk"], Key["sk"]), None)

    def query(self, **kwargs: Any) -> dict:
        wanted = kwargs["KeyConditionExpression"].get_expression()["values"][1]
        matching = sorted(k for k in self.rows if k[0] == wanted)

        start = kwargs.get("ExclusiveStartKey")
        if start:
            after = (start["pk"], start["sk"])
            matching = [k for k in matching if k > after]

        page, rest = matching[: self.PAGE], matching[self.PAGE :]
        response: dict[str, Any] = {"Items": [self.rows[k] for k in page]}
        if rest and page:
            response["LastEvaluatedKey"] = {"pk": page[-1][0], "sk": page[-1][1]}
        return response


@pytest.fixture
def table(monkeypatch):
    fake = FakeTable()

    class FakeResource:
        def Table(self, _name):  # noqa: N802 - boto3's casing
            return fake

    import boto3

    monkeypatch.setattr(boto3, "resource", lambda *a, **kw: FakeResource())
    return fake


def _collection(table, model, key_field, name):
    return DynamoCollection("handoff", model, key_field, name)


def test_every_collection_writes_regardless_of_its_id_field(table):
    """The failure the single-table layout fixes.

    ``runs`` is keyed on run_id and ``skills`` on skill_id. Both must write to
    the same table.
    """
    runs = _collection(table, WorkflowRun, "run_id", "runs")
    skills = _collection(table, Skill, "skill_id", "skills")

    runs.put(WorkflowRun(workflow_id="w1", run_id="run_1"), "run_id")
    skills.put(Skill(name="Escalation style", body="ask when unsure"), "skill_id")

    assert {key[0] for key in table.rows} == {"runs", "skills"}


def test_listing_one_collection_never_returns_another(table):
    runs = _collection(table, WorkflowRun, "run_id", "runs")
    audit = _collection(table, AuditEntry, "entry_id", "audit")

    runs.put(WorkflowRun(workflow_id="w1", run_id="run_1"), "run_id")
    for i in range(3):
        audit.append(AuditEntry(run_id="run_1", workflow_id="w1", action=f"a{i}"))

    listed = runs.all()
    assert len(listed) == 1
    assert isinstance(listed[0], WorkflowRun)
    assert len(audit.all()) == 3


def test_listing_pages_past_the_first_response(table):
    """A run's audit trail outgrows one page well before anyone notices."""
    audit = _collection(table, AuditEntry, "entry_id", "audit")
    for i in range(7):
        audit.append(AuditEntry(run_id="run_1", workflow_id="w1", action=f"a{i}"))

    assert len(audit.all()) == 7, "pagination stopped at the first page"


def test_get_and_delete_address_items_by_collection_and_id(table):
    runs = _collection(table, WorkflowRun, "run_id", "runs")
    runs.put(WorkflowRun(workflow_id="w1", run_id="run_1"), "run_id")

    found = runs.get("run_id", "run_1")
    assert found is not None and found.run_id == "run_1"
    assert runs.get("run_id", "nope") is None

    runs.delete("run_id", "run_1")
    assert runs.get("run_id", "run_1") is None


def test_the_partition_keys_do_not_leak_into_the_model(table):
    """pk/sk are storage detail; the model should never see them."""
    runs = _collection(table, WorkflowRun, "run_id", "runs")
    runs.put(WorkflowRun(workflow_id="w1", run_id="run_1"), "run_id")

    restored = runs.get("run_id", "run_1")
    assert not hasattr(restored, "pk")
    assert not hasattr(restored, "sk")
