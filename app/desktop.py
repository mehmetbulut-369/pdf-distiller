"""Desktop-only glue (pywebview): open files by path, the recent-files list, one window per document.

Nothing here is reachable over HTTP. The page calls these methods through pywebview's JS bridge, so no
web page can make the local server read an arbitrary path. Files are only read, never written.

Each window has its own Api object, so it knows which documents it shows; closing the window frees them.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from app.server import MAX_PDF_BYTES, _docs, close_document, open_document, write_atomic

RECENT = Path.home() / ".pdf-distiller" / "recent.json"
MAX_RECENT = 8
log = logging.getLogger("pdf_distiller")
_url = ""                   # the app's address; set by start()
_windows: list = []         # [(window, Api)] of the open windows


def _load() -> list[dict]:
    try:
        items = json.loads(RECENT.read_text("utf-8"))
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    write_atomic(RECENT, json.dumps(items[:MAX_RECENT], ensure_ascii=False))


class Api:
    def __init__(self, url: str, window=None):
        self._url = url
        self._window = window
        self.docs: set = set()  # documents this window shows; freed when it closes

    def choose(self):
        import webview
        w = self._window or webview.active_window()
        res = w.create_file_dialog(webview.FileDialog.OPEN, file_types=("PDF (*.pdf)",))
        return res[0] if res else None

    def open(self, path: str) -> dict:
        p = Path(path)
        if not p.is_file():
            return {"error": "recent.missing"}
        try:
            if p.stat().st_size > MAX_PDF_BYTES:  # before reading: a 10 GB file must not be loaded to find out
                return {"error": "error.too_large"}
            meta = open_document(p.read_bytes(), p.name)
        except HTTPException as e:
            return {"error": e.detail}
        except OSError:  # no permission, or the disk went away while reading
            return {"error": "recent.missing"}
        self.docs.add(meta["id"])
        doc = _docs.get(meta["id"])
        thumb = base64.b64encode(doc.render_original(0, 160)).decode() if doc else ""
        items = [i for i in _load() if i.get("path") != str(p)]
        items.insert(0, {"path": str(p), "name": p.name, "pages": meta["n_pages"], "opened": time.time(),
                         "thumb": f"data:image/png;base64,{thumb}" if thumb else ""})
        _save(items)
        return meta

    def show(self, doc_id: str) -> None:
        """The page shows this document (e.g. one it uploaded): free it with the window."""
        self.docs.add(doc_id)

    def recent(self) -> list[dict]:
        return [{**i, "missing": not Path(i.get("path", "")).is_file()} for i in _load()]

    def forget(self, path: str) -> None:
        _save([i for i in _load() if i.get("path") != path])

    def clear_recent(self) -> None:
        _save([])

    def new_window(self, doc_id: str, title: str) -> None:
        self.docs.discard(doc_id)  # it belongs to the new window now
        open_window(f"{self._url}?doc={doc_id}", title, docs=(doc_id,))

    def release(self) -> None:
        for doc_id in list(self.docs):
            close_document(doc_id)
        self.docs.clear()


def _hook_drop(window) -> None:
    """The browser hides a dropped file's path; pywebview hands it to a Python-side drop handler only."""
    from webview.dom import DOMEventHandler

    def on_drop(e):
        files = (e.get("dataTransfer") or {}).get("files") or []
        path = next((f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")), None)
        if path:
            window.evaluate_js(f"window.__dropPath && window.__dropPath({json.dumps(path)})")

    window.dom.document.events.drop += DOMEventHandler(on_drop)


def _send_path(window, path: str) -> None:
    """Hands a file to the page as if it had been dropped; queued if the page is still starting."""
    window.evaluate_js(f"(window.__dropPath ? window.__dropPath({json.dumps(path)}) : "
                       f"(window.__pendingPaths = (window.__pendingPaths || []).concat([{json.dumps(path)}])))")


def open_window(url: str, title: str = "PDF Distiller", docs=(), path: str | None = None):
    import webview
    api = Api(_url or url.split("?")[0])
    api.docs.update(docs)
    w = webview.create_window(title, url, width=1440, height=900, js_api=api)
    api._window = w
    _windows.append((w, api))

    def loaded():
        _hook_drop(w)
        if path:
            _send_path(w, path)

    def closed():
        api.release()
        _windows[:] = [x for x in _windows if x[0] is not w]

    w.events.loaded += loaded
    w.events.closed += closed
    return w


def open_paths(paths) -> None:
    """Files given by the system (Finder "Open With", Dock drop): the first goes to an empty window if there
    is one, each other one to a new window. Called off the main thread (pywebview's rule for new windows)."""
    for path in paths:
        free = next((w for w, a in _windows if not a.docs), None)
        if free is not None:
            _send_path(free, path)
        else:
            open_window(_url, path=path)


def _accept_system_files() -> None:
    """macOS delivers "open this file" as an event to the app delegate, at launch and while running."""
    try:
        import objc
        from webview.platforms.cocoa import BrowserView
    except ImportError:
        return

    def application_openFiles_(self, app, filenames):
        log.info("system asks to open %d file(s)", len(filenames))
        # pywebview only creates a window from a thread other than the main one, where this runs
        threading.Thread(target=open_paths, args=([str(f) for f in filenames],), daemon=True).start()
        app.replyToOpenOrPrint_(0)  # NSApplicationDelegateReplySuccess

    try:
        objc.classAddMethods(BrowserView.AppDelegate, [
            objc.selector(application_openFiles_, selector=b"application:openFiles:", signature=b"v@:@@")])
    except Exception as e:  # a pywebview version without this delegate: opening from Finder just isn't offered
        log.warning("could not accept files from the system: %s", e)


def _follow_system_theme() -> None:
    """macOS: the Dock icon follows the system's light/dark setting while the app runs.

    A Finder icon cannot switch on its own without Xcode's asset compiler; the bundle's .icns is the light one.
    """
    try:
        from AppKit import NSApplication, NSDistributedNotificationCenter, NSImage, NSUserDefaults
        from PyObjCTools.AppHelper import callAfter
    except ImportError:
        return
    icons = Path(__file__).resolve().parent / "static" / "icons"

    def apply(_note=None):
        dark = NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle") == "Dark"
        img = NSImage.alloc().initWithContentsOfFile_(str(icons / f"app-{'dark' if dark else 'light'}.png"))
        if img is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(img)

    def install():
        apply()
        NSDistributedNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            "AppleInterfaceThemeChangedNotification", None, None, lambda n: callAfter(apply, n))

    callAfter(install)  # AppKit calls belong on the main thread, where pywebview runs its loop


def start(url: str, paths=()) -> None:
    """Blocks until the last window is closed. paths: PDFs to open (command line / "Open With")."""
    global _url
    import sys

    import webview
    _url = url
    paths = list(paths)
    if sys.platform == "darwin":
        _accept_system_files()
        paths = []  # AppKit itself turns file arguments into "open" events (application:openFiles:)
    open_window(url, path=paths[0] if paths else None)
    for p in paths[1:]:
        open_window(url, path=p)
    # pywebview defaults to private mode: localStorage (language, theme, panel widths, saved dots) would be
    # wiped on every start
    webview.start(_follow_system_theme if sys.platform == "darwin" else None,
                  private_mode=False, storage_path=str(RECENT.parent / "webview"))


def show_start_error(message: str) -> None:
    """The server could not start: say so in a window instead of leaving the user with nothing."""
    import webview
    webview.create_window("PDF Distiller", html=message, width=560, height=300)
    webview.start()
