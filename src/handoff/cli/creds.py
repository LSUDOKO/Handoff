# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff credentials` — connect services without a secret ever hitting the screen.

Values are read with ``getpass`` or taken from an environment variable you
name, stored, verified against the live service, and from then on shown only
masked. There is no command that prints one back.
"""

from __future__ import annotations

import argparse
import getpass
import os

from handoff.cli import _ui


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("credentials", help="Connect, check or forget service credentials")
    p.set_defaults(handle=handle)
    c = p.add_subparsers(dest="creds_command", metavar="<action>")

    c.add_parser("list", help="Every provider and whether it is connected (the default)")

    p_set = c.add_parser("set", help="Store a credential, read hidden from the terminal")
    p_set.add_argument("provider", help="groq, anthropic, linear, slack, slack_webhook, github")
    p_set.add_argument("--from-env", default="", metavar="VAR", help="Take the value from this variable")
    p_set.add_argument("--label", default="")

    p_check = c.add_parser("check", help="Verify stored credentials against the real services")
    p_check.add_argument("provider", nargs="?", default="")

    p_forget = c.add_parser("forget", help="Delete a stored credential")
    p_forget.add_argument("provider")

    c.add_parser("gmail", help="Sign in to Gmail in the browser (the MCP server's own OAuth)")


def _row(cred) -> dict:
    return {
        "provider": cred.provider,
        "label": cred.label,
        "status": cred.status.value,
        "masked": cred.masked,
        "fingerprint": cred.fingerprint,
        "last_error": cred.last_error,
        "last_checked": cred.last_checked.isoformat() if cred.last_checked else "",
    }


def handle(args: argparse.Namespace) -> int:
    from handoff.platform import credentials as creds
    from handoff.store import get_store

    action = args.creds_command or "list"

    if action == "list":
        rows = creds.catalogue(_ui.workspace())
        _ui.emit(
            rows,
            lambda: _ui.table(
                "Credentials",
                ["provider", "label", "status", "value", "note"],
                [
                    [r["provider"], r["label"], r["status"], r["masked"], r["last_error"] or r["hint"]]
                    for r in rows
                ],
            ),
        )
        return 0

    if action == "set":
        spec = creds.provider(args.provider)
        if spec is None:
            raise KeyError(f"Unknown provider '{args.provider}' — one of {', '.join(creds.PROVIDERS)}")
        if args.provider == "gmail":
            raise ValueError("Gmail has no key to paste; run `handoff credentials gmail` to sign in")
        if args.from_env:
            secret = os.environ.get(args.from_env, "")
            if not secret:
                raise KeyError(f"{args.from_env} is not set in this shell")
        else:
            secret = getpass.getpass(f"{spec.label} {spec.kind.value.replace('_', ' ')}: ")
        secret = secret.strip()
        if not secret:
            raise ValueError("nothing entered")
        if spec.prefix and not secret.startswith(spec.prefix):
            _ui.warn(f"{spec.label} values usually start with {spec.prefix!r}; storing it anyway")
        cred = creds.connect(args.provider, secret, _ui.workspace(), args.label)
        if _ui.json_mode():
            _ui.print_json(_row(cred))
        elif cred.status.value == "connected":
            _ui.ok(f"{spec.label} connected ({cred.masked})")
        else:
            _ui.warn(f"{spec.label} stored but {cred.status.value.replace('_', ' ')}: {cred.last_error or 'not verified'}")
        return 0 if cred.status.value == "connected" else 1

    if action == "check":
        from handoff import doctor

        store = get_store()
        stored = [c for c in store.list_credentials(_ui.workspace()) if c.secret]
        if args.provider:
            if args.provider == "gmail":
                result = doctor.check_gmail()
                _ui.emit(result, lambda: _ui.kv_table("Gmail", result))
                return 0 if result["status"] == doctor.OK else 1
            stored = [c for c in stored if c.provider == args.provider]
            if not stored:
                raise KeyError(f"No stored credential for '{args.provider}'")
        checked = [_row(creds.verify(c.credential_id)) for c in stored]
        _ui.emit(
            checked,
            lambda: _ui.table(
                "Checked",
                ["provider", "status", "value", "detail"],
                [[r["provider"], r["status"], r["masked"], r["last_error"]] for r in checked],
            ),
        )
        if not checked and not _ui.json_mode():
            _ui.dim("no stored credentials — `handoff credentials set <provider>`")
        return 1 if any(r["status"] == "needs_attention" for r in checked) else 0

    if action == "forget":
        store = get_store()
        matches = [c for c in store.list_credentials(None) if c.provider == args.provider]
        if not matches:
            raise KeyError(f"No stored credential for '{args.provider}'")
        for cred in matches:
            creds.disconnect(cred.credential_id)
        if _ui.json_mode():
            _ui.print_json({"forgot": args.provider, "count": len(matches)})
        else:
            _ui.ok(f"forgot {args.provider}")
        return 0

    if action == "gmail":
        status = creds.gmail_status()
        if not _ui.json_mode():
            if status["signed_in"]:
                _ui.dim("already signed in; signing in again refreshes the token")
            _ui.dim("opening the Google consent screen in your browser…")
        result = creds.run_gmail_auth()
        if _ui.json_mode():
            _ui.print_json(result)
        elif result.get("ok"):
            _ui.ok(result.get("message", "signed in"))
        else:
            _ui.fail(result.get("error", "sign-in failed"))
        return 0 if result.get("ok") else 1

    return 2
