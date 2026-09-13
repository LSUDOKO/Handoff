# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Connecting Handoff to the services it acts through.

A credential is entered once in the UI, stored, and from then on the tools
that need it find it in the environment. That indirection is deliberate:
every tool in the codebase already reads its key from ``os.environ``, so
adding the UI did not mean rewriting them, and a key set in ``.env`` still
works exactly as before.

Nothing here ever returns a secret to the browser. The UI sees a masked form
and a fingerprint; the value itself only ever travels from the form, into the
store, into the process environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from handoff.platform.models import Credential, CredentialKind, CredentialStatus
from handoff.store import get_store


@dataclass(frozen=True)
class Provider:
    """One connectable service, and how to tell whether it works."""

    key: str
    label: str
    kind: CredentialKind
    env_var: str
    help_url: str = ""
    hint: str = ""
    prefix: str = ""
    #: Which doctor check proves this credential is live.
    doctor_check: str = ""
    category: str = "integration"
    actions: list[str] = field(default_factory=list)


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "groq", "Groq", CredentialKind.API_KEY, "GROQ_API_KEY",
        "https://console.groq.com/keys", "Free tier. Also powers voice.",
        "gsk_", "groq", "model",
    ),
    "anthropic": Provider(
        "anthropic", "Anthropic", CredentialKind.API_KEY, "ANTHROPIC_API_KEY",
        "https://console.anthropic.com/settings/keys", "Claude, directly.",
        "sk-ant-", "anthropic", "model",
    ),
    "gmail": Provider(
        "gmail", "Gmail", CredentialKind.OAUTH, "GMAIL_OAUTH_TOKEN",
        "https://console.cloud.google.com",
        "Needs the gmail.modify scope — read, archive, label, draft. Cannot send.",
        "ya29.", "gmail", "integration",
        ["search_threads", "archive", "create_draft", "add_label"],
    ),
    "linear": Provider(
        "linear", "Linear", CredentialKind.API_KEY, "LINEAR_API_KEY",
        "https://linear.app/settings/api",
        "Personal API key. Used raw — no 'Bearer' prefix.",
        "lin_api_", "linear", "integration",
        ["create_issue", "update_issue", "search_issues"],
    ),
    "slack": Provider(
        "slack", "Slack", CredentialKind.TOKEN, "SLACK_BOT_TOKEN",
        "https://api.slack.com/apps",
        "Bot token with chat:write. Invite the bot to the channel.",
        "xoxb-", "slack", "integration",
        ["post_message", "read_channel"],
    ),
    "slack_webhook": Provider(
        "slack_webhook", "Slack (webhook)", CredentialKind.WEBHOOK, "SLACK_WEBHOOK_URL",
        "https://api.slack.com/messaging/webhooks",
        "Faster to set up than a bot, but bound to one channel.",
        "https://hooks.slack.com/", "slack", "integration",
    ),
    "github": Provider(
        "github", "GitHub", CredentialKind.TOKEN, "GITHUB_TOKEN",
        "https://github.com/settings/tokens",
        "Fine-grained token with Issues and Pull requests access.",
        "github_pat_", "github", "integration",
        ["list_prs", "create_issue", "review_pr"],
    ),
}


def provider(key: str) -> Provider | None:
    return PROVIDERS.get(key)


# --- applying credentials to the process ------------------------------------


def apply_credentials(workspace_id: str | None = None) -> list[str]:
    """Put stored secrets into the environment the tools read.

    Called at startup and after any change. A value already present in the
    environment — from ``.env`` or the shell — wins, so a credential you set
    outside the UI is never silently overridden by a stale stored one.

    Returns the provider keys that were applied.
    """
    applied: list[str] = []
    for cred in get_store().list_credentials(workspace_id):
        spec = PROVIDERS.get(cred.provider)
        if spec is None or not cred.secret:
            continue
        if os.environ.get(spec.env_var):
            continue
        os.environ[spec.env_var] = cred.secret
        applied.append(cred.provider)
    return applied


def adopt_environment(workspace_id: str = "") -> list[Credential]:
    """Record credentials that are already in the environment.

    Someone who set up `.env` first should see their connections listed as
    connected, not be asked to paste the same keys into a form.
    """
    store = get_store()
    existing = {c.provider for c in store.list_credentials(None)}
    adopted: list[Credential] = []
    for key, spec in PROVIDERS.items():
        value = os.environ.get(spec.env_var, "")
        if not value or key in existing:
            continue
        cred = Credential(
            workspace_id=workspace_id,
            provider=key,
            label=f"{spec.label} (from environment)",
            kind=spec.kind,
            secret=value,
            status=CredentialStatus.CONNECTED,
        )
        store.credentials.put(cred, "credential_id")
        adopted.append(cred)
    return adopted


