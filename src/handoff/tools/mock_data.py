# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Synthetic inbox used by the demo and the test suite.

A flaky live integration makes for a flaky demo, so every tool has a mock mode
and this is its data. The eight messages are chosen deliberately: five are
unambiguous (the agent should handle them silently) and three are genuinely
hard (the agent should stop and ask). That ratio is the whole argument — an
agent that interrupts on everything is just a worse inbox.
"""

from __future__ import annotations

MOCK_EMAILS: list[dict] = [
    {
        "email_id": "msg_001",
        "sender": "alice@team.com",
        "sender_name": "Alice Chen",
        "subject": "Need API review by Thursday",
        "snippet": (
            "Can you review the payments API PR #247? It's blocking the v2.1 "
            "release. I've tagged the specific files that changed."
        ),
        "timestamp": "2026-09-12T07:23:00Z",
        "labels": ["team", "engineering"],
        "thread_length": 1,
    },
    {
        "email_id": "msg_002",
        "sender": "newsletter@techcrunch.com",
        "sender_name": "TechCrunch Daily",
        "subject": "TC Daily: AI Agents Are Eating Software",
        "snippet": (
            "Today's top stories: AWS launches new agent framework, Google "
            "responds with..."
        ),
        "timestamp": "2026-09-12T06:00:00Z",
        "labels": ["newsletter", "promotions"],
        "thread_length": 1,
    },
    {
        "email_id": "msg_003",
        "sender": "boss@company.com",
        "sender_name": "Jordan Kim (Manager)",
        "subject": "Quick sync on Q3 targets",
        "snippet": (
            "Let's discuss the pipeline numbers before the board deck. "
            "Free at 2pm today?"
        ),
        "timestamp": "2026-09-12T08:15:00Z",
        "labels": ["manager", "important"],
        "thread_length": 3,
    },
    {
        "email_id": "msg_004",
        "sender": "partnerships@vendor.com",
        "sender_name": "Unknown — Vendor Corp",
        "subject": "Strategic partnership opportunity — time sensitive",
        "snippet": (
            "We'd love to explore a strategic integration between our "
            "platforms. Our CEO is available next week for an intro call."
        ),
        "timestamp": "2026-09-12T05:45:00Z",
        "labels": [],
        "thread_length": 1,
    },
    {
        "email_id": "msg_005",
        "sender": "hr@company.com",
        "sender_name": "HR Team",
        "subject": "Updated PTO policy — action may be required",
        "snippet": (
            "We've updated the PTO accrual policy effective Q4. Some changes "
            "may affect your remaining balance. Please review by Sept 20."
        ),
        "timestamp": "2026-09-12T04:30:00Z",
        "labels": ["internal", "hr"],
        "thread_length": 1,
    },
    {
        "email_id": "msg_006",
        "sender": "bob@team.com",
        "sender_name": "Bob Martinez",
        "subject": "Re: Sprint retro action items",
        "snippet": (
            "I've drafted the post-mortem doc. Can you add the infra section? "
            "Link: https://docs.internal/retro-q3"
        ),
        "timestamp": "2026-09-12T07:50:00Z",
        "labels": ["team"],
        "thread_length": 5,
    },
    {
        "email_id": "msg_007",
        "sender": "security@github.com",
        "sender_name": "GitHub Security",
        "subject": "[handoff/handoff] Dependabot alert: lodash prototype pollution",
        "snippet": (
            "A security vulnerability was detected in a dependency of your "
            "repository."
        ),
        "timestamp": "2026-09-12T03:12:00Z",
        "labels": ["github", "automated"],
        "thread_length": 1,
    },
    {
        "email_id": "msg_008",
        "sender": "cfo@company.com",
        "sender_name": "CFO Office",
        "subject": "FYI: Budget freeze through end of month",
        "snippet": (
            "All non-essential purchases are paused until the monthly close. "
            "Exceptions require VP approval."
        ),
        "timestamp": "2026-09-12T08:30:00Z",
        "labels": ["internal", "leadership"],
        "thread_length": 1,
    },
]

#: What a well-behaved run should conclude. Used by the deterministic fake
#: model and asserted on in tests/test_classifier.py.
EXPECTED_CLASSIFICATIONS: dict[str, dict] = {
    "msg_001": {"category": "teammate_request", "action": "file_ticket", "confidence": 0.95},
    "msg_002": {"category": "newsletter", "action": "archive", "confidence": 0.99},
    "msg_003": {"category": "manager", "action": "draft_reply", "confidence": 0.95},
    "msg_004": {"category": "ambiguous", "action": "file_ticket", "confidence": 0.30},
    "msg_005": {"category": "ambiguous", "action": "draft_reply", "confidence": 0.50},
    "msg_006": {"category": "teammate_request", "action": "file_ticket", "confidence": 0.90},
    "msg_007": {"category": "automated", "action": "file_ticket", "confidence": 0.85},
    "msg_008": {"category": "ambiguous", "action": "skip", "confidence": 0.60},
}

#: Reasoning strings the fake model attaches, so the decision screen has
#: something honest to show during an offline demo.
MOCK_REASONING: dict[str, str] = {
    "msg_001": "Named teammate, concrete deliverable, explicit deadline. Standard ticket.",
    "msg_002": "Bulk sender with a promotions label and no direct ask. Safe to archive.",
    "msg_003": "Direct manager asking for a time-boxed sync. Draft a reply for review.",
    "msg_004": (
        "Unknown external sender using urgency language. Could be a real business "
        "development lead or could be cold spam — I can't tell from one message, "
        "and filing or deleting both have a cost if I'm wrong."
    ),
    "msg_005": (
        "Internal and legitimate, but 'action may be required' is doing a lot of "
        "work. Whether this needs a calendar reminder or nothing at all depends "
        "on a PTO balance I can't see."
    ),
    "msg_006": "Known teammate, explicit request for a named section. Ticket.",
    "msg_007": "Automated security alert on our own repo. Always worth a ticket.",
    "msg_008": (
        "Leadership FYI with no direct ask, but it changes what purchases are "
        "allowed this month. Archiving it might bury something you needed."
    ),
}

#: The second demo workflow's fixture: a competitor pricing page, before/after.
MOCK_PRICING_SNAPSHOT: dict = {
    "url": "https://competitor.example/pricing",
    "captured_at": "2026-09-12T09:00:00Z",
    "tiers": [
        {"name": "Starter", "price": 0, "period": "mo"},
        {"name": "Team", "price": 49, "period": "mo"},
        {"name": "Enterprise", "price": 129, "period": "mo"},
    ],
}

MOCK_PRICING_PREVIOUS: dict = {
    "url": "https://competitor.example/pricing",
    "captured_at": "2026-09-05T09:00:00Z",
    "tiers": [
        {"name": "Starter", "price": 0, "period": "mo"},
        {"name": "Team", "price": 49, "period": "mo"},
        {"name": "Enterprise", "price": 99, "period": "mo"},
    ],
}
