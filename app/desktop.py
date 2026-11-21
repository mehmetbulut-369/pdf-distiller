"""Desktop-only glue (pywebview): open files by path, the recent-files list, one window per document.

Nothing here is reachable over HTTP. The page calls these methods through pywebview's JS bridge, so no
web page can make the local server read an arbitrary path. Files are only read, never written.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from fastapi import HTTPException

from app.server import _docs, open_document

RECENT = Path.home() / ".pdf-distiller" / "recent.json"
MAX_RECENT = 8
_api = None  # set by start(); every window shares it


def _load() -> list[dict]:
    try:
        items = json.loads(RECENT.read_text("utf-8"))
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    RECENT.parent.mkdir(parents=True, exist_ok=True)
    RECENT.write_text(json.dumps(items[:MAX_RECENT], ensure_ascii=False), "utf-8")


class Api:
    def __init__(self, url: str):
        self._url = url

    def choose(self):
        import webview
        res = webview.active_window().create_file_dialog(webview.FileDialog.OPEN, file_types=("PDF (*.pdf)",))
        return res[0] if res else None

    def open(self, path: str) -> dict:
        p = Path(path)
        if not p.is_file():
            return {"error": "recent.missing"}
        try:
            meta = open_document(p.read_bytes(), p.name)
        except HTTPException as e:
            return {"error": e.detail}
        thumb = base64.b64encode(_docs[meta["id"]].render_original(0, 160)).decode()
        items = [i for i in _load() if i.get("path") != str(p)]
        items.insert(0, {"path": str(p), "name": p.name, "pages": meta["n_pages"], "opened": time.time(),
                         "thumb": f"data:image/png;base64,{thumb}"})
        _save(items)
        return meta

    def recent(self) -> list[dict]:
        return [{**i, "missing": not Path(i.get("path", "")).is_file()} for i in _load()]

    def forget(self, path: str) -> None:
        _save([i for i in _load() if i.get("path") != path])

    def clear_recent(self) -> None:
        _save([])

    def new_window(self, doc_id: str, title: str) -> None:
        open_window(f"{self._url}?doc={doc_id}", title)


def _hook_drop(window) -> None:
    """The browser hides a dropped file's path; pywebview hands it to a Python-side drop handler only."""
    from webview.dom import DOMEventHandler

    def on_drop(e):
        files = (e.get("dataTransfer") or {}).get("files") or []
        path = next((f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")), None)
        if path:
            window.evaluate_js(f"window.__dropPath && window.__dropPath({json.dumps(path)})")

    window.dom.document.events.drop += DOMEventHandler(on_drop)


def open_window(url: str, title: str = "PDF Distiller"):
    import webview
    w = webview.create_window(title, url, width=1440, height=900, js_api=_api)
    w.events.loaded += lambda: _hook_drop(w)
    return w


def start(url: str) -> None:
    """Blocks until the last window is closed."""
    global _api
    import webview
    _api = Api(url)
    open_window(url)
    # pywebview defaults to private mode: localStorage (language, theme, panel widths, saved dots) would be
    # wiped on every start
    webview.start(private_mode=False, storage_path=str(RECENT.parent / "webview"))
