"""Guards against hostile files and malformed requests (pre-release QA, 2026-11-25)."""
from __future__ import annotations

import importlib.util
import io
import os
import signal
import sys
import zlib
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Dictionary, Name

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("httpx2" if importlib.util.find_spec("httpx2") else "httpx")  # TestClient needs one of them
import make_samples  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.server import app  # noqa: E402
from distill_core import DistillDocument, Overrides, Settings, interpreter, render  # noqa: E402
from distill_core.images import process_images  # noqa: E402
from distill_core.imgfeat import load_small  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)


def _deck() -> bytes:
    buf = io.BytesIO()
    make_samples.light_deck(2).save(buf)
    return buf.getvalue()


def _pdf(content: bytes, img=None) -> bytes:
    p = pikepdf.new()
    p.add_blank_page(page_size=(595, 842))
    if img is not None:
        p.pages[0].Resources = Dictionary(XObject=Dictionary(Im0=img(p)))
    s = pikepdf.Stream(p, zlib.compress(content))
    s.Filter = Name.FlateDecode
    p.pages[0].Contents = s
    buf = io.BytesIO()
    p.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- request validation
@pytest.mark.parametrize("body", [
    {"settings": {"large_threshold": "abc"}},
    {"settings": {"nup": "x"}},
    {"settings": {"grayscale": "false"}},
    {"overrides": {"elements": [1, 2]}},
    {"overrides": {"signatures": "x"}},
])
def test_wrong_types_are_400_not_500(client, body):
    doc = client.post("/api/open", files={"file": ("a.pdf", _deck())}).json()["id"]
    r = client.post(f"/api/doc/{doc}/summary", json=body)
    assert r.status_code == 400 and r.json()["detail"] == "error.bad_settings"


def test_nan_threshold_is_refused():
    with pytest.raises(ValueError):
        Settings.from_dict({"large_threshold": float("nan")})


def test_override_values_other_than_remove_keep_are_dropped():
    ov = Overrides.from_dict({"elements": {"a": "remove", "b": {"x": 1}, "c": "keep"}})
    assert ov.elements == {"a": "remove", "c": "keep"}


@pytest.mark.parametrize("name", ["CON", "nul", "COM1", "lpt9"])
def test_windows_reserved_profile_names(client, name):
    assert client.put(f"/api/profiles/{name}", json={}).status_code == 400


# ----------------------------------------------------------------------------- hostile content
def test_operator_bomb_page_is_kept_unchanged(monkeypatch):
    monkeypatch.setattr(interpreter, "MAX_OPS", 1000)
    d = DistillDocument(_pdf(b"10 10 m 20 20 l S\n" * 2000))
    d.analyze(workers=1)
    assert d.failed_pages == [0]
    out = pikepdf.open(io.BytesIO(d.export(Settings.from_dict({"remove_backgrounds": True}), Overrides())))
    assert len(out.pages) == 1


def test_content_size_bomb_page_is_kept_unchanged(monkeypatch):
    monkeypatch.setattr(interpreter, "MAX_CONTENT_BYTES", 10_000)
    d = DistillDocument(_pdf(b"0 0 1 1 re f\n" * 2000))
    d.analyze(workers=1)
    assert d.failed_pages == [0]


def _huge_gray(p):
    w = 9500  # 90 M pixels: over MAX_DECODE_PIXELS, a few hundred KB compressed
    img = pikepdf.Stream(p, zlib.compress(b"\x00" * (w * w), 9))
    img.Type, img.Subtype, img.Width, img.Height = Name.XObject, Name.Image, w, w
    img.ColorSpace, img.BitsPerComponent, img.Filter = Name.DeviceGray, 8, Name.FlateDecode
    return img


def test_decompression_bomb_image_is_not_decoded():
    data = _pdf(b"q 595 0 0 842 0 0 cm /Im0 Do Q", _huge_gray)
    pdf = pikepdf.open(io.BytesIO(data))
    img = pdf.pages[0].Resources.XObject.Im0
    assert load_small(pdf, img.objgen) is None
    assert process_images(pdf, [img.objgen], grayscale=True, fade=0.5) == 0


# ----------------------------------------------------------------------------- render process
def test_renderer_restarts_after_crash_and_marks_hung_pages():
    svc = render.RenderService()
    data = _deck()
    try:
        assert svc.png("k", data, 0, 200)[:4] == b"\x89PNG"
        if svc._broken:
            pytest.skip("this environment cannot start child processes")
        svc._proc.kill()  # what a native crash looks like from the parent
        svc._proc.join()
        assert svc.png("k", data, 1, 200)[:4] == b"\x89PNG"  # restarted, document re-sent
        if not hasattr(signal, "SIGSTOP"):
            return  # Windows: no way to freeze the child from here; the crash path above is covered
        os.kill(svc._proc.pid, signal.SIGSTOP)  # a page that keeps pdfium busy, deterministically
        svc.timeout = 1.0
        assert svc.png("k", data, 0, 200) is None
        assert svc.failed("k", 0)
        svc.timeout = render.RENDER_TIMEOUT
        assert svc.png("k", data, 0, 200) is None  # not tried again
        assert svc.png("k", data, 1, 200)[:4] == b"\x89PNG"  # a fresh child serves the other pages
    finally:
        svc.close()


def test_document_shows_placeholder_when_page_cannot_be_drawn(monkeypatch):
    d = DistillDocument(_deck())
    d.analyze(workers=1)
    monkeypatch.setattr(render.RenderService, "png", lambda *a, **k: None)
    png = d.render_original(0, 300)
    assert png[:4] == b"\x89PNG"
    png = d.render_processed(0, Settings(), Overrides(), 300)
    assert png[:4] == b"\x89PNG"
