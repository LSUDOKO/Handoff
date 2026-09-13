# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Operating Handoff: serve, desktop, share, docs, deploy, doctor, completion, version.

None of these need the store set up first — `doctor` in particular must
work on a machine where nothing else does yet.
"""

from __future__ import annotations

import argparse
import re
import shutil
import socket
import subprocess
import sys

from handoff.cli import _ui

CLOUDFLARED_HINT = (
    "Install cloudflared: "
    "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
)
_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def register(sub: argparse._SubParsersAction) -> None:
    p_serve = sub.add_parser("serve", help="Start the web UI")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind address (0.0.0.0 to expose)")
    p_serve.set_defaults(handle=handle_serve, setup=False)

    p_desktop = sub.add_parser("desktop", help="Open Handoff in a native window")
    p_desktop.add_argument("--port", type=int, default=0)
    p_desktop.set_defaults(handle=handle_desktop, setup=False)

    p_share = sub.add_parser("share", help="Put a running `handoff serve` on a public trycloudflare URL")
    p_share.add_argument("--port", type=int, default=0, help="The port `handoff serve` is on")
    p_share.set_defaults(handle=handle_share, setup=False)

    p_docs = sub.add_parser("docs", help="List the guides, or open them in the running app")
    p_docs.add_argument("--open", action="store_true", help="Open /docs in the browser")
    p_docs.add_argument("--port", type=int, default=0)
    p_docs.set_defaults(handle=handle_docs, setup=False)

    p_deploy = sub.add_parser("deploy", help="Publish the site, or the AgentCore runtime")
    p_deploy.add_argument("target", choices=["site", "agentcore"])
    p_deploy.add_argument("extra", nargs=argparse.REMAINDER, help="Passed through to the deploy script")
    p_deploy.set_defaults(handle=handle_deploy, setup=False)

    p_doctor = sub.add_parser("doctor", help="Check which credentials actually work")
    p_doctor.add_argument("checks", nargs="*", help="Only run these (e.g. gmail linear slack)")
    p_doctor.set_defaults(handle=handle_doctor, setup=False)

    p_completion = sub.add_parser("completion", help="Print a shell completion script")
    p_completion.add_argument("shell", choices=["bash", "zsh", "fish"])
    p_completion.set_defaults(handle=handle_completion, setup=False)

    p_version = sub.add_parser("version", help="Print the version")
    p_version.set_defaults(handle=handle_version, setup=False)


# --- serving ----------------------------------------------------------------


def _port(requested: int) -> int:
    from handoff import config

    return requested or config.UI_PORT


def handle_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from handoff import config

    config.configure_observability()
    uvicorn.run("handoff.web.server:app", host=args.host, port=_port(args.port), reload=False)
    return 0


def handle_desktop(args: argparse.Namespace) -> int:
    from handoff.desktop import main as desktop_main

    return desktop_main(args.port or None)


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def handle_share(args: argparse.Namespace) -> int:
    exe = shutil.which("cloudflared")
    if not exe:
        if _ui.json_mode():
            _ui.print_json({"ok": False, "error": CLOUDFLARED_HINT})
        else:
            _ui.out(CLOUDFLARED_HINT)
        return 1

    port = _port(args.port)
    if not _listening(port):
        _ui.warn(f"nothing is listening on port {port} — start `handoff serve` first; tunnelling anyway")

    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = ""
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            match = _TUNNEL_URL.search(line)
            if match:
                url = match.group(0)
                if _ui.json_mode():
                    _ui.print_json({"ok": True, "url": url, "port": port})
                else:
                    _ui.ok(f"{url} → http://127.0.0.1:{port}  (Ctrl-C to stop sharing)")
                break
        if not url:
            _ui.fail("cloudflared exited before printing a URL")
            return 1
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
    return 0


def handle_docs(args: argparse.Namespace) -> int:
    try:
        from handoff import docs
    except ImportError:
        _ui.warn("the docs module isn't in this build yet — see docs/ in the repository")
        return 1

    pages = docs.index()
    if args.open:
        import webbrowser

        url = f"http://127.0.0.1:{_port(args.port)}/docs"
        webbrowser.open(url)
        if not _ui.json_mode():
            _ui.dim(f"opening {url}")
    _ui.emit(
        pages,
        lambda: _ui.table("Guides", ["slug", "title", "summary"], [[p["slug"], p["title"], p.get("summary", "")] for p in pages]),
    )
    return 0


def handle_deploy(args: argparse.Namespace) -> int:
    from handoff import config

    root = config.PROJECT_ROOT
    extra = [a for a in args.extra if a != "--"]

    if args.target == "site":
        build = root / "site" / "build.py"
        if not build.is_file():
            raise FileNotFoundError(f"{build} is missing — the site has not been added to this checkout")
        code = subprocess.run([sys.executable, str(build), *extra], cwd=root, check=False).returncode
        if code:
            _ui.fail(f"site build failed ({code})")
            return 1
        wrangler = shutil.which("wrangler") or shutil.which("npx")
        if not wrangler:
            _ui.fail("wrangler not found — `npm i -g wrangler`, then `wrangler login`")
            return 1
        command = [wrangler] if wrangler.endswith("wrangler") else [wrangler, "wrangler"]
        command += ["pages", "deploy", "site/dist", "--project-name", "handoff"]
        code = subprocess.run(command, cwd=root, check=False).returncode
        if code:
            _ui.fail(f"wrangler exited {code}")
            _ui.dim("first time? `wrangler login`, then `wrangler pages project create handoff`")
        return 1 if code else 0

    script = root / "infra" / "agentcore_runtime.py"
    if not script.is_file():
        raise FileNotFoundError(f"{script} is missing")
    code = subprocess.run([sys.executable, str(script), *extra], cwd=root, check=False).returncode
    return 1 if code else 0


# --- diagnostics ------------------------------------------------------------


def handle_doctor(args: argparse.Namespace) -> int:
    from handoff import doctor

    results = doctor.run(args.checks or None)
    if _ui.json_mode():
        _ui.print_json(results)
        return 1 if any(r["status"] == doctor.FAIL for r in results) else 0
    return doctor.report(results)


def handle_version(args: argparse.Namespace) -> int:
    from importlib.metadata import PackageNotFoundError, version

    try:
        release = version("handoff")
    except PackageNotFoundError:
        release = "0.0.0+source"
    python = ".".join(str(part) for part in sys.version_info[:3])
    if _ui.json_mode():
        _ui.print_json({"name": "handoff", "version": release, "python": python})
    else:
        _ui.console.print(f"handoff {release} (python {python})")
    return 0


# --- completion -------------------------------------------------------------


def _tree() -> dict[str, tuple[str, dict[str, str]]]:
    """``{command: (help, {subcommand: help})}`` straight from the parser."""
    from handoff.cli import build_parser

    def _choices(parser: argparse.ArgumentParser):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                helps = {a.dest: a.help or "" for a in action._choices_actions}
                return {name: (helps.get(name, ""), sub) for name, sub in action.choices.items()}
        return {}

    tree: dict[str, tuple[str, dict[str, str]]] = {}
    for name, (help_text, parser) in _choices(build_parser()).items():
        tree[name] = (help_text, {sub: h for sub, (h, _) in _choices(parser).items()})
    return tree


def _clean(text: str) -> str:
    """A description safe inside single quotes and a zsh ``name:desc`` pair."""
    text = (text or "").replace("'", "\u2019").replace(":", " \u2014")
    return re.sub(r"[\"`\[\]]", "", text).strip()


GLOBAL_FLAGS = {"--json": "Print JSON", "--workspace": "Workspace id", "--state-dir": "State directory", "--help": "Help"}


def completion_script(shell: str) -> str:
    tree = _tree()
    commands = " ".join(tree)

    if shell == "bash":
        cases = "\n".join(
            f"        {name}) COMPREPLY=( $(compgen -W \"{' '.join(subs)} --help\" -- \"$cur\") ) ;;"
            for name, (_, subs) in tree.items()
            if subs
        )
        return f"""# bash completion for handoff — eval "$(handoff completion bash)"
