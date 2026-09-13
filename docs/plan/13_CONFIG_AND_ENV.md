# Handoff — Configuration & Environment Reference

## config.py

```python
"""Handoff configuration — all settings loaded from environment."""

import os
from dotenv import load_dotenv
from strands.models.bedrock import BedrockModel

load_dotenv()

# --- AWS ---
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# --- Bedrock Models ---
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
BEDROCK_FALLBACK_MODEL_ID = os.getenv(
    "BEDROCK_FALLBACK_MODEL_ID",
    "us.amazon.nova-pro-v1:0"
)

# --- DynamoDB ---
DDB_WORKFLOWS_TABLE = os.getenv("DDB_WORKFLOWS_TABLE", "handoff_workflows")
DDB_AUDIT_TABLE = os.getenv("DDB_AUDIT_TABLE", "handoff_audit")
DDB_INTERRUPTS_TABLE = os.getenv("DDB_INTERRUPTS_TABLE", "handoff_interrupts")

# --- Notifications ---
NOTIFY_CHANNEL = os.getenv("NOTIFY_CHANNEL", "slack")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN", "")

# --- UI ---
UI_BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:8000")

# --- HITL Gate ---
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
ALERT_WINDOW_DAYS = int(os.getenv("ALERT_WINDOW_DAYS", "14"))

# --- Observability ---
OTEL_ENABLED = os.getenv("STRANDS_OTEL_ENABLE", "true").lower() == "true"
OTEL_EXPORTER = os.getenv("STRANDS_OTEL_EXPORTER", "console")

# --- MCP ---
USE_MOCK_TOOLS = os.getenv("USE_MOCK_TOOLS", "true").lower() == "true"
GMAIL_OAUTH_TOKEN = os.getenv("GMAIL_OAUTH_TOKEN", "")
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")


def get_model() -> BedrockModel:
    """Get the primary Bedrock model."""
    return BedrockModel(
        model_id=BEDROCK_MODEL_ID,
        region_name=AWS_REGION,
    )


def get_fallback_model() -> BedrockModel:
    """Get the fallback Bedrock model."""
    return BedrockModel(
        model_id=BEDROCK_FALLBACK_MODEL_ID,
        region_name=AWS_REGION,
    )
```

## .env.example

```env
# ============================================
# Handoff Environment Configuration
# ============================================
# Copy this file to .env and fill in your values.
# NEVER commit .env to git.

# --- AWS ---
AWS_REGION=us-east-1
AWS_PROFILE=default

# --- Bedrock Models ---
# Verify current model IDs at:
# https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_FALLBACK_MODEL_ID=us.amazon.nova-pro-v1:0

# --- DynamoDB ---
DDB_WORKFLOWS_TABLE=handoff_workflows
DDB_AUDIT_TABLE=handoff_audit
DDB_INTERRUPTS_TABLE=handoff_interrupts

# --- Notifications ---
# Options: slack, sns, ses, none
NOTIFY_CHANNEL=slack
SLACK_WEBHOOK_URL=
SNS_TOPIC_ARN=

# --- UI ---
UI_BASE_URL=http://localhost:8000

# --- HITL Gate ---
# Confidence threshold (0.0–1.0). Below this, the agent interrupts.
CONFIDENCE_THRESHOLD=0.7

# --- Observability ---
# Set to true to enable OpenTelemetry tracing
STRANDS_OTEL_ENABLE=true
# Options: console, cloudwatch
STRANDS_OTEL_EXPORTER=console

# --- MCP Tools ---
# Set to false to use real MCP connections instead of mock data
USE_MOCK_TOOLS=true
# Only needed if USE_MOCK_TOOLS=false:
GMAIL_OAUTH_TOKEN=
LINEAR_API_KEY=
SLACK_BOT_TOKEN=
```

## requirements.txt

```
# Core
strands-agents>=0.1.0
strands-agents-tools>=0.1.0

# AWS
boto3>=1.35.0
bedrock-agentcore>=0.1.0

# Web UI
fastapi>=0.115.0
uvicorn>=0.32.0
jinja2>=3.1.0
python-multipart>=0.0.12
httpx>=0.27.0

# Data
pydantic>=2.9.0

# Config
python-dotenv>=1.0.0

# Dev / Test
pytest>=8.3.0
pytest-asyncio>=0.24.0
ruff>=0.8.0
```

## pyproject.toml (alternative to requirements.txt)

```toml
[project]
name = "handoff"
version = "0.1.0"
description = "Describe it. Hand it off. It runs."
readme = "README.md"
license = {text = "Apache-2.0"}
requires-python = ">=3.12"
dependencies = [
    "strands-agents>=0.1.0",
    "strands-agents-tools>=0.1.0",
    "boto3>=1.35.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.12",
    "httpx>=0.27.0",
    "pydantic>=2.9.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

## .gitignore

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/

# Environment
.env
*.env.local

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# AWS
.aws/

# Test
.pytest_cache/
htmlcov/
.coverage

# Docker
*.log
```

## LICENSE (Apache-2.0)

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   [Full Apache-2.0 text — copy from https://www.apache.org/licenses/LICENSE-2.0.txt]
```

Download the full text from https://www.apache.org/licenses/LICENSE-2.0.txt and save as `LICENSE` in the repo root. Also set it in GitHub's repo About/Settings.