# --- CRUD -------------------------------------------------------------------


def connect(provider_key: str, secret: str, workspace_id: str = "", label: str = "") -> Credential:
    """Store a credential and verify it against the live service."""
    spec = PROVIDERS.get(provider_key)
    if spec is None:
        raise KeyError(f"Unknown provider '{provider_key}'")

    store = get_store()
    cred = store.credential_for(provider_key, None) or Credential(
        workspace_id=workspace_id, provider=provider_key, kind=spec.kind
    )
    cred.secret = secret.strip()
    cred.label = label or spec.label
    cred.workspace_id = cred.workspace_id or workspace_id
    store.credentials.put(cred, "credential_id")

    os.environ[spec.env_var] = cred.secret
    return verify(cred.credential_id)


def verify(credential_id: str) -> Credential:
    """Check a stored credential against the real service.

    Reuses the same doctor check the CLI runs, so "connected" in the UI means
    exactly what a green line in `handoff doctor` means.
    """
    store = get_store()
    cred = store.credentials.get("credential_id", credential_id)
    if cred is None:
        raise KeyError(credential_id)

    spec = PROVIDERS.get(cred.provider)
    cred.last_checked = datetime.now(UTC)

    if spec is None or not spec.doctor_check:
        cred.status = (
            CredentialStatus.CONNECTED if cred.secret else CredentialStatus.DISCONNECTED
        )
        store.credentials.put(cred, "credential_id")
        return cred

    if cred.secret:
        os.environ[spec.env_var] = cred.secret

    from handoff import doctor

    try:
        result = doctor.CHECKS[spec.doctor_check]()
    except Exception as exc:
        cred.status = CredentialStatus.NEEDS_ATTENTION
        cred.last_error = str(exc)[:200]
        store.credentials.put(cred, "credential_id")
        return cred

    if result["status"] == doctor.OK:
        cred.status = CredentialStatus.CONNECTED
        cred.last_error = ""
    elif result["status"] == doctor.WARN:
        cred.status = CredentialStatus.DISCONNECTED
        cred.last_error = result.get("detail", "")
    else:
        cred.status = CredentialStatus.NEEDS_ATTENTION
        cred.last_error = f"{result.get('detail', '')} — {result.get('fix', '')}".strip(" —")

    store.credentials.put(cred, "credential_id")
    return cred


def disconnect(credential_id: str) -> bool:
    """Forget a credential, and stop the tools from seeing it this process."""
    store = get_store()
    cred = store.credentials.get("credential_id", credential_id)
    if cred is None:
        return False
    spec = PROVIDERS.get(cred.provider)
    if spec is not None:
        os.environ.pop(spec.env_var, None)
    return store.credentials.delete("credential_id", credential_id)


def catalogue(workspace_id: str | None = None) -> list[dict[str, Any]]:
    """Every provider, with its connection state — what the UI renders."""
    store = get_store()
    by_provider = {c.provider: c for c in store.list_credentials(workspace_id)}

    rows: list[dict[str, Any]] = []
    for key, spec in PROVIDERS.items():
        cred = by_provider.get(key)
        in_env = bool(os.environ.get(spec.env_var))
        rows.append(
            {
                "provider": key,
                "label": spec.label,
                "kind": spec.kind.value,
                "category": spec.category,
                "hint": spec.hint,
                "help_url": spec.help_url,
                "prefix": spec.prefix,
                "actions": spec.actions,
                "connected": bool(cred and cred.secret) or in_env,
                "status": cred.status.value if cred else ("connected" if in_env else "disconnected"),
                "masked": cred.masked if cred else ("•" * 12 if in_env else ""),
                "fingerprint": cred.fingerprint if cred else "",
                "credential_id": cred.credential_id if cred else "",
                "last_error": cred.last_error if cred else "",
                "last_checked": cred.last_checked.isoformat() if cred and cred.last_checked else "",
                "from_env_only": in_env and not cred,
            }
        )
    rows.sort(key=lambda r: (r["category"] != "model", not r["connected"], r["label"]))
    return rows
