# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Model providers that need more than Strands' defaults.

Open-weight models on OpenAI-compatible endpoints (Groq, Together, Fireworks)
occasionally emit a tool call whose JSON doesn't parse — a stray quote after a
number, an unescaped newline. The endpoint rejects the whole response with
``tool_use_failed`` and Strands, reasonably, treats a 400 as fatal.

But the model's *judgement* in that call was almost always right; only the
serialisation slipped. Groq even hands the broken text back in the error as
``failed_generation``. So rather than re-sample — which costs a full context
of tokens and, at low temperature, tends to reproduce the same slip — this
provider repairs the JSON it was given and carries on as if the model had
emitted it cleanly. Re-sampling is the fallback, not the first move.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from strands.models.openai import OpenAIModel

logger = logging.getLogger(__name__)

#: How many times to re-sample if a rejected generation can't be repaired.
TOOL_JSON_RETRIES = 2

_FAILED_GEN = re.compile(r"'failed_generation':\s*'(.*?)'\s*}\s*}\s*$", re.S)


def _is_tool_json_failure(exc: BaseException) -> bool:
    text = str(exc)
    return "tool_use_failed" in text or "Failed to parse tool call arguments" in text


def extract_failed_generation(exc: BaseException) -> str | None:
    """Pull the model's rejected text out of the endpoint's error, if present."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("failed_generation"):
            return str(err["failed_generation"])
    match = _FAILED_GEN.search(str(exc))
    return match.group(1) if match else None


def repair_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Turn a broken ``{"name": ..., "arguments": ...}`` string into a call.

    Tries strict JSON first, then a tolerant parser. Returns ``None`` if what
    comes back isn't recognisably a tool call — a repair that invents a
    different tool name or drops required fields is worse than a clean retry.
    """
    candidates: list[Any] = []
    try:
        candidates.append(json.loads(text))
    except json.JSONDecodeError:
        try:
            from json_repair import loads as tolerant_loads

            candidates.append(tolerant_loads(text))
        except Exception:
            return None

    for parsed in candidates:
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name")
        arguments = parsed.get("arguments", parsed.get("parameters"))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                try:
                    from json_repair import loads as tolerant_loads

                    arguments = tolerant_loads(arguments)
                except Exception:
                    return None
        if isinstance(name, str) and name and isinstance(arguments, dict):
            return name, arguments
    return None


def synthesize_tool_use_events(name: str, arguments: dict[str, Any]):
    """The event sequence Strands expects for a single tool-use response."""
    tool_use_id = f"repaired_{uuid.uuid4().hex[:12]}"
    yield {"messageStart": {"role": "assistant"}}
    yield {
        "contentBlockStart": {
            "start": {"toolUse": {"toolUseId": tool_use_id, "name": name}}
        }
    }
    yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(arguments)}}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "tool_use"}}
    yield {
        "metadata": {
            "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
            "metrics": {"latencyMs": 0},
        }
    }


class ResilientOpenAIModel(OpenAIModel):
    """``OpenAIModel`` that survives an endpoint rejecting tool-call JSON.

    On ``tool_use_failed``: repair the rejected generation and emit it as the
    response. If it can't be repaired, re-sample a couple of times. Only safe
    in non-streaming mode — with ``stream=False`` nothing is yielded until the
    whole response has arrived, so a failure means the agent saw nothing yet.
    In streaming mode partial events may already be out, so this stays out of
    the way and lets the error propagate.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: Repairs performed this process — surfaced in the UI's trace so it's
        #: visible when a run leaned on this rather than the model being clean.
        self.repairs: list[dict[str, str]] = []

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[dict[str, Any], None]:
        streaming = bool(self.config.get("stream", True))
        attempts = 1 if streaming else TOOL_JSON_RETRIES + 1

        for attempt in range(1, attempts + 1):
            yielded = False
            try:
                async for event in super().stream(*args, **kwargs):
                    yielded = True
                    yield event
                return
            except Exception as exc:
                if yielded or streaming or not _is_tool_json_failure(exc):
                    raise

                broken = extract_failed_generation(exc)
                repaired = repair_tool_call(broken) if broken else None
                if repaired is not None:
                    name, arguments = repaired
                    self.repairs.append({"tool": name, "raw": (broken or "")[:200]})
                    logger.warning(
                        "endpoint rejected tool-call JSON for %s; repaired locally", name
                    )
                    try:
                        from handoff import events
                        from handoff.runtime import current_run

                        ctx = current_run()
                        if ctx is not None:
                            events.emit(
                                ctx.run_id, "repaired",
                                f"The model's {name} call came back malformed; repaired it rather than re-asking",
                                tool=name,
                            )
                    except Exception:
                        pass
                    for event in synthesize_tool_use_events(name, arguments):
                        yield event
                    return

                if attempt == attempts:
                    raise
                logger.warning(
                    "tool-call JSON rejected and not repairable (attempt %d/%d); re-sampling",
                    attempt,
                    attempts,
                )
