"""Fixes from the fourth audit (senior QA, 2026-11-25): each test failed on the code before the fix."""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import unicodedata
import zlib
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Name

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("httpx2" if importlib.util.find_spec("httpx2") else "httpx")  # TestClient needs one of them
import make_samples  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import server  # noqa: E402
from app.server import app  # noqa: E402
from distill_core import DistillDocument, Overrides, PageOp, Settings, render  # noqa: E402
from distill_core.pageops import apply_page_ops  # noqa: E402

BASE = "http://127.0.0.1"


@pytest.fixture(scope="module")
def client():
    return TestClient(app, base_url=BASE, raise_server_exceptions=False)


def _deck(n=2) -> bytes:
    buf = io.BytesIO()
    make_samples.light_deck(n).save(buf)
    return buf.getvalue()


def _ocr_page(words_per_line=12, lines=55) -> bytes:
    """A scanned page's text layer: every word in its own BT/ET at its own position."""
    p = pikepdf.new()
    f = make_samples.font(p)
    p.add_blank_page(page_size=(595, 842))
    step = 540 // words_per_line
    body = b"".join(b"BT /F1 9 Tf %d %d Td (wort%d) Tj ET\n" % (30 + w * step, 800 - k * 14, w)
                    for k in range(lines) for w in range(words_per_line))
    s = pikepdf.Stream(p, zlib.compress(body))
    s.Filter = Name.FlateDecode
    p.pages[0].Contents = s
    p.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=f))
    buf = io.BytesIO()
    p.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- layer list speed
def test_layer_list_reads_a_pages_text_in_one_call(monkeypatch):
    """Before: one call (page + text layer built anew) per text box; 825 OCR words took 1.5 s."""
    d = DistillDocument(_ocr_page())
    d.analyze(workers=1)
    svc = render.service()
    calls = {"text": 0, "texts": 0}
    real_text, real_texts = svc.text, svc.texts
    monkeypatch.setattr(svc, "text", lambda *a, **k: (calls.__setitem__("text", calls["text"] + 1), real_text(*a, **k))[1])
    monkeypatch.setattr(svc, "texts", lambda *a, **k: (calls.__setitem__("texts", calls["texts"] + 1), real_texts(*a, **k))[1])
    els = d.page_elements(0, Settings(), Overrides())
    texts = [e for e in els if e["kind"] == "text"]
    assert len(texts) > 600
    assert calls == {"text": 0, "texts": 1}
    assert all(e["text"].startswith("wort") for e in texts)
    d.close()


def test_word_counter_still_subtracts_removed_text_boxes():
    d = DistillDocument(_ocr_page(words_per_line=2, lines=3))
    d.analyze(workers=1)
    first = next(e for e in d.pages[0].elements if e.kind == "text")
    ov = Overrides.from_dict({"elements": {first.id: "remove"}})
    n_all = sum(w["n"] for w in d.word_counts(Settings(), Overrides()))
    n_kept = sum(w["n"] for w in d.word_counts(Settings(), ov))
    assert n_all - n_kept == 1
    d.close()


# ----------------------------------------------------------------------------- texts people read
LANGS = ("en", "de", "tr")
I18N = {lang: json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text("utf-8")) for lang in LANGS}
# Wording the project rules forbid: it blames the program, or shows a technical code
BLAMING = re.compile(r"not found|nicht gefunden|bulunamad|request failed|anfrage fehlgeschlagen|istek başarısız|"
                     r"invalid|ungültig|geçersiz|\{status\}", re.I)


@pytest.mark.parametrize("lang", LANGS)
def test_error_texts_say_what_happened_not_that_something_failed(lang):
    bad = {k: v for k, v in I18N[lang].items() if k.startswith(("error.", "load.failed")) and BLAMING.search(v)}
    assert bad == {}


@pytest.mark.parametrize("lang", LANGS)
def test_closed_document_text_names_the_reason(lang):
    assert "8" in I18N[lang]["error.doc_not_found"]  # at most 8 open documents: the usual reason


# ----------------------------------------------------------------------------- page rotation
def test_rotation_other_than_quarter_turns_is_refused(client):
    doc = client.post("/api/open", files={"file": ("a.pdf", _deck(), "application/pdf")}).json()
    r = client.post(f"/api/doc/{doc['id']}/export", json={"ops": [{"src": 0, "rotate": 45}]})
    assert r.status_code == 422  # before: 200, with /Rotate 45 written into the PDF
    r = client.post(f"/api/doc/{doc['id']}/export", json={"ops": [{"src": 0, "rotate": 270}, {"src": 1, "rotate": 90}]})
    assert r.status_code == 200
    assert [int(p.obj.Rotate) for p in pikepdf.open(io.BytesIO(r.content)).pages] == [270, 90]


def test_core_refuses_rotation_other_than_quarter_turns():
    pdf = pikepdf.open(io.BytesIO(_deck()))
    with pytest.raises(ValueError):
        apply_page_ops(pdf, [PageOp(0, 45)])


# ----------------------------------------------------------------------------- profile names
def test_profile_names_differing_only_in_case_are_one_profile(client, monkeypatch, tmp_path):
    """macOS and Windows store "Sinav" and "sinav" in one file. Before: the list said "Sinav" and showed the
    settings saved as "sinav"."""
    monkeypatch.setattr(server, "USER_PROFILES", tmp_path)
    client.put("/api/profiles/Sinav", json={"grayscale": True})
    r = client.put("/api/profiles/sinav", json={"grayscale": False})
    assert r.json() == {"name": "Sinav"}
    mine = [p for p in client.get("/api/profiles").json() if not p["builtin"]]
    assert [(p["name"], p["settings"]["grayscale"]) for p in mine] == [("Sinav", False)]
    assert client.delete("/api/profiles/SINAV").status_code == 200
    assert [p for p in client.get("/api/profiles").json() if not p["builtin"]] == []


def test_decomposed_umlaut_keeps_its_letter(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "USER_PROFILES", tmp_path)
    r = client.put("/api/profiles/" + unicodedata.normalize("NFD", "Ödev"), json={})
    assert r.json() == {"name": "Ödev"}  # before: "Odev"


# ----------------------------------------------------------------------------- image cache
def test_widths_past_the_limit_share_one_cache_entry(client):
    doc = client.post("/api/open", files={"file": ("a.pdf", _deck(1), "application/pdf")}).json()
    before = len(server._png_cache)
    for w in (2400, 2450, 9999):
        assert client.get(f"/api/doc/{doc['id']}/original/0.png?w={w}").status_code == 200
    assert len(server._png_cache) - before == 1  # before: 3 copies of the same 2400 px image


# ----------------------------------------------------------------------------- test setup
def test_test_client_needs_no_deprecated_http_library():
    """Starlette 1.10 warns that TestClient on httpx is deprecated; the next release may drop it."""
    if sys.version_info < (3, 11):
        pytest.skip("httpx2 needs Python 3.11+; older setups keep httpx")
    import starlette.testclient
    assert starlette.testclient.httpx.__name__ == "httpx2"
