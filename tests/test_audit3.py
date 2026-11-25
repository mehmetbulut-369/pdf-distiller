"""Fixes from the third audit (2026-11-25): each test failed on the code before the fix."""
from __future__ import annotations

import io
import json
import multiprocessing as mp
import sys
import zlib
from pathlib import Path

import numpy as np
import pikepdf
import pypdfium2 as pdfium
import pytest
from pikepdf import Dictionary, Name

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("httpx")
import make_samples  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import desktop, server  # noqa: E402
from app.server import app  # noqa: E402
from distill_core import DistillDocument, Overrides, PageOp, Settings, render  # noqa: E402

BASE = "http://127.0.0.1"


@pytest.fixture(scope="module")
def client():
    return TestClient(app, base_url=BASE, raise_server_exceptions=False)


def _deck(n=2) -> bytes:
    buf = io.BytesIO()
    make_samples.light_deck(n).save(buf)
    return buf.getvalue()


def _image_page(content: bytes, w: int, h: int, pixels: bytes, cs=Name.DeviceRGB, landscape=True) -> bytes:
    pdf = pikepdf.new()
    pg = pdf.add_blank_page(page_size=(842, 595) if landscape else (595, 842))
    im = pdf.make_stream(zlib.compress(pixels), Type=Name.XObject, Subtype=Name.Image, Width=w, Height=h,
                         ColorSpace=cs, BitsPerComponent=8, Filter=Name.FlateDecode)
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica))
    pg.obj.Resources = Dictionary(XObject=Dictionary(Im0=im), Font=Dictionary(F1=font))
    pg.obj.Contents = pdf.make_stream(content)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- render process
def test_document_comes_back_after_the_child_let_it_go():
    """The child keeps 16 PDFs open. Before: a document it dropped stayed grey for the rest of the session."""
    svc = render.RenderService()
    data = _deck(1)
    try:
        assert svc.png("A", data, 0, 100) is not None
        if svc._broken:
            pytest.skip("this environment cannot start child processes")
        for k in range(render.MAX_OPEN):
            assert svc.png(f"other{k}", data, 0, 100) is not None
        assert svc.png("A", data, 0, 100)[:4] == b"\x89PNG"
    finally:
        svc.close()


def test_in_process_fallback_works_when_no_child_can_start(monkeypatch):
    """Before: _kill() on a process that never started raised, so the fallback never ran."""
    real = mp.get_context("spawn")

    class NoSpawn:
        def __getattr__(self, name):
            return getattr(real, name)

        def Process(self, *a, **k):  # noqa: N802 (mirrors multiprocessing)
            p = real.Process(*a, **k)
            p.start = lambda: (_ for _ in ()).throw(PermissionError("spawn blocked"))
            return p

    monkeypatch.setattr(render.mp, "get_context", lambda *_: NoSpawn())
    svc = render.RenderService()
    data = _deck(1)
    assert svc.png("A", data, 0, 100)[:4] == b"\x89PNG"
    assert svc._broken
    assert svc.pages(data) == 1
    assert isinstance(svc.text("A", data, 0), str)


def test_main_process_never_opens_pdfium(monkeypatch):
    """Text for the word counter and text boxes now comes from the child: a pdfium crash there no longer
    takes the app down. Any pdfium document opened in this process fails the test."""
    def refuse(*a, **k):
        raise AssertionError("pdfium opened in the app's own process")

    monkeypatch.setattr(pdfium, "PdfDocument", refuse)
    d = DistillDocument(_deck(2))
    d.analyze(workers=1)
    s, ov = Settings(), Overrides()
    if render.service()._broken:
        pytest.skip("this environment cannot start child processes")
    words = d.word_counts(s, ov)
    assert words and all(w["n"] > 0 for w in words)
    texts = [e for e in d.page_elements(0, s, ov) if e["kind"] == "text"]
    assert texts and any(e["text"] for e in texts)
    d.close()


