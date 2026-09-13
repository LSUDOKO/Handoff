# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Persistence for workflows, runs, interrupts, audit entries and preferences.

Two backends behind one interface:

* **JSON files** under ``HANDOFF_STATE_DIR`` — the default. Handoff runs
  end-to-end on a laptop with no AWS account, which matters for a judge who
  wants to clone the repo and press play.
* **DynamoDB** — enabled with ``USE_DYNAMODB=true``. Same method signatures,
  same models; only the read/write primitives change.

Writes take a lock-free read-modify-write on a single small file per
collection. That is fine for one worker and one UI process, which is the
deployment shape; DynamoDB is the answer for anything larger.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from handoff import config
from handoff.models import (
    AuditEntry,
    InterruptPayload,
    LearnedPreference,
    RunStatus,
    WorkflowConfig,
    WorkflowRun,
)

T = TypeVar("T", bound=BaseModel)

_LOCK = threading.RLock()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"not JSON serialisable: {type(obj)!r}")


class JsonCollection:
    """A list of pydantic models persisted as one JSON file."""

    def __init__(self, name: str, model: type[T]) -> None:
        self.name = name
        self.model = model
        self._path = config.ensure_state_dir() / f"{name}.json"

    @property
    def path(self) -> Path:
        return self._path

    def _read_raw(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text() or "[]")
        except json.JSONDecodeError:
            return []

    def _write_raw(self, rows: list[dict]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, indent=2, default=_json_default))
        tmp.replace(self._path)

    def all(self) -> list[T]:
        return [self.model.model_validate(r) for r in self._read_raw()]

    def get(self, key_field: str, key: str) -> T | None:
        for row in self._read_raw():
            if row.get(key_field) == key:
                return self.model.model_validate(row)
        return None

    def put(self, item: T, key_field: str) -> T:
        with _LOCK:
            rows = self._read_raw()
            payload = json.loads(item.model_dump_json())
            key = payload.get(key_field)
            for i, row in enumerate(rows):
                if row.get(key_field) == key:
                    rows[i] = payload
                    break
            else:
                rows.append(payload)
            self._write_raw(rows)
        return item

    def append(self, item: T) -> T:
        with _LOCK:
            rows = self._read_raw()
            rows.append(json.loads(item.model_dump_json()))
            self._write_raw(rows)
        return item

    def delete(self, key_field: str, key: str) -> bool:
        with _LOCK:
            rows = self._read_raw()
            kept = [r for r in rows if r.get(key_field) != key]
            changed = len(kept) != len(rows)
            if changed:
                self._write_raw(kept)
        return changed

    def clear(self) -> None:
        with _LOCK:
            self._write_raw([])


class DynamoCollection:
    """DynamoDB-backed twin of :class:`JsonCollection`.

    Deliberately thin: Handoff's access patterns are "get one by id" and "scan
    a small table", which is all the demo and the dashboard need.
    """

    def __init__(self, table_name: str, model: type[T], key_field: str) -> None:
        import boto3

        self.model = model
        self.key_field = key_field
        self._table = boto3.resource(
            "dynamodb", region_name=config.AWS_REGION
        ).Table(table_name)

    @staticmethod
    def _clean(payload: dict) -> dict:
        """DynamoDB rejects floats; round-trip through JSON strings instead."""
        return json.loads(json.dumps(payload, default=_json_default), parse_float=str)

    def all(self) -> list[T]:
        items = self._table.scan().get("Items", [])
        return [self.model.model_validate(i) for i in items]

    def get(self, key_field: str, key: str) -> T | None:
        resp = self._table.get_item(Key={key_field: key})
        item = resp.get("Item")
        return self.model.model_validate(item) if item else None

    def put(self, item: T, key_field: str) -> T:
        self._table.put_item(Item=self._clean(json.loads(item.model_dump_json())))
        return item

    def append(self, item: T) -> T:
        return self.put(item, self.key_field)

    def delete(self, key_field: str, key: str) -> bool:
        self._table.delete_item(Key={key_field: key})
        return True

    def clear(self) -> None:  # pragma: no cover - never called against AWS
        raise NotImplementedError("refusing to truncate a DynamoDB table")


def _collection[M: BaseModel](name: str, model: type[M], key_field: str, table: str):
    if config.USE_DYNAMODB:
        return DynamoCollection(table, model, key_field)
    return JsonCollection(name, model)


# --- The five collections Handoff keeps ------------------------------------


