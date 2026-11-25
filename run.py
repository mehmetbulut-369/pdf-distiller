"""Starts PDF Distiller.

    python run.py            -> opens in the browser
    python run.py --window   -> opens in a desktop window (needs: pip install pywebview)
    python run.py --window a.pdf b.pdf  -> and opens these files, one window each

Packaged builds (PyInstaller) always open a desktop window; closing it stops the server.
"""
from __future__ import annotations

import argparse
import faulthandler
import logging
import logging.handlers
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
LOG_DIR = Path.home() / ".pdf-distiller"


def setup_logging() -> Path | None:
    """Warnings and errors go to ~/.pdf-distiller/log.txt (two files of 1 MB at most), so a user who reports a
    problem has something to send. Only what went wrong is written: file names, never document content.
    A native crash (pdfium, qpdf) writes its stack to crash.txt via faulthandler."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG_DIR / "log.txt", maxBytes=1_000_000, backupCount=1,
                                                 encoding="utf-8")
    except OSError:
        return None  # read-only home: run without a log rather than not at all
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.WARNING)
    logging.getLogger("pdf_distiller").setLevel(logging.INFO)  # plus one start line per run
    try:
        faulthandler.enable(open(LOG_DIR / "crash.txt", "a", encoding="utf-8"))  # noqa: SIM115 (open for the process)
    except OSError:
        pass
    sys.excepthook = lambda *exc: logging.getLogger("pdf_distiller").critical("unhandled error", exc_info=exc)
    return LOG_DIR / "log.txt"


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port found")


# Shown when the local server cannot start. Written for people, in the three UI languages.
START_ERROR = """<body style="font:15px/1.5 -apple-system,Segoe UI,sans-serif;padding:24px;color:#222">
<p><b>PDF Distiller could not start.</b> Another program may be blocking it. Please restart your computer
and try again. If it happens again, send us the file <code>~/.pdf-distiller/log.txt</code>.</p>
<p lang="de"><b>PDF Distiller konnte nicht starten.</b> Ein anderes Programm blockiert es vielleicht. Starten Sie
den Computer neu und versuchen Sie es noch einmal. Wenn es wieder passiert, schicken Sie uns die Datei
<code>~/.pdf-distiller/log.txt</code>.</p>
<p lang="tr"><b>PDF Distiller açılamadı.</b> Başka bir program engelliyor olabilir. Bilgisayarınızı yeniden
başlatıp tekrar deneyin. Yine olursa <code>~/.pdf-distiller/log.txt</code> dosyasını bize gönderin.</p></body>"""


def main():
    ap = argparse.ArgumentParser(description="PDF Distiller")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--window", action="store_true", help="desktop window instead of the browser")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("files", nargs="*", help="PDFs to open (desktop window only)")
    a, _ = ap.parse_known_args()  # macOS may add its own arguments (-psn_...) to a launched app
    setup_logging()
    logging.getLogger("pdf_distiller").info("start (frozen=%s, %s)", getattr(sys, "frozen", False), sys.platform)
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
        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        deadline = time.monotonic() + 30
        while not server.started and th.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:  # port taken in the meantime, blocked by security software, ...
            logging.getLogger("pdf_distiller").critical("local server did not start on port %d", port)
            from app.desktop import show_start_error
            show_start_error(START_ERROR)
            sys.exit(1)
        from app.desktop import start
        start(url, a.files)  # one window per document; blocks until the last one is closed
        server.should_exit = True
        return

    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)), daemon=True).start()
    print(f"PDF Distiller is running at {url}   (Ctrl+C to quit)")
    server.run()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # analysis uses worker processes; required in frozen builds
    main()
