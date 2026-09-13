# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""workspace.yml round-trips, and the file is the truth."""

from __future__ import annotations

import yaml

from handoff.platform import workspace_yaml as wy
from handoff.platform.models import Skill, Workspace
from handoff.store import get_store


def _workspace() -> Workspace:
    store = get_store()
    ws = Workspace(name="Ops", description="team ops", color="blue")
    store.workspaces.put(ws, "workspace_id")
    return ws


def test_export_parses_back_as_valid(triage_workflow):
    ws = _workspace()
    text = wy.to_yaml(ws.workspace_id)
    parsed = wy.parse(text)
    assert parsed["valid"], parsed["errors"]
    assert parsed["payload"]["workspace"]["name"] == "Ops"
    assert any(w["workflow_id"] == triage_workflow.workflow_id for w in parsed["payload"]["workflows"])


def test_credentials_never_appear_in_the_file(triage_workflow):
    ws = _workspace()
    doc = wy.document(ws.workspace_id)
    assert "credentials" not in doc
    assert "secret" not in wy.to_yaml(ws.workspace_id)


def test_parse_reports_where_the_problem_is():
    bad = yaml.safe_dump(
        {
            "workspace": {"name": "x"},
            "workflows": [{"workflow_id": "w1", "name": "One", "trigger": {"type": "cron", "schedule": "not a cron"}}],
            "skills": [{"name": "Bad Name", "body": "x"}],
        }
    )
    parsed = wy.parse(bad)
    assert not parsed["valid"]
    assert any("workflow 'w1'" in e for e in parsed["errors"])
    assert any("lowercase-with-dashes" in e for e in parsed["errors"])


def test_apply_updates_and_removes_to_match_the_file(triage_workflow):
    store = get_store()
    ws = _workspace()
    store.skills.put(Skill(workspace_id=ws.workspace_id, name="keep-me", body="k"), "skill_id")
    store.skills.put(Skill(workspace_id=ws.workspace_id, name="drop-me", body="d"), "skill_id")

    payload = wy.parse(wy.to_yaml(ws.workspace_id))["payload"]
    payload["workspace"]["name"] = "Ops renamed"
    payload["skills"] = [s for s in payload["skills"] if s["name"] == "keep-me"]
    payload["skills"][0]["body"] = "kept, edited"
    for w in payload["workflows"]:
        if w["workflow_id"] == triage_workflow.workflow_id:
            w["confidence_threshold"] = 0.9

    counts = wy.apply(ws.workspace_id, payload)

    assert store.get_workspace(ws.workspace_id).name == "Ops renamed"
    names = {s.name: s for s in store.list_skills(ws.workspace_id) if not s.builtin}
    assert set(names) == {"keep-me"}
    assert names["keep-me"].body == "kept, edited"
    assert store.get_workflow(triage_workflow.workflow_id).confidence_threshold == 0.9
    assert counts["removed"] == 1


def test_bundle_import_creates_a_new_workspace(triage_workflow):
    ws = _workspace()
    get_store().skills.put(Skill(workspace_id=ws.workspace_id, name="sender-trust-2", body="b"), "skill_id")
    blob = wy.bundle(ws.workspace_id)

    result = wy.import_document(blob, "ops.zip")

    assert result["workspace_id"] != ws.workspace_id
    imported = get_store().get_workspace(result["workspace_id"])
    assert imported is not None and imported.name == "Ops"
    assert {s.name for s in get_store().list_skills(imported.workspace_id) if not s.builtin} == {"sender-trust-2"}


def test_default_workspace_cannot_be_removed():
    store = get_store()
    default = store.default_workspace()
    try:
        wy.remove(default.workspace_id)
    except ValueError as exc:
        assert "default" in str(exc)
    else:
        raise AssertionError("removing the default workspace should refuse")
    assert store.get_workspace(default.workspace_id) is not None
