# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""The sidebar, as data.

Templates should not know the information architecture; they render whatever
this hands them. Two lists: the global tools, and the per-workspace sub-nav
that unfolds under the active workspace.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str
    icon: str = ""
    key: str = ""
    badge: str = ""  # "pending" → live count from /api/status
    exact: bool = False

    def is_active(self, path: str) -> bool:
        if self.exact:
            return path == self.href
        return path == self.href or path.startswith(self.href.rstrip("/") + "/")


#: Global tools, in sidebar order.
TOOLS: tuple[NavItem, ...] = (
    NavItem("Talk", "/orb", "i-mic", "orb"),
    NavItem("Chat", "/chat", "i-chat", "chat"),
    NavItem("Memory", "/memory", "i-memory", "memory"),
    NavItem("Activity", "/activity", "i-clock", "activity", badge="pending"),
    NavItem("Agents", "/agents", "i-chip", "agents"),
    NavItem("Inspector", "/inspector", "i-inspect", "inspector"),
    NavItem("Schedules", "/schedules", "i-rotate", "schedules"),
    NavItem("Tool servers", "/mcp", "i-wrench", "mcp"),
    NavItem("Skills", "/skills", "i-compass", "skills"),
    NavItem("Usage", "/usage", "i-target", "usage"),
    NavItem("Settings", "/settings", "i-gear", "settings"),
)

DISCOVER = NavItem("Discover", "/discover", "i-discover", "discover")


@dataclass
class WorkspaceNav:
    id: str
    name: str
    color: str = "amber"
    requires_setup: bool = False
    active: bool = False
    sub: list[NavItem] = field(default_factory=list)


def workspace_subnav(workspace_id: str) -> list[NavItem]:
    base = f"/platform/{workspace_id}"
    return [
        NavItem("Overview", base, exact=True),
        NavItem("Activity", f"{base}/activity"),
        NavItem("Chat", f"{base}/chat"),
        NavItem("Agents", f"{base}/agents"),
        NavItem("Skills", f"{base}/skills"),
        NavItem("Workflows", f"{base}/workflows"),
        NavItem("Runs", f"{base}/runs"),
        NavItem("Memory", f"/memory/{workspace_id}"),
        NavItem("Settings", f"{base}/settings"),
    ]


def build(path: str, workspaces, active_id: str | None) -> dict:
    """Everything the shell template needs, given the current URL."""
    tools = [{"item": t, "active": t.is_active(path)} for t in TOOLS]
    discover = {"item": DISCOVER, "active": DISCOVER.is_active(path)}

    rows: list[WorkspaceNav] = []
    for ws in workspaces:
        wid = ws.workspace_id
        row = WorkspaceNav(
            id=wid,
            name=ws.name,
            color=getattr(ws, "color", "amber") or "amber",
            requires_setup=bool(getattr(ws, "requires_setup", False)),
            active=(wid == active_id),
        )
        if row.active:
            row.sub = workspace_subnav(wid)
        rows.append(row)

    # The personal workspace is pinned first; the rest keep store order.
    rows.sort(key=lambda r: 0 if r.id in ("personal", "user", "default") else 1)

    return {
        "tools": tools,
        "discover": discover,
        "workspaces": rows,
        "path": path,
    }
