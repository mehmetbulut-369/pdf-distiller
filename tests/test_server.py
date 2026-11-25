"""Server layer tests (FastAPI TestClient; needs httpx)."""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("httpx2" if importlib.util.find_spec("httpx2") else "httpx")  # TestClient needs one of them
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


def test_other_websites_cannot_send_files(client):
    pdf = (ROOT / "tests" / "samples" / "light_slides.pdf").read_bytes()
    files = {"file": ("x.pdf", pdf, "application/pdf")}
    assert client.post("/api/open", files=files, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/open", files=files, headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/open", files=files, headers={"Origin": BASE}).status_code == 200  # our own page
    assert client.get("/api/tiers", headers={"Origin": "https://evil.example"}).status_code == 200  # reads stay open


def test_malformed_page_ops_are_rejected_not_crashing(client):
    doc = _open(client)
    assert client.post(f"/api/doc/{doc}/export", json={"ops": [{"rotate": 90}]}).status_code == 422


def test_closed_document_leaves_no_cached_images(client):
    from app import server
    first = _open(client)
    assert client.get(f"/api/doc/{first}/original/0.png?w=200").status_code == 200
    for _ in range(server.MAX_DOCS):
        _open(client)
    assert first not in server._docs
    assert not [k for k in server._png_cache if k.startswith(first + ":")]


def test_broken_profile_does_not_hide_the_others(client, tmp_path, monkeypatch, caplog):
    from app import server
    monkeypatch.setattr(server, "USER_PROFILES", tmp_path)
    (tmp_path / "good.json").write_text("{}", "utf-8")
    (tmp_path / "bad.json").write_text("{not json", "utf-8")
    names = [p["name"] for p in client.get("/api/profiles").json() if not p["builtin"]]
    assert names == ["good"]
    assert "bad.json" in caplog.text


def test_not_a_pdf_is_400(client):
    r = client.post("/api/open", files={"file": ("x.pdf", b"hello", "application/pdf")})
    assert r.status_code == 400


def test_oversized_upload_is_refused(client, monkeypatch):
    from app import server
    monkeypatch.setattr(server, "MAX_PDF_BYTES", 1024)  # keep the test cheap; real default is 300 MB
    big = b"%PDF-1.4\n" + b"0" * 4096
    r = client.post("/api/open", files={"file": ("big.pdf", big, "application/pdf")})
    assert r.status_code == 413
    assert r.json()["detail"] == "error.too_large"


def test_version_names_the_running_code(client):
    from distill_core import __version__
    v = client.get("/api/version").json()
    assert v["version"] == __version__ and v["build"]  # a commit id from source, the BUILD stamp when packaged