# ----------------------------------------------------------------------------- printed output
def test_white_title_on_faded_photo_turns_black():
    """Before: 'fade images' 0.8 printed a white title on a pale grey photo (contrast 1.2:1, unreadable)."""
    data = _image_page(b"q 400 0 0 200 200 300 cm /Im0 Do Q BT 1 1 1 rg /F1 40 Tf 220 400 Td (TITLE) Tj ET",
                       300, 150, bytes([40, 50, 60]) * (300 * 150))
    d = DistillDocument(data)
    d.analyze(workers=1)
    out = d.export(Settings.from_dict({"image_fade": 0.8, "text_mode": "auto"}), Overrides())
    doc = pdfium.PdfDocument(out)
    a = np.asarray(doc[0].render(scale=1).to_pil().convert("L"))[150:200, 215:600]
    doc.close()
    assert a.min() < 60 and a.max() > 180  # dark letters on the faded photo
    d.close()


def test_white_title_on_unfaded_photo_stays_white():
    data = _image_page(b"q 400 0 0 200 200 300 cm /Im0 Do Q BT 1 1 1 rg /F1 40 Tf 220 400 Td (TITLE) Tj ET",
                       300, 150, bytes([40, 50, 60]) * (300 * 150))
    d = DistillDocument(data)
    d.analyze(workers=1)
    out = d.export(Settings.from_dict({"text_mode": "auto"}), Overrides())
    doc = pdfium.PdfDocument(out)
    a = np.asarray(doc[0].render(scale=1).to_pil().convert("L"))[150:200, 215:600]
    doc.close()
    assert a.max() > 240  # still white letters on the dark photo
    d.close()


def test_lossless_image_stays_lossless_in_grayscale():
    """Before: any image over 40 000 px became a JPEG, blurring screenshots of tables and formulas."""
    rng = np.random.default_rng(1)
    px = (rng.integers(0, 2, (300, 800)) * 255).astype(np.uint8)
    rgb = np.repeat(px[:, :, None], 3, axis=2).tobytes()
    data = _image_page(b"q 500 0 0 187 40 300 cm /Im0 Do Q", 800, 300, rgb)
    d = DistillDocument(data)
    d.analyze(workers=1)
    out = pikepdf.open(io.BytesIO(d.export(Settings(grayscale=True), Overrides())))
    [img] = list(out.pages[0].Resources.XObject.values())
    assert img.Filter == Name.FlateDecode
    assert np.array_equal(np.asarray(pikepdf.PdfImage(img).as_pil_image().convert("L")), px)
    d.close()


def test_letter_paper_for_n_up():
    d = DistillDocument(_deck(4))
    d.analyze(workers=1)
    out = pikepdf.open(io.BytesIO(d.export(Settings.from_dict({"nup": 4, "paper": "letter"}), Overrides())))
    w, h = (float(v) for v in out.pages[0].mediabox[2:])
    assert sorted((round(w), round(h))) == [612, 792]
    assert Settings.from_dict({"paper": "tabloid"}).paper == "a4"
    d.close()


# ----------------------------------------------------------------------------- ink and saved dots
def test_saved_ink_counts_deleted_pages_and_n_up():
    d = DistillDocument(_deck(4))
    d.analyze(workers=1)
    s = Settings()
    all_pages = d.ink_estimate(s, Overrides())
    two = d.ink_estimate(s, Overrides(), ops=[PageOp(0), PageOp(1)])
    four_up = d.ink_estimate(Settings.from_dict({"nup": 4}), Overrides())
    assert all_pages["out_pages"] == 4 and two["out_pages"] == 2
    assert two["saved_pages"] > all_pages["saved_pages"]  # deleting pages saves ink, it must not count less
    assert four_up["saved_pages"] > all_pages["saved_pages"]
    d.close()


def test_summary_takes_page_operations(client):
    r = client.post("/api/open", files={"file": ("a.pdf", _deck(3), "application/pdf")})
    doc = r.json()["id"]
    full = client.post(f"/api/doc/{doc}/summary", json={}).json()["ink"]
    one = client.post(f"/api/doc/{doc}/summary", json={"ops": [{"src": 0}]}).json()["ink"]
    assert full["out_pages"] == 3 and one["out_pages"] == 1


def test_region_count_is_cached():
    d = DistillDocument(_deck(3))
    d.analyze(workers=1)
    box = (0.0, 0.0, 1.0, 1.0)
    n = d.region_pages(box)
    d.pages = []  # a second call must not walk the pages again
    assert d.region_pages(box) == n
    d.close()


