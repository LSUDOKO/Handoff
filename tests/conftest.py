# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Test fixtures: every test runs offline, against a throwaway state dir."""

from __future__ import annotations

import os

import pytest

# Must be set before `handoff.config` is imported anywhere.
os.environ.setdefault("HANDOFF_FAKE_MODEL", "true")
os.environ.setdefault("USE_MOCK_TOOLS", "true")
os.environ.setdefault("NOTIFY_CHANNEL", "console")
os.environ.setdefault("STRANDS_OTEL_ENABLE", "false")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point every store at a fresh directory, and reset the singletons."""
    from handoff import config, store

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(config, "USE_DYNAMODB", False)
    monkeypatch.setattr(config, "USE_AGENTCORE_MEMORY", False)
    store.reset_store()
    yield tmp_path
    store.reset_store()


@pytest.fixture
def fake_model():
    from handoff.testing.fake_model import FakeModel

    return FakeModel()


@pytest.fixture
def triage_workflow():
    """The demo workflow, seeded into the isolated store."""
    from handoff.store import get_store
    from handoff.tools.workflow_store import load_example_workflows

    workflow = next(
        w for w in load_example_workflows() if w.workflow_id == "inbox-triage-morning"
    )
    get_store().save_workflow(workflow)
    return workflow
