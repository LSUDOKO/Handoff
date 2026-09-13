# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Handoff as a desktop application.

The FastAPI server in a background thread, and a native window (WebKitGTK on
Linux, WebKit on macOS, WebView2 on Windows) pointed at it. No Electron, no
bundler, no second runtime — the whole thing is the Python environment you
already have, which is why it works the same on all three platforms.

    handoff desktop

If no native webview is available, it opens the system browser instead and
says so — a worse window beats no window.
"""

from __future__ import annotations

import socket
import threading
import time
import webbrowser
from contextlib import closing

from handoff import config


def _free_port(preferred: int) -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        if sock.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve(port: int) -> None:
    import uvicorn

    uvicorn.run(
        "handoff.web.server:app", host="127.0.0.1", port=port, log_level="warning"
    )


def _wait_until_up(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def main(port: int | None = None, width: int = 1280, height: int = 860) -> int:
    port = _free_port(port or config.UI_PORT)
    url = f"http://127.0.0.1:{port}"

    server = threading.Thread(target=_serve, args=(port,), daemon=True, name="handoff-server")
    server.start()
    if not _wait_until_up(port):
        print(f"[handoff] server did not come up on {url}")
        return 1

    try:
        import webview
    except ImportError:
        print("[handoff] pywebview not installed; opening in your browser instead")
        print("          pip install pywebview   # for a native window")
        webbrowser.open(url)
        server.join()
        return 0

    try:
        webview.create_window(
            "Handoff",
            url,
            width=width,
            height=height,
            min_size=(720, 520),
            text_select=True,
        )
        webview.start()
    except Exception as exc:
        print(f"[handoff] native window unavailable ({exc}); opening in your browser")
        webbrowser.open(url)
        server.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
