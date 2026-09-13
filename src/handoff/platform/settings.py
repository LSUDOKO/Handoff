# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Model settings you can change from the UI, written back to ``.env``.

A model chain is primary → fallback. The primary is what agents reason with;
the fallback serves the cheap, high-volume steps. Changing model ids applies
immediately — ``config.get_model`` reads the module attributes at call time —
while changing the provider needs a restart, because the provider decides
which client library is loaded.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from handoff import config

#: What the picker offers per provider. Ids are bare for Bedrock; the region
#: prefix is added by config.bedrock_profile.
MODEL_CATALOG: dict[str, list[dict[str, str]]] = {
    "bedrock": [
        {"id": "amazon.nova-pro-v1:0", "name": "Amazon Nova Pro", "note": "on-demand everywhere · $0.80 / $3.20"},
        {"id": "amazon.nova-lite-v1:0", "name": "Amazon Nova Lite", "note": "13× cheaper · $0.06 / $0.24"},
        {"id": "amazon.nova-micro-v1:0", "name": "Amazon Nova Micro", "note": "text only · $0.035 / $0.14"},
        {"id": "global.anthropic.claude-sonnet-4-5-20250929-v1:0", "name": "Claude Sonnet 4.5", "note": "Marketplace · $3 / $15"},
        {"id": "global.anthropic.claude-haiku-4-5-20251001-v1:0", "name": "Claude Haiku 4.5", "note": "Marketplace · $0.80 / $4"},
    ],
    "groq": [
        {"id": "qwen/qwen3.8-27b", "name": "Qwen 3.8 27B", "note": "free tier · validated"},
        {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B", "note": "free tier"},
        {"id": "openai/gpt-oss-20b", "name": "GPT-OSS 20B", "note": "free tier · fast"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5", "note": "$3 / $15"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "note": "$0.80 / $4"},
    ],
}

PROVIDER_META = {
    "bedrock": {"name": "Amazon Bedrock", "letter": "B", "key": "AWS credentials"},
    "groq": {"name": "Groq", "letter": "G", "key": "GROQ_API_KEY"},
    "anthropic": {"name": "Anthropic", "letter": "A", "key": "ANTHROPIC_API_KEY"},
}

_ENV_KEYS = {
    "bedrock": ("BEDROCK_MODEL_ID", "BEDROCK_FALLBACK_MODEL_ID"),
    "groq": ("GROQ_MODEL_ID", "GROQ_FALLBACK_MODEL_ID"),
    "anthropic": ("ANTHROPIC_MODEL_ID", "ANTHROPIC_FALLBACK_MODEL_ID"),
}


def env_path() -> Path:
    return Path(".env")


def current() -> dict[str, Any]:
    provider = config.active_provider()
    primary, fallback = {
        "bedrock": (config.BEDROCK_MODEL_ID, config.BEDROCK_FALLBACK_MODEL_ID),
        "groq": (config.GROQ_MODEL_ID, config.GROQ_FALLBACK_MODEL_ID),
        "anthropic": (config.ANTHROPIC_MODEL_ID, config.ANTHROPIC_FALLBACK_MODEL_ID),
    }.get(provider, ("scripted offline model", ""))
    return {
        "provider": provider,
        "primary": primary,
        "fallback": fallback,
        "catalog": MODEL_CATALOG,
        "providers": PROVIDER_META,
        "env_file": str(env_path().resolve()),
    }


def write_env(values: dict[str, str]) -> Path:
    """Set keys in .env in place, keeping everything else exactly as it was."""
    path = env_path()
    lines = path.read_text().splitlines() if path.exists() else []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in values:
            lines[i] = f"{m.group(1)}={values[m.group(1)]}"
            seen.add(m.group(1))
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def save(provider: str, primary: str, fallback: str) -> dict[str, Any]:
    """Persist the chain and apply what can be applied without a restart."""
    provider = provider.strip().lower()
    if provider not in _ENV_KEYS:
        raise ValueError(f"Unknown provider '{provider}'")
    key_primary, key_fallback = _ENV_KEYS[provider]
    values = {"HANDOFF_MODEL_PROVIDER": provider, key_primary: primary.strip()}
    if fallback.strip():
        values[key_fallback] = fallback.strip()
    write_env(values)

    restart_needed = provider != config.active_provider()
    if provider == "bedrock":
        config.BEDROCK_MODEL_ID = config.bedrock_profile(primary.strip())
        if fallback.strip():
            config.BEDROCK_FALLBACK_MODEL_ID = config.bedrock_profile(fallback.strip())
    elif provider == "groq":
        config.GROQ_MODEL_ID = primary.strip()
        if fallback.strip():
            config.GROQ_FALLBACK_MODEL_ID = fallback.strip()
    elif provider == "anthropic":
        config.ANTHROPIC_MODEL_ID = primary.strip()
        if fallback.strip():
            config.ANTHROPIC_FALLBACK_MODEL_ID = fallback.strip()
    if not restart_needed:
        config.MODEL_PROVIDER = provider
    return {"restart_needed": restart_needed, **current()}
