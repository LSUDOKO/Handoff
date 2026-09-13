# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The ``handoff`` command line, driven in-process against the isolated store.

Every command that has a ``--json`` form is checked through it, because that
is the contract scripts depend on; the human forms are checked for the one
or two facts a person would look for.
"""

from __future__ import annotations

import json
import struct

import pytest

from handoff.cli import build_parser, main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, out


@pytest.fixture
def no_mcp(monkeypatch):
    """Chat turns without spawning MCP servers; the test is about the CLI."""
    from handoff.chat import service

    monkeypatch.setattr(service, "_ready_mcp_tools", lambda: [])


# --- C1: package, read-only commands ----------------------------------------


def test_workflows_list_json(capsys, triage_workflow):
    code, out = run(capsys, "--json", "workflows", "list")
    assert code == 0
    rows = json.loads(out)
    assert any(r["workflow_id"] == triage_workflow.workflow_id for r in rows)


def test_workflows_show_human(capsys, triage_workflow):
    code, out = run(capsys, "workflows", "show", triage_workflow.workflow_id)
    assert code == 0 and triage_workflow.name in out and triage_workflow.trigger.schedule in out


def test_unknown_workflow_is_exit_2(capsys):
    code, out = run(capsys, "workflows", "show", "nope")
    assert code == 2


def test_settings_show_never_prints_secrets(capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_secret_value")
    code, out = run(capsys, "settings", "show")
    assert code == 0
    assert "gsk_supersecret" not in out


def test_version(capsys):
    code, out = run(capsys, "version")
    assert code == 0 and "handoff" in out.lower()


def test_help_lists_every_group():
    text = build_parser().format_help()
    for name in (
        "workflows", "runs", "inspect", "pending", "activity", "settings", "usage",
        "workspace", "doctor", "serve", "desktop", "version", "ask", "chat", "build",
        "run", "decide", "agents", "mcp", "skills", "memory", "credentials",
        "schedules", "scheduler", "say", "listen", "talk", "share", "docs", "deploy",
        "completion",
    ):
        assert f"{name}" in text, name


def test_workflows_bare_lists_like_the_old_cli(capsys, triage_workflow):
    code, out = run(capsys, "workflows")
    assert code == 0 and triage_workflow.workflow_id in out


def test_workflows_disable_enable_delete(capsys, triage_workflow):
    wid = triage_workflow.workflow_id
    assert run(capsys, "workflows", "disable", wid)[0] == 0
    code, out = run(capsys, "--json", "workflows", "show", wid)
    assert json.loads(out)["status"] == "paused"
    assert run(capsys, "workflows", "enable", wid)[0] == 0
    code, out = run(capsys, "--json", "workflows", "show", wid)
    assert json.loads(out)["status"] == "active"
    # Shipped templates are re-seeded on every start, so delete is tested on
    # a workflow of our own.
    from handoff.store import get_store

    mine = triage_workflow.model_copy(update={"workflow_id": "my-own-triage", "name": "Mine"})
    get_store().save_workflow(mine)
    code, out = run(capsys, "--json", "workflows", "delete", "my-own-triage")
    assert code == 0 and json.loads(out)["shipped_template"] is False
    assert run(capsys, "workflows", "show", "my-own-triage")[0] == 2
    code, out = run(capsys, "--json", "workflows", "delete", wid)
    assert code == 0 and json.loads(out)["shipped_template"] is True


def test_workflows_export_writes_json(capsys, tmp_path, triage_workflow):
    target = tmp_path / "wf.json"
    code, out = run(capsys, "workflows", "export", triage_workflow.workflow_id, str(target))
    assert code == 0
    assert json.loads(target.read_text())["workflow_id"] == triage_workflow.workflow_id


def test_runs_inspect_pending_activity_after_a_run(capsys, triage_workflow):
    code, out = run(capsys, "--json", "run", triage_workflow.workflow_id)
    assert code == 0
    outcome = json.loads(out)
    assert outcome["status"] == "waiting_on_human"

    code, out = run(capsys, "--json", "runs", "--limit", "5")
    assert code == 0
    runs_ = json.loads(out)
    assert runs_ and runs_[0]["run_id"] == outcome["run_id"]

    code, out = run(capsys, "inspect", outcome["run_id"])
    assert code == 0 and "submit_action" in out

    code, out = run(capsys, "--json", "pending")
    assert code == 0 and len(json.loads(out)) == 3

    code, out = run(capsys, "--json", "activity", "--limit", "3")
    assert code == 0 and len(json.loads(out)) == 3


def test_inspect_unknown_run_is_exit_2(capsys):
    assert run(capsys, "inspect", "run_nope")[0] == 2


def test_usage_json(capsys):
    code, out = run(capsys, "--json", "usage", "--days", "7")
    assert code == 0
    data = json.loads(out)
    assert "total_tokens" in data and isinstance(data["models"], list)


def test_workspace_list_and_round_trip(capsys, tmp_path, triage_workflow):
    code, out = run(capsys, "--json", "workspace", "list")
    assert code == 0
    spaces = json.loads(out)
    assert any(w["is_default"] for w in spaces)

    target = tmp_path / "workspace.yml"
    assert run(capsys, "workspace", "export", str(target))[0] == 0
    assert "inbox-triage-morning" in target.read_text()

    code, out = run(capsys, "--json", "workspace", "import", str(target))
    assert code == 0
    imported = json.loads(out)
    assert imported["workflows"] >= 1

    code, out = run(capsys, "workspace", "remove", imported["workspace_id"])
    assert code == 0
    code, out = run(capsys, "--json", "workspace", "list")
    assert all(w["workspace_id"] != imported["workspace_id"] for w in json.loads(out))


def test_unknown_workspace_flag_is_exit_2(capsys):
    assert run(capsys, "--workspace", "ws_nope", "agents", "list")[0] == 2


# --- C2: chat, ask, build, run --watch, decide ------------------------------


def test_ask_streams_on_fake_model(capsys, no_mcp):
    code, out = run(capsys, "ask", "what is waiting on me")
    assert code == 0 and out.strip()


def test_ask_json_prints_the_done_event(capsys, no_mcp):
    code, out = run(capsys, "--json", "ask", "what is waiting on me")
    assert code == 0
    done = json.loads(out)
    assert done["kind"] == "done"


def test_run_watch_prints_events(capsys, triage_workflow):
    code, out = run(capsys, "run", triage_workflow.workflow_id, "--watch")
    assert code == 0 and "started" in out and ("completed" in out or "asked" in out)


def test_run_unknown_workflow_is_exit_2(capsys):
    assert run(capsys, "run", "nope")[0] == 2


def test_build_activates_the_config(capsys, no_mcp):
    from handoff.store import get_store

    code, out = run(capsys, "build", "triage my inbox every weekday morning", "--activate")
    assert code == 0
    saved = get_store().get_workflow("inbox-triage-morning")
    assert saved is not None and saved.status.value == "active"


def test_decide_all_answers_every_pending(capsys, triage_workflow):
    from handoff.store import get_store

    run(capsys, "--json", "run", triage_workflow.workflow_id)
    assert len(get_store().pending_interrupts()) == 3
    code, out = run(capsys, "decide", "--all", "archive", "--note", "cold outreach")
    assert code == 0
    assert get_store().pending_interrupts() == []


def test_decide_unknown_is_exit_2(capsys):
    assert run(capsys, "decide", "int_nope", "archive")[0] == 2


# --- C3: agents, mcp, skills, memory, credentials, schedules, speech, ops ---


def test_agents_list_json_has_the_builtins(capsys):
    code, out = run(capsys, "--json", "agents", "list")
    assert code == 0
    names = {a["name"] for a in json.loads(out)}
    assert {"Inbox Executor", "Digest Writer"} <= names


def test_agents_show_by_name(capsys):
    code, out = run(capsys, "agents", "show", "Digest Writer")
    assert code == 0 and "read_audit_log" in out


def test_mcp_list_json_includes_gmail(capsys):
    code, out = run(capsys, "--json", "mcp", "list")
    assert code == 0
    assert any(row["name"] == "gmail" for row in json.loads(out))


def test_mcp_add_and_remove(capsys):
    code, out = run(
        capsys, "--json", "mcp", "add", "echo", "--command", "echo", "--args", "hello", "world",
        "--description", "test server",
    )
    assert code == 0
    row = json.loads(out)
    assert row["args"] == ["hello", "world"] and row["transport"] == "stdio"
    assert run(capsys, "mcp", "remove", row["server_id"])[0] == 0
    assert run(capsys, "mcp", "remove", row["server_id"])[0] == 2


def test_skills_list_json_non_empty_and_toggle(capsys):
    code, out = run(capsys, "--json", "skills", "list")
    assert code == 0
    rows = json.loads(out)
    assert rows
    skill = rows[0]
    assert run(capsys, "skills", "disable", skill["skill_id"])[0] == 0
    code, out = run(capsys, "--json", "skills", "show", skill["skill_id"])
    assert json.loads(out)["enabled"] is False
    assert run(capsys, "skills", "enable", skill["name"])[0] == 0


def test_skills_import_markdown(capsys, tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text("---\nname: quiet-hours\ndescription: When not to ping.\n---\n\nNever notify after 22:00.\n")
    code, out = run(capsys, "--json", "skills", "import", str(doc))
    assert code == 0
    assert json.loads(out)[0]["name"] == "quiet-hours"


def test_memory_rules_json_returns_empty_list(capsys):
    code, out = run(capsys, "--json", "memory", "rules")
    assert code == 0 and json.loads(out) == []


def test_memory_add_and_forget(capsys):
    code, out = run(capsys, "--json", "memory", "add", "Bob is on the platform team")
    assert code == 0
    entry = json.loads(out)
    code, out = run(capsys, "--json", "memory", "entries")
    assert any(e["entry_id"] == entry["entry_id"] for e in json.loads(out))
    assert run(capsys, "memory", "forget", entry["entry_id"])[0] == 0
    assert run(capsys, "memory", "forget", entry["entry_id"])[0] == 2


def test_credentials_list_masks_values(capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_secret_value")
    code, out = run(capsys, "--json", "credentials", "list")
    assert code == 0
    assert '"secret"' not in out
    assert "gsk_test_secret_value" not in out
    rows = json.loads(out)
    groq = next(r for r in rows if r["provider"] == "groq")
    assert groq["connected"] and "•" in groq["masked"]

    code, out = run(capsys, "credentials", "list")
    assert code == 0 and "gsk_test_secret_value" not in out


def test_credentials_set_reads_from_env_without_echo(capsys, monkeypatch):
    from handoff.platform import credentials as creds
    from handoff.platform.models import CredentialStatus

    def offline_verify(credential_id):
        store = creds.get_store()
        cred = store.credentials.get("credential_id", credential_id)
        cred.status = CredentialStatus.CONNECTED
        store.credentials.put(cred, "credential_id")
        return cred

    monkeypatch.setenv("MY_LINEAR", "lin_api_abcdefghijklmnop")
    monkeypatch.setattr(creds, "verify", offline_verify)
    code, out = run(capsys, "credentials", "set", "linear", "--from-env", "MY_LINEAR")
    assert code == 0
    assert "lin_api_abcdefghijklmnop" not in out
    assert creds.get_store().credential_for("linear") is not None


def test_schedules_list_json_is_list(capsys, triage_workflow):
    code, out = run(capsys, "--json", "schedules", "list")
    assert code == 0 and isinstance(json.loads(out), list)


def test_schedules_toggle(capsys, triage_workflow):
    code, out = run(capsys, "--json", "schedules", "list")
    rows = json.loads(out)
    assert rows, "the cron workflow should have a schedule"
    before = rows[0]["enabled"]
    code, out = run(capsys, "--json", "schedules", "toggle", rows[0]["schedule_id"])
    assert code == 0 and json.loads(out)["enabled"] is (not before)


def test_settings_threshold_writes_env(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(capsys, "settings", "threshold", "0.8")[0] == 0
    assert "CONFIDENCE_THRESHOLD=0.8" in (tmp_path / ".env").read_text()
    assert run(capsys, "settings", "threshold", "1.5")[0] == 2


def test_settings_model_writes_env(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out = run(capsys, "--json", "settings", "model", "groq", "openai/gpt-oss-20b")
    assert code == 0 and json.loads(out)["primary"] == "openai/gpt-oss-20b"
    assert "GROQ_MODEL_ID=openai/gpt-oss-20b" in (tmp_path / ".env").read_text()
    assert run(capsys, "settings", "model", "nope", "x")[0] == 2


def test_say_without_a_server_engine_is_exit_1(capsys, monkeypatch):
    from handoff import config

    monkeypatch.setattr(config, "SPEECH_PROVIDER", "browser")
    code, out = run(capsys, "say", "hello")
    assert code == 1


def test_say_writes_the_file(capsys, tmp_path, monkeypatch):
    from handoff import speech

    monkeypatch.setattr(speech, "speak", lambda text, voice=None: (b"ID3fake", "audio/mpeg", ""))
    target = tmp_path / "hi.mp3"
    code, out = run(capsys, "say", "hello", "--out", str(target))
    assert code == 0 and target.read_bytes() == b"ID3fake"


def test_listen_transcribes_a_wav(capsys, tmp_path, monkeypatch):
    from handoff import speech
    from handoff.speech import wav

    seen = {}

    def fake_transcribe(audio, filename="speech.wav", language=None):
        seen["wav"] = wav.is_wav(audio)
        return {"text": "archive it"}

    monkeypatch.setattr(speech, "transcribe", fake_transcribe)
    clip = tmp_path / "clip.wav"
    clip.write_bytes(wav.pcm_to_wav(struct.pack("<16h", *([0] * 16))))
    code, out = run(capsys, "listen", str(clip))
    assert code == 0 and "archive it" in out and seen["wav"]


def test_listen_missing_file_is_exit_2(capsys, tmp_path):
    assert run(capsys, "listen", str(tmp_path / "nope.wav"))[0] == 2


def test_share_without_cloudflared_prints_install_hint(capsys, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    code, out = run(capsys, "share")
    assert code == 1
    assert "cloudflare-one/connections/connect-networks/downloads" in out


def test_completion_scripts_list_the_commands(capsys):
    for shell in ("bash", "zsh", "fish"):
        code, out = run(capsys, "completion", shell)
        assert code == 0 and "workflows" in out and "credentials" in out


def test_doctor_json_reports_each_check(capsys):
    code, out = run(capsys, "--json", "doctor", "dynamodb", "memory")
    assert code == 0
    names = {r["name"] for r in json.loads(out)}
    assert names == {"DynamoDB", "AgentCore Memory"}


def test_state_dir_flag_repoints_the_store(capsys, tmp_path):
    other = tmp_path / "elsewhere"
    code, out = run(capsys, "--state-dir", str(other), "--json", "workflows", "list")
    assert code == 0
    assert (other / "workflows.json").exists()


def test_state_dir_means_local_storage(tmp_path, monkeypatch, capsys):
    """--state-dir must never let a scratch run reach the live table."""
    from handoff import config

    monkeypatch.setenv("USE_DYNAMODB", "true")
    monkeypatch.setenv("USE_AGENTCORE_MEMORY", "true")
    code = main(["--state-dir", str(tmp_path / "scratch"), "version"])
    assert code == 0
    assert config.USE_DYNAMODB is False and config.USE_AGENTCORE_MEMORY is False
    import os

    assert os.environ["USE_DYNAMODB"] == "false"
