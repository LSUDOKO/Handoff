# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""``handoff doctor`` — does each credential actually work?

Every check makes a real call. "The variable is set" is not the same fact as
"the token is valid, unexpired, and has the scope we need", and only the second
one stops a run failing silently at 8am. Each failure says what to
do about it, because a red line that doesn't tell you the fix is just anxiety.
"""

from __future__ import annotations

import os
from typing import Any

from handoff import config

OK = "ok"
WARN = "warn"
FAIL = "fail"


def _result(name: str, status: str, detail: str, fix: str = "") -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


# --- model providers -------------------------------------------------------


def check_anthropic() -> dict[str, Any]:
    if not config.ANTHROPIC_API_KEY:
        return _result(
            "Anthropic API",
            WARN,
            "no key set",
            "Add ANTHROPIC_API_KEY to .env (console.anthropic.com → API keys)",
        )
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        client.messages.create(
            model=config.ANTHROPIC_MODEL_ID,
            max_tokens=4,
            messages=[{"role": "user", "content": "hi"}],
        )
        return _result("Anthropic API", OK, f"reachable, {config.ANTHROPIC_MODEL_ID}")
    except Exception as exc:
        return _result(
            "Anthropic API",
            FAIL,
            str(exc)[:140],
            "Check the key is valid and the model id exists for your account",
        )


def check_groq() -> dict[str, Any]:
    if not config.GROQ_API_KEY:
        return _result(
            "Groq API",
            WARN,
            "no key set",
            "Add GROQ_API_KEY to .env (console.groq.com → API keys)",
        )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.GROQ_API_KEY, base_url=config.GROQ_BASE_URL)
        response = client.chat.completions.with_raw_response.create(
            model=config.GROQ_MODEL_ID,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        headers = response.headers
        remaining = headers.get("x-ratelimit-remaining-tokens", "?")
        limit = headers.get("x-ratelimit-limit-tokens", "?")
        return _result(
            "Groq API",
            OK,
            f"{config.GROQ_MODEL_ID} — {remaining}/{limit} tokens left this minute",
        )
    except Exception as exc:
        message = str(exc)
        fix = "Check the key at console.groq.com"
        if "rate_limit" in message:
            fix = "Rate-limited. Free tier: 8K tokens/min, 200K/day per model. Wait, or switch GROQ_MODEL_ID"
        elif "model_terms_required" in message:
            fix = "Accept the model's terms once in the Groq console playground"
        return _result("Groq API", FAIL, message[:140], fix)


def check_bedrock() -> dict[str, Any]:
    try:
        import boto3

        session = boto3.Session()
        if session.get_credentials() is None:
            return _result(
                "AWS Bedrock",
                WARN,
                "no AWS credentials found",
                "Run `aws configure` (or `aws sso login`), then re-run doctor",
            )

        client = session.client("bedrock-runtime", region_name=config.AWS_REGION)
        client.converse(
            modelId=config.BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": "hi"}]}],
            inferenceConfig={"maxTokens": 4},
        )
        return _result(
            "AWS Bedrock", OK, f"{config.BEDROCK_MODEL_ID} in {config.AWS_REGION}"
        )
    except Exception as exc:
        message = str(exc)
        fix = "Check credentials and region"
        if "AccessDenied" in message or "don't have access" in message:
            fix = (
                f"Enable model access for {config.BEDROCK_MODEL_ID} in the Bedrock "
                f"console → Model access, for region {config.AWS_REGION}"
            )
        elif "ValidationException" in message:
            fix = f"{config.BEDROCK_MODEL_ID} may not exist in {config.AWS_REGION}"
        return _result("AWS Bedrock", FAIL, message[:140], fix)


def check_speech() -> dict[str, Any]:
    """One word through Polly, half a second of silence through Transcribe.

    Both are real calls in the configured region; together they cost well
    under a hundredth of a cent.
    """
    from handoff import speech

    which = speech.provider()
    if which == "browser":
        return _result(
            "Speech", WARN, "no server engine — the browser will hear and speak",
            "Configure AWS credentials (Transcribe + Polly) or a Groq key",
        )
    if which == "groq":
        audio, _, reason = speech.speak("Ready.")
        if audio:
            return _result("Speech", OK, f"Groq {config.GROQ_STT_MODEL} in, {config.GROQ_TTS_MODEL} out")
        return _result("Speech", FAIL, f"Groq Orpheus: {reason}", "Accept the model terms in the Groq console playground")
    try:
        from handoff.speech import aws

        audio = aws.synthesize("Ready.", config.POLLY_VOICE, config.POLLY_ENGINE)
        if not audio:
            return _result("Speech", FAIL, "Polly returned no audio", "Check the voice/engine pair")
        aws.transcribe_pcm(b"\x00" * 16000, 16000, config.TRANSCRIBE_LANGUAGE)
        return _result(
            "Speech", OK,
            f"Polly {config.POLLY_VOICE} ({config.POLLY_ENGINE}) + Transcribe streaming in {config.AWS_REGION}",
        )
    except Exception as exc:
        message = str(exc)
        fix = "Check the IAM user has polly:SynthesizeSpeech and transcribe:StartStreamTranscription"
        if "not supported" in message or "ValidationException" in message:
            fix = f"{config.POLLY_VOICE} may not support engine {config.POLLY_ENGINE} in {config.AWS_REGION}"
        return _result("Speech", FAIL, message[:140], fix)


# --- integrations ----------------------------------------------------------


def check_gmail() -> dict[str, Any]:
    """Gmail has no bearer token to check — its MCP server owns its own
    OAuth and refreshes itself from a file on disk. The only honest check is
    to actually start that server and ask it what it can do, which is
    exactly what a real run would do."""
    from handoff.platform.credentials import gmail_oauth_keys_path, gmail_status

    status = gmail_status()
    if not status["npx_available"]:
        return _result("Gmail", WARN, "npx not found", "Install Node.js — the Gmail MCP server needs it")
    if not status["keys_present"]:
        return _result(
            "Gmail", WARN, "not set up",
            f"Download the OAuth client JSON from Google Cloud Console and save it "
            f"as {gmail_oauth_keys_path()}, then sign in — see docs/SETUP.md, step 2",
        )
    if not status["signed_in"]:
        return _result(
            "Gmail", WARN, "OAuth client is set up, not signed in yet",
            "Connect Gmail from the Credentials page (one browser click) or run: "
            "npx -y @gongrzhe/server-gmail-autoauth-mcp auth",
        )
    try:
        from handoff.mcp.servers import get_client

        tools = get_client("gmail").list_tools_sync()
        return _result("Gmail", OK, f"signed in — {len(tools)} tools live")
    except Exception as exc:
        return _result("Gmail", FAIL, str(exc)[:140], "Try signing in again from the Credentials page")


def check_linear() -> dict[str, Any]:
    key = config.LINEAR_API_KEY
    if not key:
        return _result(
            "Linear",
            WARN,
            "no key set",
            "Linear → Settings → API → Personal API keys, then set LINEAR_API_KEY",
        )
    try:
        import httpx

        response = httpx.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": key, "Content-Type": "application/json"},
            json={"query": "{ viewer { name email } }"},
            timeout=15.0,
        )
        payload = response.json()
        viewer = (payload.get("data") or {}).get("viewer")
        if viewer:
            return _result("Linear", OK, f"{viewer.get('name')} <{viewer.get('email')}>")
        return _result(
            "Linear",
            FAIL,
            str(payload.get("errors", payload))[:140],
            "Check the key — Linear expects it raw, with no 'Bearer ' prefix",
        )
    except Exception as exc:
        return _result("Linear", FAIL, str(exc)[:140])


def check_slack() -> dict[str, Any]:
    from handoff.tools import slack

    if not slack.configured():
        return _result(
            "Slack",
            WARN,
            "neither token nor webhook set",
            "Set SLACK_BOT_TOKEN (xoxb-…) or SLACK_WEBHOOK_URL",
        )
    try:
        result = slack.check()
    except Exception as exc:
        return _result("Slack", FAIL, str(exc)[:140])

    if not result.get("ok"):
        error = result.get("error", "unknown")
        fix = "Check the token"
        if error == "invalid_auth":
            fix = "The bot token is invalid or revoked — reinstall the Slack app"
        elif error == "missing_scope":
            fix = "Add the chat:write scope to the bot, then reinstall it"
        return _result("Slack", FAIL, str(error), fix)

    if result.get("via") == "bot":
        return _result("Slack", OK, f"bot {result.get('user')} in {result.get('team')}")
    return _result("Slack", WARN, "webhook set but unverified", result.get("note", ""))


def check_github() -> dict[str, Any]:
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return _result(
            "GitHub",
            WARN,
            "no token set",
            "github.com/settings/tokens → fine-grained token, then set GITHUB_TOKEN",
        )
    try:
        import httpx

        response = httpx.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15.0,
        )
        if response.status_code == 200:
            return _result("GitHub", OK, f"@{response.json().get('login')}")
        return _result(
            "GitHub",
            FAIL,
            f"{response.status_code}: {response.text[:100]}",
            "The token may be expired or missing repo scope",
        )
    except Exception as exc:
        return _result("GitHub", FAIL, str(exc)[:140])


# --- AWS services ----------------------------------------------------------


def check_dynamodb() -> dict[str, Any]:
    if not config.USE_DYNAMODB:
        return _result("DynamoDB", WARN, "off — using local JSON state", "")
    try:
        import boto3

        client = boto3.client("dynamodb", region_name=config.AWS_REGION)
        described = client.describe_table(TableName=config.DDB_TABLE)["Table"]
        keys = "+".join(k["AttributeName"] for k in described["KeySchema"])
        if keys != "pk+sk":
            return _result(
                "DynamoDB",
                FAIL,
                f"{config.DDB_TABLE} is keyed on {keys}, not pk+sk",
                "Old single-key layout. Run: python infra/dynamodb_setup.py --delete "
                "&& python infra/dynamodb_setup.py",
            )
        return _result(
            "DynamoDB", OK, f"{config.DDB_TABLE} ({described['ItemCount']} items)"
        )
    except Exception as exc:
        return _result(
            "DynamoDB", FAIL, str(exc)[:140], "Run: python infra/dynamodb_setup.py"
        )


def check_agentcore_memory() -> dict[str, Any]:
    if not config.USE_AGENTCORE_MEMORY:
        return _result("AgentCore Memory", WARN, "off — using local preferences", "")
    try:
        import boto3

        client = boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)
        memory = client.get_memory(memoryId=config.AGENTCORE_MEMORY_ID)["memory"]
        return _result("AgentCore Memory", OK, f"{memory['id']} ({memory['status']})")
    except Exception as exc:
        return _result(
            "AgentCore Memory", FAIL, str(exc)[:140], "Run: python infra/memory_setup.py"
        )


# --- runner ----------------------------------------------------------------

CHECKS = {
    "groq": check_groq,
    "anthropic": check_anthropic,
    "bedrock": check_bedrock,
    "speech": check_speech,
    "gmail": check_gmail,
    "linear": check_linear,
    "slack": check_slack,
    "github": check_github,
    "dynamodb": check_dynamodb,
    "memory": check_agentcore_memory,
}

GLYPH = {OK: "PASS", WARN: "SKIP", FAIL: "FAIL"}


def run(only: list[str] | None = None) -> list[dict[str, Any]]:
    names = only or list(CHECKS)
    return [CHECKS[n]() for n in names if n in CHECKS]


def report(results: list[dict[str, Any]]) -> int:
    """Print the results. Returns a shell exit code."""
    print(f"\nHandoff doctor — provider: {config.active_provider()}\n")
    width = max(len(r["name"]) for r in results)

    for result in results:
        print(f"  {GLYPH[result['status']]}  {result['name']:<{width}}  {result['detail']}")
        if result["fix"] and result["status"] != OK:
            print(f"        {' ' * width}  → {result['fix']}")

    failures = [r for r in results if r["status"] == FAIL]
    passes = [r for r in results if r["status"] == OK]

    print(f"\n  {len(passes)} working, {len(failures)} broken, "
          f"{len(results) - len(passes) - len(failures)} not configured\n")

    model_checks = [r for r in results if r["name"] in ("Groq API", "Anthropic API", "AWS Bedrock")]
    if model_checks and not any(r["status"] == OK for r in model_checks):
        print("  No working model provider. Handoff can only run with")
        print("  HANDOFF_FAKE_MODEL=true until you fix that.\n")

    return 1 if failures else 0
