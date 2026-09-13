# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
#
# AgentCore Runtime requires linux/arm64, which buildx supplies at build time:
#   docker buildx build --platform linux/arm64 -t handoff:latest .
#
# The platform is deliberately NOT pinned in the FROM line — that would ignore
# --platform and break native builds on other architectures.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    HANDOFF_STATE_DIR=/tmp/handoff-state

WORKDIR /app

# Dependencies first, so source edits don't invalidate the wheel cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The web UI and the workflow templates live inside the package, so this is
# the whole application.
COPY src/ ./src/

# AgentCore Runtime health-checks and invokes on 8080.
EXPOSE 8080

RUN useradd --create-home --uid 10001 handoff \
    && mkdir -p /tmp/handoff-state \
    && chown -R handoff /tmp/handoff-state
USER handoff

CMD ["python", "-m", "handoff.app"]
