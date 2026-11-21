"""Starts PDF Distiller.

    python run.py            -> opens in the browser
    python run.py --window   -> opens in a desktop window (needs: pip install pywebview)

Packaged builds (PyInstaller) always open a desktop window; closing it stops the server.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port found")


def main():
    ap = argparse.ArgumentParser(description="PDF Distiller")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--window", action="store_true", help="desktop window instead of the browser")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if getattr(sys, "frozen", False):
        # windowed builds have no console; uvicorn's log formatter fails on a None stream
        sys.stdout = sys.stdout or open(os.devnull, "w")  # noqa: SIM115
        sys.stderr = sys.stderr or open(os.devnull, "w")  # noqa: SIM115
        if not a.no_browser:
            a.window = True

    import uvicorn

    from app.server import app

    port = free_port(a.port)
    url = f"http://127.0.0.1:{port}/"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    if a.window:
        try:
            import webview  # noqa: F401  (availability check; app.desktop uses it)
        except ImportError:
            print("For a desktop window:  pip install pywebview   (opening in the browser for now)")
            a.window = False

    if a.window:
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.05)
        from app.desktop import start
        start(url)  # one window per document; blocks until the last one is closed
        server.should_exit = True
        return

    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)), daemon=True).start()
    print(f"PDF Distiller is running at {url}   (Ctrl+C to quit)")
    server.run()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # analysis uses worker processes; required in frozen builds
    main()
