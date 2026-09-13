# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Handoff configuration — every setting is read from the environment.

Nothing in here reaches out to AWS at import time. ``get_model()`` is the only
function that constructs a Bedrock client, and it is called lazily so the test
suite and the local runner work on a machine with no AWS credentials at all.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -----------------------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent

#: Workflow templates ship inside the package, so `pip install handoff` has
#: them without a source checkout.
WORKFLOWS_DIR = PACKAGE_ROOT / "workflows"


def _default_state_dir() -> Path:
    """Where runs, audit entries and learned rules live.

    In a source checkout, beside the code — a judge who clones the repo can
    see and delete it. Installed as a package, under the user's home, because
    writing into site-packages would be wrong.
    """
    if (PROJECT_ROOT / "pyproject.toml").exists():
        return PROJECT_ROOT / ".handoff-state"
    return Path.home() / ".handoff" / "state"


STATE_DIR = Path(os.getenv("HANDOFF_STATE_DIR") or _default_state_dir())

# --- AWS -------------------------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

# --- Model provider --------------------------------------------------------
#: "bedrock" | "anthropic" | "groq" | "fake".
#:
#: Bedrock is what the AgentCore deployment runs on. Anthropic and Groq exist
#: because each needs one API key rather than an AWS account with model access
#: approved per-region — useful when you want real reasoning today and the
#: cloud deployment later. All run identical agent code; only the model object
#: differs. Groq is OpenAI-compatible, so it rides Strands' OpenAI provider.
MODEL_PROVIDER = os.getenv("HANDOFF_MODEL_PROVIDER", "bedrock").lower()

# --- Bedrock models --------------------------------------------------------
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
BEDROCK_FALLBACK_MODEL_ID = os.getenv(
    "BEDROCK_FALLBACK_MODEL_ID", "us.amazon.nova-pro-v1:0"
)

# --- Anthropic models ------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL_ID = os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-5-20250929")
ANTHROPIC_FALLBACK_MODEL_ID = os.getenv(
    "ANTHROPIC_FALLBACK_MODEL_ID", "claude-haiku-4-5-20251001"
)
# --- Groq models -----------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "qwen/qwen3.8-27b")
GROQ_FALLBACK_MODEL_ID = os.getenv("GROQ_FALLBACK_MODEL_ID", "openai/gpt-oss-20b")
#: Groq also serves speech models, which is what makes voice real rather than
#: a browser-only trick: Whisper for hearing you, Orpheus for talking back.
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_TTS_MODEL = os.getenv("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")
GROQ_TTS_VOICE = os.getenv("GROQ_TTS_VOICE", "troy")
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")
#: Groq's streaming pipeline rejects tool calls whose JSON it can't parse
#: mid-stream ("Failed to parse tool call arguments as JSON"), which
#: open-weight models trip over on long string arguments. Non-streaming
#: returns the whole call at once and sidesteps it. Streaming gains nothing
#: for a background job nobody is watching type.
GROQ_STREAM = os.getenv("GROQ_STREAM", "false").lower() == "true"
#: Groq's free tier caps output tokens per minute at 1,000 on some models and
#: rejects any request whose max_tokens implies more. A tool call is well
#: under 200 tokens; 700 leaves room for a sentence of reasoning.
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "700"))

#: The executor reasons over a whole inbox in one turn, so give it room.
MODEL_MAX_TOKENS = int(os.getenv("HANDOFF_MODEL_MAX_TOKENS", "8192"))

# --- DynamoDB --------------------------------------------------------------
DDB_WORKFLOWS_TABLE = os.getenv("DDB_WORKFLOWS_TABLE", "handoff_workflows")
DDB_AUDIT_TABLE = os.getenv("DDB_AUDIT_TABLE", "handoff_audit")
DDB_INTERRUPTS_TABLE = os.getenv("DDB_INTERRUPTS_TABLE", "handoff_interrupts")

#: When false (the default) the stores persist to STATE_DIR as JSON instead of
#: DynamoDB. This is what makes the whole project runnable with zero AWS setup.
USE_DYNAMODB = os.getenv("USE_DYNAMODB", "false").lower() == "true"

# --- AgentCore Memory ------------------------------------------------------
AGENTCORE_MEMORY_ID = os.getenv("AGENTCORE_MEMORY_ID", "")
USE_AGENTCORE_MEMORY = (
    os.getenv("USE_AGENTCORE_MEMORY", "false").lower() == "true"
    and bool(AGENTCORE_MEMORY_ID)
)

# --- Notifications ---------------------------------------------------------
NOTIFY_CHANNEL = os.getenv("NOTIFY_CHANNEL", "console")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN", "")

# --- UI --------------------------------------------------------------------
UI_BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:8000")
UI_PORT = int(os.getenv("UI_PORT", "8000"))

# --- The HITL gate ---------------------------------------------------------
#: Below this confidence the agent stops and asks a human. This single number
#: is the dial between "autonomous" and "annoying".
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))

# --- Observability ---------------------------------------------------------
OTEL_ENABLED = os.getenv("STRANDS_OTEL_ENABLE", "false").lower() == "true"
OTEL_EXPORTER = os.getenv("STRANDS_OTEL_EXPORTER", "console")

# --- Tools / MCP -----------------------------------------------------------
USE_MOCK_TOOLS = os.getenv("USE_MOCK_TOOLS", "true").lower() == "true"
GMAIL_OAUTH_TOKEN = os.getenv("GMAIL_OAUTH_TOKEN", "")
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")

