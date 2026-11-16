"""Lokal web sunucusu. Sadece 127.0.0.1'de dinler; PDF'ler bilgisayardan çıkmaz.

Arayüz ile çekirdek motor arasındaki ince katman: iş mantığı burada değil,
distill_core içinde. Yeni bir arayüz (masaüstü, mobil, bulut) aynı uç noktaları
kullanabilir.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

import unicodedata
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from distill_core import TIERS, DistillDocument, Overrides, PageOp, Settings, tier_settings  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
BUILTIN_PROFILES = ROOT / "profiles"
USER_PROFILES = Path.home() / ".pdf-distiller" / "profiles"
MAX_DOCS = 4
log = logging.getLogger("pdf_distiller")

app = FastAPI(title="PDF Distiller", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
# DNS rebinding koruması: başka bir alan adı 127.0.0.1'e çözülse bile istekler reddedilir.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

_docs: "OrderedDict[str, DistillDocument]" = OrderedDict()
_png_cache: "OrderedDict[str, bytes]" = OrderedDict()
_lock = threading.Lock()


class Job(BaseModel):
    settings: dict = {}
    overrides: dict = {}
    ops: list[dict] | None = None
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
    return Settings.from_dict(job.settings), Overrides.from_dict(job.overrides)


def _cache_get(key):
    v = _png_cache.get(key)
    if v is not None:
        _png_cache.move_to_end(key)
    return v


def _cache_put(key, v):
    _png_cache[key] = v
    while len(_png_cache) > 300:
        _png_cache.popitem(last=False)


# ----------------------------------------------------------------------------- sayfalar
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.middleware("http")
async def no_stale_static(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"  # güncellemeden sonra eski arayüz görünmesin
    return resp


@app.get("/api/tiers")
def tiers():
    return {str(t): {"label": label, "settings": tier_settings(t).to_dict()} for t, label in TIERS.items()}


@app.post("/api/open")
def open_pdf(file: UploadFile = File(...)):  # sync: analiz iş parçacığında koşar, olay döngüsünü kilitlemez
    data = file.file.read()
    if not data.startswith(b"%PDF") and b"%PDF" not in data[:1024]:
        raise HTTPException(400, "error.not_pdf")
    try:
        doc = DistillDocument(data, file.filename or "document.pdf")
    except Exception as e:  # şifreli veya bozuk PDF
        log.warning("PDF could not be opened: %s", e)
        raise HTTPException(400, "error.pdf_open_failed") from e
    doc.analyze()
    doc_id = uuid.uuid4().hex[:12]
    with _lock:
        _docs[doc_id] = doc
        while len(_docs) > MAX_DOCS:
            _, old = _docs.popitem(last=False)
            old.close()
    return {
        "id": doc_id,
        "name": doc.name,
        "n_pages": doc.n_pages,
        "analysis_seconds": round(doc.analysis_seconds, 2),
        "pages": [{"w": p.width, "h": p.height, "rot": p.rotate} for p in doc.pages],
    }


@app.get("/api/doc/{doc_id}/original/{page}.png")
def original(doc_id: str, page: int, w: int = 900):
    d = _doc(doc_id)
    _check_page(d, page)
    key = f"{doc_id}:o:{page}:{w}"
    png = _cache_get(key)
    if png is None:
        png = d.render_original(page, min(max(w, 60), 2400))
        _cache_put(key, png)
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.post("/api/doc/{doc_id}/processed.png")
def processed(doc_id: str, job: Job):
    d = _doc(doc_id)
    _check_page(d, job.page)
    s, ov = _parse(job)
    h =hashlib.md5(json.dumps([s.to_dict(), ov.to_dict()], sort_keys=True).encode()).hexdigest()
    key = f"{doc_id}:p:{job.page}:{job.width}:{h}"
    png = _cache_get(key)
    if png is None:
        png = d.render_processed(job.page, s, ov, min(max(job.width, 60), 2400))
        _cache_put(key, png)
    return Response(png, media_type="image/png")


@app.post("/api/doc/{doc_id}/elements")
def elements(doc_id: str, job: Job):
    d = _doc(doc_id)
    _check_page(d, job.page)
    s, ov = _parse(job)
    return {"page": job.page, "elements": d.page_elements(job.page, s, ov)}


@app.post("/api/doc/{doc_id}/summary")
def summary(doc_id: str, job: Job):
    d = _doc(doc_id)
    s, ov = _parse(job)
    return {**d.summary(s, ov), "ink": d.ink_estimate(s, ov)}


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
    ops = None
    if job.ops is not None:
        ops = [PageOp(int(o["src"]), int(o.get("rotate", 0))) for o in job.ops]
        ops = [o for o in ops if 0 <= o.src < d.n_pages]
        if not ops:
            raise HTTPException(400, "error.no_pages")
    data = d.export(s, ov, ops)
    name = (re.sub(r"[^\w\-. ]", "_", Path(d.name).stem)[:80] or "document") + "_print.pdf"
    # HTTP başlıkları ASCII olmalı: ASCII yedek ad + UTF-8 asıl ad (RFC 6266 / 5987)
    fallback = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode() or "document_print.pdf"
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"})


# ----------------------------------------------------------------------------- profiller
def _safe(name: str) -> str:
    n = re.sub(r"[^\w\- ]", "", name, flags=re.UNICODE).strip()[:60]
    if not n:
        raise HTTPException(400, "error.invalid_profile_name")
    return n


@app.get("/api/profiles")
def list_profiles():
    out = []
    for folder, builtin in ((BUILTIN_PROFILES, True), (USER_PROFILES, False)):
        if folder.exists():
            for f in sorted(folder.glob("*.json")):
                try:
                    out.append({"name": f.stem, "builtin": builtin,
                                "settings": Settings.from_dict(json.loads(f.read_text("utf-8"))).to_dict()})
                except Exception:
                    pass
    return out


@app.put("/api/profiles/{name}")
def save_profile(name: str, settings: dict):
    n = _safe(name)
    USER_PROFILES.mkdir(parents=True, exist_ok=True)
    (USER_PROFILES / f"{n}.json").write_text(
        json.dumps(Settings.from_dict(settings).to_dict(), indent=2, ensure_ascii=False), "utf-8")
    return {"name": n}


@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
    f = USER_PROFILES / f"{_safe(name)}.json"
    if not f.exists():
        raise HTTPException(404, "error.only_own_profiles")
    f.unlink()
    return {"ok": True}
