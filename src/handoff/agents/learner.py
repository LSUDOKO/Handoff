# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The Learning Agent — why the second run interrupts less than the first.

Every time a human resolves an interrupt, they have told us something we didn't
know. This agent's only job is to write that down in a form the executor can
use next week, so the same question is never asked twice.

The hard part is not storing the rule, it's not over-generalising it. "Archive
mail from partnerships@vendor.com" is a rule. "Archive mail that looks like
sales" is a licence to delete something the user wanted. The system prompt
leans hard on that distinction, and ``find_matching_preference`` is
correspondingly strict about when a stored rule is allowed to fire.
"""

from __future__ import annotations

from typing import Any

from strands import Agent

from handoff import config
from handoff.memory.store import (
    list_preferences,
    recall_preferences,
    store_user_preference,
)
from handoff.models import InterruptPayload, UserDecision

LEARNER_PROMPT = """You turn one human decision into one reusable rule.

You are given: an item the executor wasn't sure about, what it suggested, what
the human actually chose, and any note they left.

Work out what the decision reveals, then call store_user_preference exactly
once. Then stop.

Be narrow. The rule you write will run unsupervised on this person's mail:

- Prefer an exact sender match when the decision plainly turned on who sent it.
- Use "@domain.com" only when the whole domain clearly behaves the same way.
- Use keywords only when they are distinctive. "partnership", "invoice",
  "dependabot" are distinctive. "update", "important", "please" are not.
- If the decision looks like a one-off — a specific person, a specific week, a
  specific project — say so in the pattern and set confidence below 0.6 so it
  is applied cautiously.
- If you cannot see a generalisable rule at all, store one scoped tightly to
  that exact sender and subject rather than inventing a broad one.

The user's note, if they left one, is the strongest signal you have. It is them
telling you the reason directly — weight it above your own inference.

Write `pattern` as a sentence the user would recognise as their own decision,
because they will see it listed as a rule you are acting on."""


def create_learner_agent(model: Any = None) -> Agent:
    """Construct the Learning Agent."""
    return Agent(
        model=model if model is not None else config.get_model(),
        tools=[store_user_preference, recall_preferences],
        system_prompt=LEARNER_PROMPT,
        name="learner",
        description="Turns human decisions into rules for future runs",
        callback_handler=None,
    )


def _briefing(payload: InterruptPayload, decision: UserDecision, preference_key: str) -> str:
    return (
        "A human just resolved one of your escalations.\n\n"
        f"Store the rule under preference_key=\"{preference_key}\".\n\n"
        f"Item id:        {payload.item.item_id}\n"
        f"From:           {payload.item.sender}\n"
        f"Subject:        {payload.item.subject}\n"
        f"Preview:        {payload.item.snippet}\n\n"
        f"Why I escalated it: {payload.reason}\n"
        f"My suggestion:      {payload.agent_analysis.suggested_action or '(none)'}"
        f" at {payload.agent_analysis.confidence:.0%} confidence\n"
        f"My reasoning:       {payload.agent_analysis.reasoning}\n\n"
        f"What they chose:    {decision.chosen_action}\n"
        f"Their note:         {decision.user_note or '(none)'}\n\n"
        "Store the rule this implies."
    )


def learn_from_decision(
    payload: InterruptPayload,
    decision: UserDecision,
    preference_key: str = "",
    model: Any = None,
) -> dict[str, Any]:
    """Run the Learning Agent over one resolved decision.

    The rule must land under the workflow's ``preference_key`` or the gate
    will never find it. The key is put in the briefing *and* enforced after
    the fact — a model that forgets the argument, or a fallback rule written
    without a model at all, still ends up where the executor looks.
    """
    from handoff.memory.store import save_preference
    from handoff.models import LearnedPreference

    preference_key = preference_key or "default_rules"
    before_ids = {p.preference_id for p in list_preferences()}

    reply = ""
    try:
        agent = create_learner_agent(model)
        reply = str(agent(_briefing(payload, decision, preference_key)))
    except Exception as exc:
        reply = f"learner unavailable: {exc}"

    new_rules = [p for p in list_preferences() if p.preference_id not in before_ids]

    # Wherever the model put them, they belong to this workflow.
    for rule in new_rules:
        if rule.preference_key != preference_key:
            rule.preference_key = preference_key
            save_preference(rule)

    if not new_rules and payload.item.sender and decision.chosen_action:
        # The model didn't write a rule (throttled, answered in prose, or
        # judged it a one-off). Fail toward the narrowest safe thing: this
        # exact sender, this action. Never toward asking again next week.
        fallback = LearnedPreference(
            preference_key=preference_key,
            pattern=(
                f"{decision.chosen_action.replace('_', ' ').capitalize()} mail from "
                f"{payload.item.sender}"
                + (f" — {decision.user_note}" if decision.user_note else "")
            ),
            match_sender=payload.item.sender,
            action=decision.chosen_action,
            confidence=0.85,
            source_interrupt_id=payload.interrupt_id,
            note=decision.user_note,
        )
        save_preference(fallback)
        new_rules = [fallback]
        reply = (reply + " (stored a narrow sender rule as fallback)").strip()

    after = list_preferences()
    return {
        "stored": bool(new_rules),
        "rules": [
            {"pattern": r.pattern, "action": r.action, "match_sender": r.match_sender}
            for r in new_rules
        ],
        "total_rules": len(after),
        "reply": str(reply)[:500],
    }
