# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Embedding Handoff in another agent runtime.

See :mod:`handoff.host.embed` for the host-context protocol — it is two
methods — and :mod:`handoff.host.gate` for how a Strands interrupt is answered
through the host instead of through Handoff's own decision screen.
"""

from handoff.host.embed import pick_workflow, run_in_host
from handoff.host.gate import HostGate, options_for, question_for
from handoff.host.tools import HostTool, describe, load_host_tools

__all__ = [
    "HostGate",
    "HostTool",
    "describe",
    "load_host_tools",
    "options_for",
    "pick_workflow",
    "question_for",
    "run_in_host",
]
