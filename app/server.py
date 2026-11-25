"""Local web server. Listens on 127.0.0.1 only; PDFs never leave the computer.

A thin layer between the UI and the core engine: the logic lives in distill_core,
not here. A new front end (desktop, mobile, cloud) can use the same endpoints.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import unicodedata
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import pikepdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from distill_core import TIERS, DistillDocument, Overrides, PageOp, Settings, __version__, tier_settings  # noqa: E402
from distill_core.engine import EmptyPdf, settings_key  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
BUILTIN_PROFILES = ROOT / "app" / "profiles"
USER_PROFILES = Path.home() / ".pdf-distiller" / "profiles"
PREFS = Path.home() / ".pdf-distiller" / "prefs.json"
# UI preferences kept in a file as well as in the page's localStorage: localStorage belongs to one port, and
# the app moves to another port when 8765 is taken, which would otherwise look like lost settings.
PREF_KEYS = {"lang", "theme", "layout", "savedDots", "creditedDots"}
MAX_PREF_CHARS = 64_000
MAX_DOCS = 8  # one per open window; the oldest is dropped beyond that
# A lecture deck is a few MB; a hostile or runaway upload can be arbitrarily large and is read into
# memory (then copied into each analysis worker). Refused by its announced size before the body is read
# (the multipart parser would otherwise spool all of it to a temporary file first), and again by its real size.
MAX_PDF_MB = int(os.environ.get("PDF_DISTILLER_MAX_MB", "300"))
MAX_PDF_BYTES = MAX_PDF_MB * 1024 * 1024
log = logging.getLogger("pdf_distiller")

app = FastAPI(title="PDF Distiller", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
# DNS rebinding protection: requests are rejected even if another domain resolves to 127.0.0.1.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

_docs: OrderedDict[str, DistillDocument] = OrderedDict()
_png_cache: OrderedDict[str, bytes] = OrderedDict()
_lock = threading.Lock()


class Op(BaseModel):
    src: int
    rotate: Literal[0, 90, 180, 270] = 0  # PDF /Rotate must be a multiple of 90; the UI sends 0-270


class Job(BaseModel):
    settings: dict = {}
    overrides: dict = {}
    ops: list[Op] | None = None
    page: int = 0
    width: int = 900


def _doc(doc_id: str) -> DistillDocument:
    d = _docs.get(doc_id)
    if d is None:
        raise HTTPException(404, "error.doc_not_found")
    return d


def _check_page(d: DistillDocument, page: int):
    if not 0 <= page < d.n_pages:
        raise HTTPException(404, "error.page_not_found")


def _parse(job: Job):
    try:
        return Settings.from_dict(job.settings), Overrides.from_dict(job.overrides)
    except (TypeError, ValueError) as e:  # wrong types from a script or an old saved state: not a server error
        raise HTTPException(400, "error.bad_settings") from e


def _cache_get(key):
    with _lock:  # the UI sends several requests at once; get + move must not interleave with an eviction
        v = _png_cache.get(key)
        if v is not None:
            _png_cache.move_to_end(key)
        return v


def _cache_put(key, v):
    with _lock:
        _png_cache[key] = v
        while len(_png_cache) > 300:
            _png_cache.popitem(last=False)


# ----------------------------------------------------------------------------- pages
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.middleware("http")
async def same_origin_writes(request, call_next):
    """Any web page open in the browser can send a form POST to 127.0.0.1. Browsers name the sending page in
    Origin on such requests, so a write from another origin is refused. Requests without Origin come from
    programs on this computer, not from web pages."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None \
            and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
        return JSONResponse({"detail": "error.foreign_origin"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def announced_size(request, call_next):
    """An upload whose Content-Length is past the limit is refused before a byte of it is read."""
    try:
        n = int(request.headers.get("content-length") or 0)
    except ValueError:
        n = 0
    if request.method == "POST" and request.url.path == "/api/open" and n > MAX_PDF_BYTES + 64 * 1024:
        return JSONResponse({"detail": "error.too_large"}, status_code=413)
    return await call_next(request)


@app.middleware("http")
async def no_stale_static(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"  # no stale UI after an update
    return resp


def _build() -> str:
    """Which code is running: packaged apps carry a BUILD file written by packaging/build.py;
    from source it is the git commit ("-dirty" = uncommitted changes)."""
    f = ROOT / "BUILD"
    if f.is_file():
        return f.read_text("utf-8").strip()
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "describe", "--always", "--dirty"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return f"{out} · source" if out else "source"


BUILD = _build()


@app.get("/api/version")
def version():
    return {"version": __version__, "build": BUILD, "max_mb": MAX_PDF_MB}


@app.get("/api/tiers")
def tiers():
    return {str(t): {"label": label, "settings": tier_settings(t).to_dict()} for t, label in TIERS.items()}


@app.post("/api/open")
def open_pdf(file: UploadFile = File(...)):  # sync: analysis runs in the threadpool, not on the event loop
    data = file.file.read(MAX_PDF_BYTES + 1)  # bounded read: never more than the limit in memory
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "error.too_large")
    return open_document(data, file.filename or "document.pdf")


@app.get("/api/doc/{doc_id}")
def doc_meta(doc_id: str):
    """For a second window that shows a document the server already holds (opened by id, not re-uploaded)."""
    return _meta(doc_id, _doc(doc_id))


def _meta(doc_id: str, doc: DistillDocument) -> dict:
    return {
        "id": doc_id,
        "name": doc.name,
        "n_pages": doc.n_pages,
        "analysis_seconds": round(doc.analysis_seconds, 2),
        "failed_pages": doc.failed_pages,
        "pages": [{"w": p.width, "h": p.height, "rot": p.rotate} for p in doc.pages],
    }


def open_document(data: bytes, name: str) -> dict:
    """Analyse a PDF given as bytes and keep it in memory. The source file is only read, never written."""
    if len(data) > MAX_PDF_BYTES:  # also guards the desktop drag-drop / reopen paths that call this directly
        raise HTTPException(413, "error.too_large")
    if not data.startswith(b"%PDF") and b"%PDF" not in data[:1024]:
        raise HTTPException(400, "error.not_pdf")
    try:
        doc = DistillDocument(data, name)
    except pikepdf.PasswordError as e:
        raise HTTPException(400, "error.pdf_encrypted") from e
    except EmptyPdf as e:
        raise HTTPException(400, "error.pdf_empty") from e
    except Exception as e:  # damaged beyond repair
        log.warning("PDF could not be opened: %s", e)
        raise HTTPException(400, "error.pdf_open_failed") from e
    if doc.n_pages == 0:
        doc.close()
        raise HTTPException(400, "error.pdf_empty")
    try:
        doc.analyze()
    except Exception as e:
        log.exception("analysis failed")
        doc.close()
        raise HTTPException(400, "error.pdf_open_failed") from e
    doc_id = uuid.uuid4().hex[:12]
    with _lock:
        _docs[doc_id] = doc
        evict = list(_docs)[:-MAX_DOCS] if len(_docs) > MAX_DOCS else []
    for old_id in evict:  # closed outside the lock: closing waits for that document's running render
        close_document(old_id)
    return _meta(doc_id, doc)


def close_document(doc_id: str) -> bool:
    """Frees a document and its cached page images. False: it was not open (already closed or dropped)."""
    with _lock:
        doc = _docs.pop(doc_id, None)
        for k in [k for k in _png_cache if k.startswith(doc_id + ":")]:
            del _png_cache[k]
    if doc is None:
        return False
    doc.close()
    return True


@app.delete("/api/doc/{doc_id}")
def close_doc(doc_id: str):
    """The page is done with this document (another one replaced it): give its memory back now."""
    return {"closed": close_document(doc_id)}


@app.get("/api/doc/{doc_id}/original/{page}.png")
def original(doc_id: str, page: int, w: int = 900):
    d = _doc(doc_id)
    _check_page(d, page)
    w = min(max(w, 60), 2400)  # clamp before the cache key: w=2400 and w=9999 are the same image
    key = f"{doc_id}:o:{page}:{w}"
    png = _cache_get(key)
    if png is None:
        png = d.render_original(page, w)
        _cache_put(key, png)
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.post("/api/doc/{doc_id}/processed.png")
def processed(doc_id: str, job: Job):
    d = _doc(doc_id)
    _check_page(d, job.page)
    s, ov = _parse(job)
    w = min(max(job.width, 60), 2400)
    key = f"{doc_id}:p:{job.page}:{w}:{settings_key(s, ov)}"
    png = _cache_get(key)
    if png is None:
        png = d.render_processed(job.page, s, ov, w)
        _cache_put(key, png)
    return Response(png, media_type="image/png")


@app.post("/api/doc/{doc_id}/elements")
def elements(doc_id: str, job: Job):
    d = _doc(doc_id)
    _check_page(d, job.page)
    s, ov = _parse(job)
    return {"page": job.page, "elements": d.page_elements(job.page, s, ov)}


def _ops(d: DistillDocument, job: Job) -> list[PageOp] | None:
    """The pages to print, in order; None = all pages unchanged."""
    if job.ops is None:
        return None
    return [PageOp(o.src, o.rotate) for o in job.ops if 0 <= o.src < d.n_pages]


@app.post("/api/doc/{doc_id}/summary")
def summary(doc_id: str, job: Job):
    d = _doc(doc_id)
    s, ov = _parse(job)
    return {**d.summary(s, ov), "ink": d.ink_estimate(s, ov, ops=_ops(d, job)), "ink_report": d.ink_report(s, ov)}


class WordJob(Job):
    pages: list[int] | None = None
    exclude_removed: bool = True


@app.post("/api/doc/{doc_id}/words")
def words(doc_id: str, job: WordJob):
    d = _doc(doc_id)
    s, ov = _parse(job)
    items = d.word_counts(s, ov, job.pages, job.exclude_removed)
    return {"total": sum(w["n"] for w in items), "unique": len(items), "words": items}


@app.post("/api/doc/{doc_id}/export")
def export(doc_id: str, job: Job):
    d = _doc(doc_id)
    s, ov = _parse(job)
    ops = _ops(d, job)
    if ops is not None and not ops:
        raise HTTPException(400, "error.no_pages")
    data = d.export(s, ov, ops)
    name = (re.sub(r"[^\w\-. ]", "_", Path(d.name).stem)[:80] or "document") + "_print.pdf"
    # HTTP headers must be ASCII: ASCII fallback + UTF-8 real name (RFC 6266 / 5987)
    fallback = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode() or "document_print.pdf"
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"})


# ----------------------------------------------------------------------------- profiles
# Windows refuses these as file names, with any extension ("CON.json" opens the console)
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _safe(name: str) -> str:
    # NFC first: a decomposed "Ö" (O + combining mark) would otherwise lose its mark and become "O"
    n = re.sub(r"[^\w\- ]", "", unicodedata.normalize("NFC", name), flags=re.UNICODE).strip()[:60]
    if not n or n.upper() in _WIN_RESERVED:
        raise HTTPException(400, "error.invalid_profile_name")
    return n


def _profile_file(name: str) -> Path:
    """The user profile file for name. macOS and Windows treat "Exam" and "exam" as one file: an existing
    profile that differs only in case is that profile, so the list never shows a name whose file holds
    another name's settings."""
    n = _safe(name)
    if USER_PROFILES.exists():
        for f in USER_PROFILES.glob("*.json"):
            if unicodedata.normalize("NFC", f.stem).casefold() == n.casefold():
                return f
    return USER_PROFILES / f"{n}.json"


@app.get("/api/profiles")
def list_profiles():
    out = []
    for folder, builtin in ((BUILTIN_PROFILES, True), (USER_PROFILES, False)):
        if folder.exists():
            for f in sorted(folder.glob("*.json")):
                try:
                    out.append({"name": f.stem, "builtin": builtin,
                                "settings": Settings.from_dict(json.loads(f.read_text("utf-8"))).to_dict()})
                except Exception as e:  # one broken file must not hide the others
                    log.warning("profile %s could not be read: %s", f.name, e)
    return out


@app.put("/api/profiles/{name}")
def save_profile(name: str, settings: dict):
    f = _profile_file(name)
    try:
        clean = Settings.from_dict(settings).to_dict()
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "error.bad_settings") from e
    USER_PROFILES.mkdir(parents=True, exist_ok=True)
    write_atomic(f, json.dumps(clean, indent=2, ensure_ascii=False))
    return {"name": f.stem}


@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
    f = _profile_file(name)
    if not f.exists():
        raise HTTPException(404, "error.only_own_profiles")
    f.unlink()
    return {"ok": True}


# ----------------------------------------------------------------------------- preferences
def _read_prefs() -> dict:
    try:
        v = json.loads(PREFS.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: x for k, x in v.items() if k in PREF_KEYS and isinstance(x, str)} if isinstance(v, dict) else {}


@app.get("/api/prefs")
def get_prefs():
    return _read_prefs()


@app.put("/api/prefs")
def put_prefs(changes: dict):
    """Merges {key: string | null}; null removes the key. Only the UI's own keys, never more than 64 KB."""
    prefs = _read_prefs()
    for k, v in changes.items():
        if k not in PREF_KEYS or not (v is None or isinstance(v, str)):
            raise HTTPException(400, "error.bad_settings")
        if v is None:
            prefs.pop(k, None)
        else:
            prefs[k] = v
    text = json.dumps(prefs, ensure_ascii=False)
    if len(text) > MAX_PREF_CHARS:
        raise HTTPException(400, "error.bad_settings")
    write_atomic(PREFS, text)
    return {"ok": True}


def write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file and a rename: a crash or a second window never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, path)
