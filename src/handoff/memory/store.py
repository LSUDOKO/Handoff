# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Learned preferences — the reason the agent asks fewer questions over time.

Backed by AgentCore Memory when ``USE_AGENTCORE_MEMORY=true`` and a memory id
is configured, and by the local store otherwise. Both paths speak the same
``LearnedPreference`` model, so the learning loop is identical in the demo and
in production.

The matching in :func:`find_matching_preference` is intentionally conservative.
A preference that fires too eagerly silently takes actions the human never
sanctioned, which is a far worse failure than one extra interrupt.
"""

from __future__ import annotations

import re
from typing import Any

from strands import tool

from handoff import config
from handoff.models import LearnedPreference
from handoff.store import get_store

#: Words too common to identify anything, stripped before keyword matching.
_STOPWORDS = {
    "the", "and", "for", "you", "your", "our", "with", "from", "this", "that",
    "have", "has", "are", "was", "were", "will", "would", "can", "could",
    "about", "into", "over", "re", "fwd", "please", "thanks", "hi", "hello",
    "a", "an", "of", "to", "in", "on", "is", "it", "be", "by", "at", "as",
}


def _keywords(text: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    seen: list[str] = []
    for word in words:
        if word in _STOPWORDS or word in seen:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    return seen


# --- AgentCore Memory adapter ----------------------------------------------


def _agentcore_client():
    import boto3

    return boto3.client("bedrock-agentcore", region_name=config.AWS_REGION)


def _agentcore_store(pref: LearnedPreference) -> bool:
    try:
        client = _agentcore_client()
        client.create_event(
            memoryId=config.AGENTCORE_MEMORY_ID,
            actorId=pref.preference_key,
            sessionId=pref.source_interrupt_id or pref.preference_id,
            payload=[
                {
                    "conversational": {
                        "role": "ASSISTANT",
                        "content": {"text": pref.model_dump_json()},
                    }
                }
            ],
        )
        return True
    except Exception as exc:  # pragma: no cover - requires live AgentCore
        print(f"[handoff] AgentCore Memory write failed, using local store: {exc}")
        return False


def _agentcore_recall(query: str, preference_key: str) -> list[LearnedPreference]:
    try:
        client = _agentcore_client()
        resp = client.retrieve_memory_records(
            memoryId=config.AGENTCORE_MEMORY_ID,
            namespace=f"/preferences/{preference_key}",
            searchCriteria={"searchQuery": query, "topK": 5},
        )
        out: list[LearnedPreference] = []
        for record in resp.get("memoryRecordSummaries", []):
            text = record.get("content", {}).get("text", "")
            try:
                out.append(LearnedPreference.model_validate_json(text))
            except Exception:
                continue
        return out
    except Exception as exc:  # pragma: no cover - requires live AgentCore
        print(f"[handoff] AgentCore Memory recall failed, using local store: {exc}")
        return []


# --- Public API -------------------------------------------------------------


def save_preference(pref: LearnedPreference) -> LearnedPreference:
    """Persist a learned preference to AgentCore Memory and the local store.

    The local write always happens: it is what the dashboard reads, and it
    keeps the demo honest when AgentCore isn't reachable.
    """
    if config.USE_AGENTCORE_MEMORY:
        _agentcore_store(pref)
    return get_store().save_preference(pref)


def list_preferences(preference_key: str | None = None) -> list[LearnedPreference]:
    return get_store().list_preferences(preference_key)


def find_matching_preference(
    sender: str = "", subject: str = "", snippet: str = "", preference_key: str | None = None
) -> LearnedPreference | None:
    """Find a rule the user already gave us that covers this item.

    An exact sender match wins outright. Otherwise a preference must match on
    at least two distinct keywords before it is allowed to fire — one shared
    word is a coincidence, not a rule.
    """
    prefs = list_preferences(preference_key)
    if not prefs:
        return None

    sender = (sender or "").lower().strip()
    haystack = f"{subject} {snippet}".lower()

    exact = [p for p in prefs if p.match_sender and p.match_sender.lower() == sender]
    if exact:
        return max(exact, key=lambda p: p.confidence)

    domain = sender.split("@")[-1] if "@" in sender else ""
    if domain:
        by_domain = [
            p for p in prefs
            if p.match_sender.startswith("@") and p.match_sender.lower().lstrip("@") == domain
        ]
        if by_domain:
            return max(by_domain, key=lambda p: p.confidence)

    best: LearnedPreference | None = None
    best_hits = 0
    for pref in prefs:
        if not pref.match_keywords:
            continue
        hits = sum(1 for kw in pref.match_keywords if kw.lower() in haystack)
        if hits >= 2 and hits > best_hits:
            best, best_hits = pref, hits
    return best


# --- Tools exposed to the agents -------------------------------------------


@tool
def store_user_preference(
    pattern: str,
    action: str,
    match_sender: str = "",
    match_keywords: list[str] | None = None,
    preference_key: str = "default_rules",
    confidence: float = 0.9,
    note: str = "",
    source_interrupt_id: str = "",
) -> dict:
    """Store a rule learned from a human decision, for use on future runs.

    Be specific. "Archive anything from partnerships@vendor.com" is a useful
    rule; "archive unimportant email" is not, and will cause the agent to act
    without permission on things the user cared about.

    Args:
        pattern: The rule in one plain sentence, shown to the user later.
        action: What to do when it matches: "file_ticket", "archive",
            "draft_reply" or "skip".
        match_sender: An exact address, or "@domain.com" for a whole domain.
        match_keywords: Distinctive subject/body words. At least two must
            appear before the rule fires, so choose specific ones.
        preference_key: Which workflow's rule set this belongs to.
        confidence: How strongly to apply it, 0.0 to 1.0.
        note: The user's own note from the decision screen, if they left one.
        source_interrupt_id: The decision this rule was learned from.

    Returns:
        The stored preference, including its new id.
    """
    if not match_sender and not match_keywords:
        match_keywords = _keywords(pattern)

    pref = LearnedPreference(
        preference_key=preference_key,
        pattern=pattern,
        match_sender=match_sender,
        match_keywords=[k.lower() for k in (match_keywords or [])],
        action=action,
        confidence=max(0.0, min(1.0, float(confidence))),
        note=note,
        source_interrupt_id=source_interrupt_id,
    )
    save_preference(pref)
    return {
        "stored": True,
        "preference_id": pref.preference_id,
        "pattern": pref.pattern,
        "action": pref.action,
        "match_sender": pref.match_sender,
        "match_keywords": pref.match_keywords,
    }


@tool
def recall_preferences(context: str, preference_key: str = "default_rules") -> list[dict]:
    """Rules this user set on earlier runs. Call once, first.

    Args:
        context: What you're about to process, briefly.
        preference_key: The workflow's rule set.
    """
    prefs: list[LearnedPreference] = []
    if config.USE_AGENTCORE_MEMORY:
        prefs = _agentcore_recall(context, preference_key)
    if not prefs:
        prefs = list_preferences(preference_key)

    return [
        {
            "preference_id": p.preference_id,
            "pattern": p.pattern,
            "action": p.action,
            "match_sender": p.match_sender,
            "match_keywords": p.match_keywords,
            "confidence": p.confidence,
        }
        for p in prefs
    ]


def memory_summary() -> dict[str, Any]:
    """Rollup for the dashboard's "what it has learned" panel."""
    prefs = list_preferences()
    return {
        "count": len(prefs),
        "backend": "agentcore" if config.USE_AGENTCORE_MEMORY else "local",
        "rules": [
            {"pattern": p.pattern, "action": p.action, "applied": p.times_applied}
            for p in prefs
        ],
    }
