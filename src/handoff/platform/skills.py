# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Reusable instruction, written once and attached where it's needed.

A skill is markdown with a name and a description. The description is the
part that does the work: an agent reads it to decide whether the body is
worth loading, which is how you can have twenty skills without putting twenty
pages into every prompt.

Handoff uses them for the judgement that differs between workspaces — what
counts as urgent in *your* inbox, which senders are internal, what your team
means by "blocked". That knowledge doesn't belong in the executor's prompt,
because it isn't true for everyone.
"""

from __future__ import annotations

import re

from handoff.platform.models import Skill, slugify
from handoff.store import get_store

FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def parse(markdown: str) -> tuple[str, str, str]:
    """Split ``name``, ``description`` and body out of a skill document."""
    match = FRONTMATTER.match(markdown.strip())
    if not match:
        first = markdown.strip().splitlines()[0] if markdown.strip() else ""
        return slugify(first.lstrip("# ").strip(), "skill"), "", markdown.strip()

    head, body = match.groups()
    name = description = ""
    key = None
    for line in head.splitlines():
        if line.startswith(("name:", "description:")):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip("|>").strip()
            if key == "name":
                name = value
            else:
                description = value
        elif key == "description" and line.strip():
            description = f"{description} {line.strip()}".strip()
    return name or "skill", description, body.strip()


def render(skill: Skill) -> str:
    return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n{skill.body}"


def save_from_markdown(
    markdown: str, workspace_id: str = "", namespace: str = "workspace", skill_id: str = ""
) -> Skill:
    name, description, body = parse(markdown)
    store = get_store()
    skill = store.skills.get("skill_id", skill_id) if skill_id else None
    if skill is None:
        skill = Skill(workspace_id=workspace_id, namespace=namespace, name=name)
    skill.name = slugify(name, "skill")
    skill.description = description
    skill.body = body
    from datetime import UTC, datetime

    skill.updated_at = datetime.now(UTC)
    store.skills.put(skill, "skill_id")
    return skill


def compose(skill_ids: list[str], workspace_id: str | None = None) -> str:
    """Fold the named skills into one block for an agent's system prompt.

    Only enabled skills are included, and each is labelled, so an agent that
    misapplies one can be traced back to the text that told it to.
    """
    store = get_store()
    wanted = set(skill_ids)
    chosen = [
        s
        for s in store.list_skills(workspace_id)
        if s.enabled and (s.skill_id in wanted or s.qualified in wanted or s.name in wanted)
    ]
    if not chosen:
        return ""

    blocks = [
        "The following are instructions this workspace has established. Treat "
        "them as the user's own standing preferences.",
        "",
    ]
    for skill in chosen:
        blocks.append(f"## {skill.name}")
        if skill.description:
            blocks.append(f"_{skill.description}_")
        blocks.append("")
        blocks.append(skill.body)
        blocks.append("")
    return "\n".join(blocks).strip()


BUILTIN_SKILLS: list[dict[str, str]] = [
    {
        "name": "escalation-style",
        "description": (
            "How to word a question when stopping for a human. Loads whenever "
            "an item is being escalated."
        ),
        "body": (
            "When you escalate, the person reads your reasoning and nothing "
            "else. Write it so they can decide without opening the item.\n\n"
            "- Say what you could not determine, not that something was unclear.\n"
            "  \"I can't tell if this vendor is known to you\" beats \"ambiguous\".\n"
            "- Name the cost of being wrong in each direction. That is usually\n"
            "  why you stopped.\n"
            "- One or two sentences. If it takes longer to read your question\n"
            "  than to open the email, you have saved them nothing."
        ),
    },
    {
        "name": "sender-trust",
        "description": (
            "How to weigh who sent something when classifying. Loads during "
            "inbox triage and any workflow that reads mail."
        ),
        "body": (
            "Sender is the strongest signal you have, in this order:\n\n"
            "1. A named colleague with a concrete ask — act. This is the\n"
            "   clearest case there is.\n"
            "2. An automated sender about our own systems (CI, security\n"
            "   alerts, error tracking) — act; these are routine.\n"
            "3. A bulk sender with an unsubscribe link — archive.\n"
            "4. An unknown external sender asking for time or money — stop.\n"
            "   Urgency language from a stranger is a reason to be slower,\n"
            "   not faster."
        ),
    },
    {
        "name": "irreversibility",
        "description": (
            "Which actions deserve more caution than their confidence score "
            "suggests. Loads before any action that leaves the system."
        ),
        "body": (
            "Confidence is about whether you understood the item. It says\n"
            "nothing about what happens if you are wrong. Weigh both.\n\n"
            "- Reversible and private (archive, label, draft): act on ordinary\n"
            "  confidence. The person can undo it.\n"
            "- Visible to others (filing a ticket, posting to a channel): be\n"
            "  surer. Undoing it means explaining it.\n"
            "- Irreversible or reaching a stranger (sending mail, deleting):\n"
            "  ask, whatever your confidence. There is no undo."
        ),
    },
]


def seed_builtin_skills() -> list[Skill]:
    """Install the skills that ship with Handoff, once."""
    store = get_store()
    existing = {s.name for s in store.skills.all() if s.builtin}
    created: list[Skill] = []
    for spec in BUILTIN_SKILLS:
        if spec["name"] in existing:
            continue
        skill = Skill(
            namespace="handoff",
            name=spec["name"],
            description=spec["description"],
            body=spec["body"],
            builtin=True,
        )
        store.skills.put(skill, "skill_id")
        created.append(skill)
    return created
