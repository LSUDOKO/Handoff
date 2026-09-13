# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Builds the Strands Graph a workflow config describes.

**Why a Graph and not a Swarm.** A workflow is a fixed, auditable sequence:
wake up, do the work, stop at anything unclear, close out. ``Graph`` models
exactly that — deterministic edges, one entry point, a replayable execution
order. ``Swarm`` models open-ended collaboration between peers, which would
make every run take a different path through the same job. For something that
files tickets in your name at 8am, "different every time" is a bug.

The graph is three nodes because the responsibilities are genuinely different:

    trigger  — is this a legitimate reason to wake up?
    executor — do the work; stop and ask when unsure  (the HITL gate lives here)
    completer— write the audit trail and tell the human what happened

The gate is attached to the executor node only. The trigger and completer are
never in a position to do anything irreversible, so gating them would just add
interruptions without adding safety.
"""

from __future__ import annotations

from typing import Any

from strands import Agent

from handoff import config
from handoff.graph.hooks.hitl import HITLGate
from handoff.graph.nodes.classifier import classify_email
from handoff.graph.nodes.completer import finalize_run
from handoff.graph.nodes.executor import (
    check_competitor_pricing,
    fetch_unread_emails,
    get_email_body,
)
from handoff.graph.nodes.gate import finish_batch, submit_action
from handoff.graph.nodes.trigger import check_trigger
from handoff.mcp.servers import load_agent_tools
from handoff.memory.store import recall_preferences
from handoff.models import WorkflowConfig
from handoff.tools.notify import notify_user

TRIGGER_PROMPT = """You confirm whether a workflow should run.

Call check_trigger once with the trigger type you were given, then stop. Do not
do any of the workflow's actual work — that is the executor's job."""


EXECUTOR_PROMPT = """You are Handoff's Workflow Executor. You run a person's recurring task
while they do something else. Handle what is clear; ask about what isn't;
never guess at something you'd have to apologise for.

Loop:
1. recall_preferences first. Past answers are rules now — don't re-ask.
2. fetch_unread_emails.
3. For EACH item, exactly one submit_action call with category, action,
   confidence and reasoning. One item per turn. Pass ids only; never re-type
   subjects or previews. get_email_body if a preview isn't enough.
4. When every item has an action, call finish_batch once, then stop. Items
   you weren't sure about are set aside during the pass and asked about all
   together there — keep going through the batch; don't wait on them.

Confidence is a real decision, because submit_action is gated:
- 0.85-1.0 when sender, intent and action are all clear (a named teammate's
  specific ask → file_ticket; a bulk newsletter → archive; your manager →
  draft_reply; automated alerts on your repo → file_ticket). Act silently.
- Below 0.7 with force_interrupt=true when you genuinely can't tell: unknown
  sender with real stakes, or the right action depends on context you lack.
- Never inflate to avoid asking; never deflate to avoid responsibility.

Your reasoning is shown to the human verbatim when you escalate. Say exactly
what you couldn't determine, so they can decide in five seconds.

Most items should not need a human. Escalating more than a third of a batch
is timidity, not care."""


COMPLETER_PROMPT = """You close out a workflow run.

Call finalize_run exactly once with a two or three sentence summary. Lead with
what you handled autonomously, then what needed a human and why. Be concrete
about counts. Do not pad it — this is read at a glance over coffee."""


def build_executor_agent(
    workflow: WorkflowConfig | None,
    model: Any,
    gate: HITLGate | None = None,
    extra_tools: list[Any] | None = None,
) -> Agent:
    """Construct the agent that does the work, with the gate attached."""
    tools: list[Any] = [
        recall_preferences,
        fetch_unread_emails,
        get_email_body,
        classify_email,
        submit_action,
        finish_batch,
    ]

    if workflow is not None and "browser" in workflow.mcp_tools:
        tools.append(check_competitor_pricing)

    if workflow is not None:
        tools.extend(load_agent_tools(workflow.mcp_tools))
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        model=model,
        tools=tools,
        system_prompt=EXECUTOR_PROMPT,
        hooks=[gate] if gate is not None else [],
        name="executor",
        description="Runs the workflow and decides what needs a human",
        callback_handler=None,
    )


def build_workflow_graph(
    workflow: WorkflowConfig | None = None,
    model: Any = None,
    gate: HITLGate | None = None,
    extra_tools: list[Any] | None = None,
):
    """Wire trigger → executor → completer into a Strands Graph.

    Args:
        workflow: The config being run. Determines which integrations are
            loaded and where the confidence threshold sits.
        model: The model the EXECUTOR node runs on — this is where the actual
            judgment calls happen (is this ambiguous? what's my confidence?),
            so it defaults to the primary model. Defaults to the configured one.
        gate: The HITL gate to attach to the executor node.
        extra_tools: Additional tools for the executor node. When embedded in
            a host runtime this carries the host's already-authenticated
            tools, so Handoff uses the OAuth the user clicked through there
            rather than its own copy of every credential.

    Returns:
        A built ``Graph``, ready to invoke.

    The trigger and completer nodes run on the cheaper fallback model. Neither
    makes a judgment call — one confirms a cron/webhook fired, the other writes
    a two-sentence summary from numbers the executor already computed. Spending
    Sonnet-level reasoning on "did the trigger fire" is waste, not quality.
    """
    from strands.multiagent import GraphBuilder

    model = model if model is not None else config.get_model()
    light_model = config.get_fallback_model()

    trigger_agent = Agent(
        model=light_model,
        tools=[check_trigger],
        system_prompt=TRIGGER_PROMPT,
        name="trigger",
        description="Confirms the workflow's trigger condition",
        callback_handler=None,
    )

    executor_agent = build_executor_agent(workflow, model, gate, extra_tools)

    completer_agent = Agent(
        model=light_model,
        tools=[finalize_run, notify_user],
        system_prompt=COMPLETER_PROMPT,
        name="completer",
        description="Writes the audit trail and notifies the user",
        callback_handler=None,
    )

    builder = GraphBuilder()
    builder.add_node(trigger_agent, "trigger")
    builder.add_node(executor_agent, "executor")
    builder.add_node(completer_agent, "completer")

    builder.add_edge("trigger", "executor", condition=_trigger_fired)
    builder.add_edge("executor", "completer")
    builder.set_entry_point("trigger")
    builder.set_max_node_executions(12)

    return builder.build()


def _trigger_fired(state: Any) -> bool:
    """Edge condition: only run the work if the trigger actually validated.

    A webhook with an empty body should not cost a Bedrock invocation, let
    alone file tickets.
    """
    result = state.results.get("trigger") if hasattr(state, "results") else None
    if result is None:
        return True
    text = str(result).lower()
    return '"triggered": false' not in text and "'triggered': false" not in text


def build_inbox_triage_graph(model: Any = None, gate: HITLGate | None = None):
    """Convenience wrapper for the demo workflow."""
    from handoff.tools.workflow_store import load_example_workflows

    workflow = next(
        (w for w in load_example_workflows() if w.workflow_id == "inbox-triage-morning"),
        None,
    )
    return build_workflow_graph(workflow, model, gate)
