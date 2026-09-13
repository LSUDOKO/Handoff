# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff settings` and `handoff usage` — the dials, and what the agents cost.

``settings show`` is a redacted view on purpose. Which provider, which
model, where the state lives — yes. Keys — never, not even masked; that is
what ``credentials list`` is for.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("settings", help="Show or change the model chain and the confidence threshold")
    p.set_defaults(handle=handle)
    s = p.add_subparsers(dest="settings_command", metavar="<action>")

    s.add_parser("show", help="The active configuration, secrets left out (the default)")

    p_model = s.add_parser("model", help="Set the provider and model chain (written to .env)")
    p_model.add_argument("provider", help="bedrock, groq or anthropic")
    p_model.add_argument("primary", help="Model id the agents reason with")
    p_model.add_argument("fallback", nargs="?", default="", help="Cheaper model for high-volume steps")

    p_threshold = s.add_parser("threshold", help="Below this confidence the agent stops and asks you")
    p_threshold.add_argument("value", help="0 to 1, e.g. 0.7")

    p_usage = sub.add_parser("usage", help="Tokens spent and what they cost, per model")
    p_usage.add_argument("--days", type=int, default=30, help="Only the last N days")
    p_usage.set_defaults(handle=handle_usage)


def show() -> dict:
    from handoff import config, speech
    from handoff.platform import settings as settings_mod

    chain = settings_mod.current()
    summary = config.settings_summary()
    voice = speech.status()
    return {
        "provider": chain["provider"],
        "model": chain["primary"],
        "fallback_model": chain["fallback"] or summary["fallback_model_id"],
        "aws_region": summary["aws_region"],
        "confidence_threshold": summary["confidence_threshold"],
        "mock_tools": summary["use_mock_tools"],
        "dynamodb": summary["use_dynamodb"],
        "agentcore_memory": summary["use_agentcore_memory"],
        "notify_channel": summary["notify_channel"],
        "otel": summary["otel_enabled"],
        "speech_provider": voice["provider"],
        "speech_voice": voice["voice"],
        "speech_engine": voice["engine"],
        "state_dir": summary["state_dir"],
        "env_file": chain["env_file"],
    }


def handle(args: argparse.Namespace) -> int:
    from handoff import config
    from handoff.platform import settings as settings_mod

    action = args.settings_command or "show"

    if action == "show":
        data = show()
        _ui.emit(data, lambda: _ui.kv_table("Settings", data))
        return 0

    if action == "model":
        saved = settings_mod.save(args.provider, args.primary, args.fallback)
        result = {
            "provider": args.provider.strip().lower(),
            "primary": args.primary.strip(),
            "fallback": args.fallback.strip(),
            "restart_needed": saved["restart_needed"],
            "active_provider": saved["provider"],
            "env_file": saved["env_file"],
        }
        if _ui.json_mode():
            _ui.print_json(result)
        else:
            _ui.ok(f"{result['provider']}: {result['primary']}" + (f" → {result['fallback']}" if result["fallback"] else ""))
            if result["restart_needed"]:
                _ui.warn("provider changed — restart `handoff serve` for it to take effect")
        return 0

    if action == "threshold":
        try:
            value = float(args.value)
        except ValueError:
            raise ValueError(f"'{args.value}' is not a number") from None
        if not 0.0 <= value <= 1.0:
            raise ValueError("the threshold is a confidence between 0 and 1")
        settings_mod.write_env({"CONFIDENCE_THRESHOLD": f"{value:g}"})
        config.CONFIDENCE_THRESHOLD = value
        if _ui.json_mode():
            _ui.print_json({"confidence_threshold": value, "env_file": str(settings_mod.env_path().resolve())})
        else:
            _ui.ok(f"confidence threshold {value:g} — below it, the agent asks you")
        return 0

    return 2


def handle_usage(args: argparse.Namespace) -> int:
    from handoff.platform.usage import PRICES, estimate_cost
    from handoff.store import get_store

    since = datetime.now(UTC) - timedelta(days=max(args.days, 0)) if args.days else None
    records = [
        r for r in get_store().list_usage(_ui.workspace())
        if since is None or (r.at if r.at.tzinfo else r.at.replace(tzinfo=UTC)) >= since
    ]

    by_model: dict[str, dict] = {}
    for record in records:
        bucket = by_model.setdefault(record.model or "unknown", {"calls": 0, "input": 0, "output": 0})
        bucket["calls"] += 1
        bucket["input"] += record.input_tokens
        bucket["output"] += record.output_tokens
    models = [
        {
            "model": model,
            **bucket,
            "total": bucket["input"] + bucket["output"],
            "cost": estimate_cost(model, bucket["input"], bucket["output"]),
            "free": PRICES.get(model) == (0.0, 0.0),
        }
        for model, bucket in sorted(by_model.items(), key=lambda kv: -(kv[1]["input"] + kv[1]["output"]))
    ]
    runs = {r.run_id for r in records if r.run_id}
    total_tokens = sum(m["total"] for m in models)
    total_cost = sum(m["cost"] for m in models)
    data = {
        "days": args.days,
        "total_calls": len(records),
        "total_input": sum(m["input"] for m in models),
        "total_output": sum(m["output"] for m in models),
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "runs": len(runs),
        "per_run_tokens": round(total_tokens / len(runs)) if runs else 0,
        "per_run_cost": total_cost / len(runs) if runs else 0.0,
        "models": models,
    }

    def render():
        grid = _ui.table(
            f"Usage, last {args.days} days — {total_tokens:,} tokens, ${total_cost:.4f} over {len(runs)} runs",
            ["model", "calls", "in", "out", "total", "cost"],
            [
                [m["model"], m["calls"], f"{m['input']:,}", f"{m['output']:,}", f"{m['total']:,}",
                 "free" if m["free"] else f"${m['cost']:.4f}"]
                for m in models
            ],
        )
        return grid

    _ui.emit(data, render)
    return 0
