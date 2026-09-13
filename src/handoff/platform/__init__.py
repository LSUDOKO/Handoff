# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The platform layer: everything around a single workflow run.

A workflow that runs once is a script. What makes it a platform is the rest:
somewhere to put many of them (workspaces), the credentials they act with,
the tool servers they reach, the reusable instructions they share (skills),
the agents you author yourself, a scheduler that fires them unattended, and
a record of what happened that you can actually inspect afterwards.
"""

from handoff.platform.models import (
    Artifact,
    Credential,
    CustomAgent,
    MCPServerConfig,
    MemoryEntry,
    MemoryStore,
    Schedule,
    Session,
    SessionStep,
    Skill,
    UsageRecord,
    Workspace,
)

__all__ = [
    "Artifact",
    "Credential",
    "CustomAgent",
    "MCPServerConfig",
    "MemoryEntry",
    "MemoryStore",
    "Schedule",
    "Session",
    "SessionStep",
    "Skill",
    "UsageRecord",
    "Workspace",
]