#: Set by scripts/run_local.py and the test suite to avoid any Bedrock call.
USE_FAKE_MODEL = os.getenv("HANDOFF_FAKE_MODEL", "false").lower() == "true"


def ensure_state_dir() -> Path:
    """Create (once) and return the local state directory."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def configure_observability() -> None:
    """Turn on Strands' OpenTelemetry tracing if the env asks for it.

    Must run before the first Agent is constructed, which is why every entry
    point (app.py, ui/server.py, scripts/run_local.py) calls it early.
    """
    if not OTEL_ENABLED:
        return
    os.environ.setdefault("STRANDS_OTEL_ENABLE", "true")
    os.environ.setdefault("STRANDS_OTEL_EXPORTER", OTEL_EXPORTER)
    try:
        from strands.telemetry import StrandsTelemetry

        telemetry = StrandsTelemetry()
        if OTEL_EXPORTER == "console":
            telemetry.setup_console_exporter()
        else:
            telemetry.setup_otlp_exporter()
    except Exception as exc:  # pragma: no cover - telemetry is best-effort
        print(f"[handoff] observability disabled: {exc}")


def active_provider() -> str:
    """Which model provider will actually be used, given the environment.

    Resolved rather than read straight from the env, because asking for
    Anthropic without a key, or Bedrock without credentials, should produce a
    clear message here instead of an opaque failure three frames into a run.
    """
    if USE_FAKE_MODEL or MODEL_PROVIDER == "fake":
        return "fake"
    if MODEL_PROVIDER == "anthropic":
        return "anthropic"
    if MODEL_PROVIDER == "groq":
        return "groq"
    return "bedrock"


@lru_cache(maxsize=2)
def get_model(fallback: bool = False):
    """Return the model every agent in a run shares.

    Cached: constructing either provider opens an HTTP client, and one run can
    build three agents.
    """
    provider = active_provider()

    if provider == "fake":
        from handoff.testing.fake_model import FakeModel

        return FakeModel()

    if provider == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "HANDOFF_MODEL_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.\n"
                "Add it to .env, or switch to HANDOFF_MODEL_PROVIDER=bedrock."
            )
        from strands.models.anthropic import AnthropicModel

        model_id = ANTHROPIC_FALLBACK_MODEL_ID if fallback else ANTHROPIC_MODEL_ID
        return AnthropicModel(
            client_args={"api_key": ANTHROPIC_API_KEY},
            model_id=model_id,
            max_tokens=MODEL_MAX_TOKENS,
        )

    if provider == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError(
                "HANDOFF_MODEL_PROVIDER=groq but GROQ_API_KEY is not set.\n"
                "Add it to .env (console.groq.com → API keys)."
            )
        import logging

        from handoff.providers import ResilientOpenAIModel

        # gpt-oss returns reasoning content on every turn; the OpenAI provider
        # drops it in multi-turn and logs a warning each time. That's expected
        # here, not a problem — silence it so real errors stay visible.
        logging.getLogger("strands.models.openai").setLevel(logging.ERROR)

        model_id = GROQ_FALLBACK_MODEL_ID if fallback else GROQ_MODEL_ID
        return ResilientOpenAIModel(
            client_args={"api_key": GROQ_API_KEY, "base_url": GROQ_BASE_URL},
            model_id=model_id,
            stream=GROQ_STREAM,
            params={
                "max_tokens": GROQ_MAX_TOKENS,
                "temperature": 0.2,
                # Tool-calling loops don't benefit from long deliberation, and
                # the executor makes a dozen calls per run. Keep it snappy.
                "reasoning_effort": GROQ_REASONING_EFFORT,
                # One tool call per turn. Eight parallel calls with long
                # string arguments is where open-weight models emit JSON the
                # server can't parse. Groq is fast enough that sixteen short
                # turns beat one broken one.
                "parallel_tool_calls": False,
            },
        )

    from strands.models.bedrock import BedrockModel

    model_id = BEDROCK_FALLBACK_MODEL_ID if fallback else BEDROCK_MODEL_ID
    return BedrockModel(model_id=model_id, region_name=AWS_REGION)


def get_fallback_model():
    """The cheaper model, for high-volume or low-stakes steps."""
    return get_model(fallback=True)


def active_model_id() -> str:
    """The model id in use, for display."""
    return {
        "fake": "scripted offline model",
        "anthropic": ANTHROPIC_MODEL_ID,
        "groq": GROQ_MODEL_ID,
        "bedrock": BEDROCK_MODEL_ID,
    }[active_provider()]


def settings_summary() -> dict:
    """A redacted view of the active configuration, for the UI's status panel."""
    return {
        "aws_region": AWS_REGION,
        "provider": active_provider(),
        "model_id": active_model_id(),
        "fallback_model_id": BEDROCK_FALLBACK_MODEL_ID,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "use_mock_tools": USE_MOCK_TOOLS,
        "use_dynamodb": USE_DYNAMODB,
        "use_agentcore_memory": USE_AGENTCORE_MEMORY,
        "notify_channel": NOTIFY_CHANNEL,
        "otel_enabled": OTEL_ENABLED,
        "otel_exporter": OTEL_EXPORTER,
        "state_dir": str(STATE_DIR),
    }