_handoff_completion() {{
    local cur cmd="" i
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    for ((i=1; i < COMP_CWORD; i++)); do
        case "${{COMP_WORDS[i]}}" in
            --workspace|--state-dir) ((i++)) ;;
            -*) ;;
            *) cmd="${{COMP_WORDS[i]}}"; break ;;
        esac
    done
    if [[ -z "$cmd" ]]; then
        COMPREPLY=( $(compgen -W "{commands} {' '.join(GLOBAL_FLAGS)}" -- "$cur") )
        return 0
    fi
    case "$cmd" in
{cases}
        *) COMPREPLY=( $(compgen -f -- "$cur") ) ;;
    esac
}}
complete -F _handoff_completion handoff
"""

    if shell == "zsh":
        entries = "\n".join(f"    '{name}:{_clean(help_text)}'" for name, (help_text, _) in tree.items())
        # `_describe` wants "name:description" words; quote each pair.
        cases = "\n".join(
            f"        {name}) local -a sub; sub=({' '.join(repr(f'{s}:{_clean(h)}') for s, h in subs.items())}); _describe 'action' sub ;;"
            for name, (_, subs) in tree.items()
            if subs
        )
        return f"""#compdef handoff
# zsh completion for handoff — eval "$(handoff completion zsh)"
_handoff() {{
  local -a commands
  commands=(
{entries}
  )
  _arguments -C \\
    '--json[Print JSON]' \\
    '--workspace[Workspace id]:id:' \\
    '--state-dir[State directory]:path:_files -/' \\
    '1: :->cmd' \\
    '*:: :->args'
  case $state in
    cmd) _describe 'command' commands ;;
    args)
      case $words[1] in
{cases}
        *) _files ;;
      esac ;;
  esac
}}
compdef _handoff handoff
"""

    lines = ["# fish completion for handoff — handoff completion fish > ~/.config/fish/completions/handoff.fish",
             "complete -c handoff -f"]
    for flag, help_text in GLOBAL_FLAGS.items():
        takes_value = " -r" if flag in ("--workspace", "--state-dir") else ""
        lines.append(f"complete -c handoff -l {flag.lstrip('-')}{takes_value} -d '{_clean(help_text)}'")
    for name, (help_text, subs) in tree.items():
        lines.append(f"complete -c handoff -n '__fish_use_subcommand' -a {name} -d '{_clean(help_text)}'")
        for sub, sub_help in subs.items():
            lines.append(
                f"complete -c handoff -n '__fish_seen_subcommand_from {name}' -a {sub} -d '{_clean(sub_help)}'"
            )
    return "\n".join(lines) + "\n"


def handle_completion(args: argparse.Namespace) -> int:
    _ui.out(completion_script(args.shell))
    return 0