# ----------------------------------------------------------------------------- server
def test_announced_oversize_upload_is_refused_before_reading(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_PDF_BYTES", 1000)
    r = client.post("/api/open", files={"file": ("big.pdf", b"%PDF-1.4\n" + b"0" * 200_000, "application/pdf")})
    assert r.status_code == 413 and r.json()["detail"] == "error.too_large"


def test_closed_document_is_freed(client):
    r = client.post("/api/open", files={"file": ("a.pdf", _deck(1), "application/pdf")})
    doc = r.json()["id"]
    assert client.delete(f"/api/doc/{doc}").json() == {"closed": True}
    assert doc not in server._docs
    assert client.get(f"/api/doc/{doc}").status_code == 404
    assert client.delete(f"/api/doc/{doc}").json() == {"closed": False}


def test_prefs_survive_in_a_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "PREFS", tmp_path / "prefs.json")
    assert client.get("/api/prefs").json() == {}
    assert client.put("/api/prefs", json={"lang": "tr", "savedDots": "123"}).status_code == 200
    assert client.put("/api/prefs", json={"savedDots": None}).status_code == 200
    assert client.get("/api/prefs").json() == {"lang": "tr"}
    assert client.put("/api/prefs", json={"evil": "x"}).status_code == 400
    assert client.put("/api/prefs", json={"lang": 5}).status_code == 400
    assert client.put("/api/prefs", json={"layout": "x" * 70_000}).status_code == 400
    assert list(tmp_path.iterdir()) == [tmp_path / "prefs.json"]  # no temporary file left behind


def test_foreign_origin_answer_is_translatable(client):
    r = client.put("/api/prefs", json={"lang": "en"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["detail"] == "error.foreign_origin"
    for lang in ("en", "de", "tr"):
        assert "error.foreign_origin" in json.loads((ROOT / "app/static/i18n" / f"{lang}.json").read_text("utf-8"))


# ----------------------------------------------------------------------------- desktop
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "RECENT", tmp_path / "recent.json")
    return desktop.Api("http://127.0.0.1:1/")


def test_desktop_refuses_oversize_file_without_reading_it(api, tmp_path, monkeypatch):
    f = tmp_path / "huge.pdf"
    f.write_bytes(b"%PDF-1.4\n" + b"0" * 5000)
    monkeypatch.setattr(desktop, "MAX_PDF_BYTES", 1000)
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("the file was read"))
    assert api.open(str(f)) == {"error": "error.too_large"}


def test_closing_a_window_frees_its_documents(api, tmp_path, monkeypatch):
    f = tmp_path / "a.pdf"
    f.write_bytes(_deck(1))
    meta = api.open(str(f))
    assert meta["id"] in server._docs and api.docs == {meta["id"]}
    opened = []
    monkeypatch.setattr(desktop, "open_window", lambda url, title="", docs=(), path=None: opened.append(docs))
    api.new_window(meta["id"], "a.pdf")
    assert opened == [(meta["id"],)] and api.docs == set()  # it moved to the new window
    other = desktop.Api("http://127.0.0.1:1/")
    other.docs.add(meta["id"])
    other.release()
    assert meta["id"] not in server._docs


def test_recent_list_is_written_atomically(api, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(_deck(1))
    api.open(str(f))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "recent.json"]


def test_region_count_matches_the_region_rule():
    """The array version of region_pages must count exactly what classify.in_region describes."""
    from distill_core.classify import in_region
    from distill_core.model import TEXT
    d = DistillDocument((ROOT / "tests" / "samples" / "hochschule_slides.pdf").read_bytes())
    d.analyze(workers=1)
    for box in [(0.0, 0.0, 1.0, 1.0), (0.0, 0.85, 1.0, 1.0), (0.1, 0.0, 0.5, 0.3), (0.9, 0.9, 0.95, 0.95)]:
        naive = sum(1 for p in d.pages if any(e.kind == TEXT and in_region(e.view, box) for e in p.elements))
        assert d.region_pages(box) == naive
    d.close()
