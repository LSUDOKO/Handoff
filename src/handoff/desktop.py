# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Handoff as a desktop application.

The FastAPI server on a background thread, and a native window (Qt or
WebKitGTK on Linux, WebKit on macOS, WebView2 on Windows) pointed at it. No
Electron, no bundler, no second runtime — the whole thing is the Python
environment you already have, which is why it works the same on all three.

    handoff desktop

What makes it feel like an app rather than a browser tab: it remembers its
size and position, reopens on the page you were on, and if Handoff is
already running it opens a window onto that instance instead of a second
scheduler. If no native webview is available it opens the system browser
and says so — a worse window beats no window.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import webbrowser
from contextlib import closing
from pathlib import Path

from handoff import config

WINDOW_STATE = "window.json"


def _state_path() -> Path:
    return Path(config.STATE_DIR) / WINDOW_STATE


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        _state_path().parent.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(state))
    except OSError:
        pass


def _port_open(port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _is_handoff(port: int) -> bool:
    """Is the thing on this port our own server?"""
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return r.status == 200 and b"handoff" in r.read().lower()
    except Exception:
        return False


def _free_port(preferred: int) -> int:
    if not _port_open(preferred):
        return preferred
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve(port: int) -> None:
    import uvicorn

    uvicorn.run("handoff.web.server:app", host="127.0.0.1", port=port, log_level="warning")


def _wait_until_up(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.2)
    return False


def main(port: int | None = None, width: int = 1360, height: int = 880) -> int:
    preferred = port or config.UI_PORT
    state = _load_state()

    # Second launch: attach to the running instance rather than start another
    # scheduler that would fire every cron twice.
    if _port_open(preferred) and _is_handoff(preferred):
        actual = preferred
        server = None
        print(f"[handoff] already running on :{actual} — opening a window onto it")
    else:
        actual = _free_port(preferred)
        server = threading.Thread(target=_serve, args=(actual,), daemon=True, name="handoff-server")
        server.start()
        if not _wait_until_up(actual):
            print(f"[handoff] server did not come up on :{actual}")
            return 1

    last_page = state.get("page") or "/"
    url = f"http://127.0.0.1:{actual}{last_page if last_page.startswith('/') else '/'}"

    try:
        import webview
    except ImportError:
        print("[handoff] pywebview not installed; opening in your browser instead")
        print("          pip install 'handoff[desktop]'   # for a native window")
        webbrowser.open(url)
        if server:
            server.join()
        return 0

    try:
        window = webview.create_window(
            "Handoff",
            url,
            width=int(state.get("width", width)),
            height=int(state.get("height", height)),
            x=state.get("x"),
            y=state.get("y"),
            min_size=(760, 540),
            text_select=True,
            background_color="#f5f3f1",
        )

        def remember() -> None:
            try:
                page = window.get_current_url() or url
                path = page.split(f":{actual}", 1)[1] if f":{actual}" in page else "/"
                _save_state(
                    {
                        "width": window.width,
                        "height": window.height,
                        "x": window.x,
                        "y": window.y,
                        "page": path if path.startswith("/") and not path.startswith("/welcome") else "/",
                    }
                )
            except Exception:
                pass

        window.events.closing += remember
        window.events.resized += lambda *_: remember()
        window.events.moved += lambda *_: remember()
        webview.start()
    except Exception as exc:
        print(f"[handoff] native window unavailable ({exc}); opening in your browser")
        webbrowser.open(url)
        if server:
            server.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