class Store:
    """Single entry point so callers never think about which backend is live."""

    def __init__(self) -> None:
        self.workflows = _collection(
            "workflows", WorkflowConfig, "workflow_id", config.DDB_WORKFLOWS_TABLE
        )
        self.runs = _collection("runs", WorkflowRun, "run_id", config.DDB_AUDIT_TABLE)
        self.interrupts = _collection(
            "interrupts", InterruptPayload, "interrupt_id", config.DDB_INTERRUPTS_TABLE
        )
        self.audit = _collection("audit", AuditEntry, "entry_id", config.DDB_AUDIT_TABLE)
        self.preferences = _collection(
            "preferences", LearnedPreference, "preference_id", config.DDB_WORKFLOWS_TABLE
        )

    # -- workflows ---------------------------------------------------------

    def save_workflow(self, wf: WorkflowConfig) -> WorkflowConfig:
        wf.updated_at = datetime.now(wf.created_at.tzinfo)
        return self.workflows.put(wf, "workflow_id")

    def get_workflow(self, workflow_id: str) -> WorkflowConfig | None:
        return self.workflows.get("workflow_id", workflow_id)

    def list_workflows(self) -> list[WorkflowConfig]:
        return self.workflows.all()

    # -- runs --------------------------------------------------------------

    def save_run(self, run: WorkflowRun) -> WorkflowRun:
        return self.runs.put(run, "run_id")

    def get_run(self, run_id: str) -> WorkflowRun | None:
        return self.runs.get("run_id", run_id)

    def list_runs(self, workflow_id: str | None = None, limit: int = 25) -> list[WorkflowRun]:
        runs = self.runs.all()
        if workflow_id:
            runs = [r for r in runs if r.workflow_id == workflow_id]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs[:limit]

    def latest_run(self, workflow_id: str) -> WorkflowRun | None:
        runs = self.list_runs(workflow_id, limit=1)
        return runs[0] if runs else None

    # -- interrupts --------------------------------------------------------

    def save_interrupt(self, payload: InterruptPayload) -> InterruptPayload:
        return self.interrupts.put(payload, "interrupt_id")

    def get_interrupt(self, interrupt_id: str) -> InterruptPayload | None:
        return self.interrupts.get("interrupt_id", interrupt_id)

    def pending_interrupts(self) -> list[InterruptPayload]:
        pending = [i for i in self.interrupts.all() if not i.resolved]
        pending.sort(key=lambda i: i.timestamp, reverse=True)
        return pending

    def interrupts_for_run(self, run_id: str) -> list[InterruptPayload]:
        return [i for i in self.interrupts.all() if i.run_id == run_id]

    # -- audit -------------------------------------------------------------

    def write_audit(self, entry: AuditEntry) -> AuditEntry:
        return self.audit.append(entry)

    def list_audit(self, run_id: str | None = None, limit: int = 50) -> list[AuditEntry]:
        entries = self.audit.all()
        if run_id:
            entries = [e for e in entries if e.run_id == run_id]
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    # -- learned preferences ----------------------------------------------

    def save_preference(self, pref: LearnedPreference) -> LearnedPreference:
        return self.preferences.put(pref, "preference_id")

    def list_preferences(self, preference_key: str | None = None) -> list[LearnedPreference]:
        prefs = self.preferences.all()
        if preference_key:
            prefs = [p for p in prefs if p.preference_key == preference_key]
        return prefs

    # -- dashboard rollup --------------------------------------------------

    def stats(self) -> dict[str, Any]:
        runs = self.runs.all()
        audit = self.audit.all()
        return {
            "workflows": len(self.workflows.all()),
            "runs": len(runs),
            "auto_actions": sum(1 for e in audit if e.decision_by.value == "agent"),
            "human_decisions": sum(1 for e in audit if e.decision_by.value == "human"),
            "memory_applied": sum(1 for e in audit if e.decision_by.value == "memory"),
            "pending": len(self.pending_interrupts()),
            "learned_rules": len(self.preferences.all()),
            "waiting_runs": sum(
                1 for r in runs if r.status == RunStatus.WAITING_ON_HUMAN
            ),
        }


_store: Store | None = None


def get_store() -> Store:
    """Process-wide store singleton."""
    global _store
    if _store is None:
        _store = Store()
    return _store


def reset_store() -> None:
    """Drop the singleton — used by tests that repoint ``HANDOFF_STATE_DIR``."""
    global _store
    _store = None
