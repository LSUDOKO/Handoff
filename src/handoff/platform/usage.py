# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""What the agents cost.

An agent that runs every morning spends money every morning. These are rough
list prices per million tokens — enough to answer "is this £2 a month or
£200", which is the question people actually have. Not a billing system.
"""

from __future__ import annotations

from typing import Any

from handoff.store import get_store

#: USD per million tokens (input, output). Approximate list prices.
#: USD per million tokens, (input, output). Keyed on the bare model id, without
#: the Bedrock inference-profile geography prefix — the same model costs the
#: same whether you reach it through "us." or "apac.", and keying on the
#: prefixed id meant every non-US run was priced at zero.
PRICES: dict[str, tuple[float, float]] = {
    "anthropic.claude-sonnet-4-5-20250929-v1:0": (3.00, 15.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "amazon.nova-pro-v1:0": (0.80, 3.20),
    "amazon.nova-lite-v1:0": (0.06, 0.24),
    "amazon.nova-micro-v1:0": (0.035, 0.14),
    "qwen/qwen3.8-27b": (0.00, 0.00),
    "openai/gpt-oss-120b": (0.00, 0.00),
    "openai/gpt-oss-20b": (0.00, 0.00),
}

#: Bedrock cross-region inference profile prefixes, stripped before pricing.
_GEO_PREFIXES = ("us.", "apac.", "eu.", "ca.", "sa.", "global.")


def bare_model_id(model: str) -> str:
    """Strip a Bedrock inference-profile geography prefix, if there is one."""
    for prefix in _GEO_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix) :]
    return model


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rate_in, rate_out = PRICES.get(bare_model_id(model), (0.0, 0.0))
    return (input_tokens / 1_000_000 * rate_in) + (output_tokens / 1_000_000 * rate_out)


def summary(workspace_id: str | None = None) -> dict[str, Any]:
    """Totals, per-model breakdown, and per-run averages for the UI."""
    store = get_store()
    records = store.list_usage(workspace_id)
    rollup = store.usage_summary(workspace_id)

    models = []
    for model, bucket in sorted(
        rollup["by_model"].items(), key=lambda kv: -(kv[1]["input"] + kv[1]["output"])
    ):
        cost = estimate_cost(model, bucket["input"], bucket["output"])
        models.append(
            {
                "model": model,
                "calls": bucket["calls"],
                "input": bucket["input"],
                "output": bucket["output"],
                "total": bucket["input"] + bucket["output"],
                "cost": cost,
                "free": model in PRICES and PRICES[model] == (0.0, 0.0),
            }
        )

    runs = {r.run_id for r in records if r.run_id}
    total_cost = sum(m["cost"] for m in models)
    total_tokens = rollup["total_input"] + rollup["total_output"]

    return {
        "total_input": rollup["total_input"],
        "total_output": rollup["total_output"],
        "total_tokens": total_tokens,
        "total_calls": rollup["total_calls"],
        "total_cost": total_cost,
        "runs": len(runs),
        "per_run_tokens": round(total_tokens / len(runs)) if runs else 0,
        "per_run_cost": total_cost / len(runs) if runs else 0.0,
        "models": models,
    }
