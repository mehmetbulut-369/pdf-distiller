"""Server layer tests (FastAPI TestClient; needs httpx)."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("httpx")
import make_samples  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.server import app  # noqa: E402

BASE = "http://127.0.0.1"


@pytest.fixture(scope="module")
def client():
    return TestClient(app, base_url=BASE, raise_server_exceptions=False)


def _open(client, name="slides.pdf"):
    buf = io.BytesIO()
    make_samples.light_deck(3).save(buf)
    pdf = buf.getvalue()
    r = client.post("/api/open", files={"file": (name, pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.parametrize("name", ["Vorlesung_Übung.pdf", "Ders_şğı.pdf", "講義.pdf"])
def test_export_non_ascii_filename(client, name):
    doc = _open(client, name)
    r = client.post(f"/api/doc/{doc}/export", json={})
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    cd = r.headers["content-disposition"]
    cd.encode("ascii")  # header must stay ASCII
    utf8 = cd.split("filename*=UTF-8''", 1)[1]
    assert unquote(utf8) == Path(name).stem + "_print.pdf"


def test_page_out_of_range_is_404(client):
    doc = _open(client)
    assert client.post(f"/api/doc/{doc}/elements", json={"page": 999}).status_code == 404
    assert client.post(f"/api/doc/{doc}/processed.png", json={"page": -1}).status_code == 404
    assert client.get(f"/api/doc/{doc}/original/999.png").status_code == 404


def test_export_with_only_invalid_pages_is_400(client):
    doc = _open(client)
    assert client.post(f"/api/doc/{doc}/export", json={"ops": [{"src": 99}]}).status_code == 400
    assert client.post(f"/api/doc/{doc}/export", json={"ops": []}).status_code == 400
    r = client.post(f"/api/doc/{doc}/export", json={"ops": [{"src": 99}, {"src": 1}]})
    assert r.status_code == 200


def test_foreign_host_rejected(client):
    assert client.get("/api/tiers", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/tiers", headers={"Host": "localhost:8765"}).status_code == 200


def test_not_a_pdf_is_400(client):
    r = client.post("/api/open", files={"file": ("x.pdf", b"hello", "application/pdf")})
    assert r.status_code == 400
