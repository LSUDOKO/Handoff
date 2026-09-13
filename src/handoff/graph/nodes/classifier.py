# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Classifier node — where the model actually earns its keep.

``classify_email`` does not classify anything itself, and that is deliberate.
Strands is a model-driven framework: the *agent* reasons about the message and
calls this tool to record the conclusion it reached. Hard-coding rules here
would turn the LLM into an expensive if-statement.

What the tool does add is the memory overlay — a learned preference that
matches this sender or subject raises confidence, which is precisely how a
question the human already answered stops being asked again.
"""

from __future__ import annotations

from strands import tool

from handoff.memory.store import find_matching_preference
from handoff.models import EmailCategory
from handoff.runtime import current_run

VALID_CATEGORIES = {c.value for c in EmailCategory}


@tool
def classify_email(
    email_id: str,
    category: str,
    confidence: float,
    suggested_action: str,
    reasoning: str,
    sender: str = "",
    subject: str = "",
    snippet: str = "",
) -> dict:
    """Optional: record a classification before acting, when you want to
    think an item through. Pass the id and your judgement only.

    Args:
        email_id: Id from fetch_unread_emails.
        category: "teammate_request" | "newsletter" | "manager" | "automated" | "ambiguous".
        confidence: 0.0-1.0.
        suggested_action: "file_ticket" | "archive" | "draft_reply" | "skip".
        reasoning: One or two sentences.
        sender: Optional; only if not fetched this run.
        subject: Optional; same.
        snippet: Optional; same.
    """
    category = category if category in VALID_CATEGORIES else EmailCategory.AMBIGUOUS.value
    confidence = max(0.0, min(1.0, float(confidence)))

    ctx = current_run()
    known = ctx.item(email_id) if ctx is not None else {}
    sender = sender or str(known.get("sender", ""))
    subject = subject or str(known.get("subject", ""))
    snippet = snippet or str(known.get("snippet", ""))

    result = {
        "email_id": email_id,
        "sender": sender,
        "subject": subject,
        "snippet": snippet,
        "category": category,
        "confidence": confidence,
        "suggested_action": suggested_action,
        "reasoning": reasoning,
        "applied_preference": None,
    }

    preference = find_matching_preference(sender=sender, subject=subject, snippet=snippet)
    if preference is not None:
        result["suggested_action"] = preference.action
        result["confidence"] = max(confidence, preference.confidence)
        result["applied_preference"] = preference.preference_id
        result["reasoning"] = (
            f"{reasoning} (Applying a rule you set earlier: {preference.pattern})"
        )

    return result
