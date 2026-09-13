# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff` command line: run a workflow, answer a decision, serve the UI."""

from __future__ import annotations

import argparse
import json


def build_parser() -> argparse.ArgumentParser:
    """The command tree. Exposed so the docs can render a reference from it."""
    parser = argparse.ArgumentParser(
        prog="handoff", description="Describe it. Hand it off. It runs."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run a workflow now")
    p_run.add_argument("workflow_id", nargs="?", default="inbox-triage-morning")
    p_run.add_argument("--trigger", default="manual")

    sub.add_parser("pending", help="List decisions waiting on you")

    p_decide = sub.add_parser("decide", help="Answer a pending decision")
    p_decide.add_argument("interrupt_id")
    p_decide.add_argument("action")
    p_decide.add_argument("--note", default="")

    p_serve = sub.add_parser("serve", help="Start the web UI")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument(
        "--host", default="127.0.0.1", help="Bind address (0.0.0.0 to expose)"
    )

    p_desktop = sub.add_parser("desktop", help="Open Handoff in a native window")
    p_desktop.add_argument("--port", type=int, default=0)

    sub.add_parser("workflows", help="List saved workflows")
    sub.add_parser("rules", help="List the rules it has learned from you")

    p_ws = sub.add_parser("workspace", help="Export or import a workspace.yml / bundle")
    ws_sub = p_ws.add_subparsers(dest="ws_command", required=True)
    p_ws_export = ws_sub.add_parser("export", help="Write workspace.yml (or a .zip bundle) to a path")
    p_ws_export.add_argument("path", help="Where to write; .zip for a bundle, anything else for YAML")
    p_ws_export.add_argument("--workspace", default="", help="Workspace id (default: the default workspace)")
    p_ws_import = ws_sub.add_parser("import", help="Create a workspace from a workspace.yml or bundle")
    p_ws_import.add_argument("path")
    ws_sub.add_parser("list", help="List workspaces")

    p_doctor = sub.add_parser(
        "doctor", help="Check which credentials actually work"
    )
    p_doctor.add_argument(
        "checks", nargs="*", help="Only run these (e.g. gmail linear slack)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from handoff import config

    # `doctor` runs before anything is set up, so it must not depend on the
    # store, the examples, or a working model.
    if args.command == "doctor":
        from handoff import doctor

        return doctor.report(doctor.run(args.checks or None))

    from handoff.store import get_store
    from handoff.tools.workflow_store import seed_examples

    config.configure_observability()
    seed_examples()
    store = get_store()

    if args.command == "workspace":
        from pathlib import Path

        from handoff.platform import workspace_yaml

        if args.ws_command == "list":
            for ws in store.list_workspaces():
                print(f"{ws.workspace_id}  {ws.name}{'  (default)' if ws.is_default else ''}")
            return 0
        if args.ws_command == "export":
            workspace_id = args.workspace or store.default_workspace().workspace_id
            target = Path(args.path)
            if target.suffix == ".zip":
                target.write_bytes(workspace_yaml.bundle(workspace_id))
            else:
                target.write_text(workspace_yaml.to_yaml(workspace_id))
            print(f"wrote {target}")
            return 0
        if args.ws_command == "import":
            source = Path(args.path)
            result = workspace_yaml.import_document(source.read_bytes(), source.name)
            print(f"imported '{result['name']}' as {result['workspace_id']}: "
                  f"{result['workflows']} workflows, {result['skills']} skills, {result['agents']} agents")
            return 0

    if args.command == "run":
        from handoff.agents.executor import run_workflow

        outcome = run_workflow(args.workflow_id, args.trigger)
        print(json.dumps(dict(outcome), indent=2, default=str))
        return 0

    if args.command == "pending":
        for payload in store.pending_interrupts():
            print(
                f"{payload.interrupt_id}  {payload.item.sender:<28}  "
                f"{payload.agent_analysis.confidence:>4.0%}  {payload.item.subject}"
            )
        return 0

    if args.command == "decide":
        from handoff.agents.executor import submit_decision

        outcome = submit_decision(args.interrupt_id, args.action, args.note)
        print(json.dumps(dict(outcome), indent=2, default=str))
        return 0

    if args.command == "workflows":
        for workflow in store.list_workflows():
            print(f"{workflow.workflow_id:<28} {workflow.status.value:<8} {workflow.name}")
        return 0

    if args.command == "rules":
        for rule in store.list_preferences():
            print(f"{rule.action:<14} {rule.pattern}")
        return 0

    if args.command == "desktop":
        from handoff.desktop import main as desktop_main

        return desktop_main(args.port or None)

    if args.command == "serve":
        import uvicorn

        port = args.port or config.UI_PORT
        uvicorn.run("handoff.web.server:app", host=args.host, port=port, reload=False)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
