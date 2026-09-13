# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Chat with a workspace: a Strands agent whose thread survives restarts."""

from handoff.chat.service import ChatService, get_chat_service

__all__ = ["ChatService", "get_chat_service"]
