"""Pathological PDFs (tests/weird_pdfs.py) through the HTTP API: each one either works end to end
or is refused with a known error code. Never a 500, never an unreadable export."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pikepdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("httpx")
import weird_pdfs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.server import app  # noqa: E402

REJECT_CODES = {"error.not_pdf", "error.pdf_open_failed", "error.pdf_encrypted", "error.pdf_empty"}
EXPECTED_CODE = {"encrypted_user_password": "error.pdf_encrypted", "zero_pages": "error.pdf_empty",
                 "empty_file": "error.not_pdf", "not_a_pdf": "error.not_pdf"}


@pytest.fixture(scope="module")
def client():
    return TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)


@pytest.mark.parametrize("name", list(weird_pdfs.ALL))
def test_weird_pdf(client, name):
    build, expect = weird_pdfs.ALL[name]
    r = client.post("/api/open", files={"file": (f"{name}.pdf", build(), "application/pdf")})
    assert r.status_code < 500, r.text
    if expect == "reject":
        assert r.status_code == 400
        assert r.json()["detail"] == EXPECTED_CODE.get(name, r.json()["detail"])
        assert r.json()["detail"] in REJECT_CODES
        return
    if r.status_code == 400 and expect == "ok-or-reject":
        assert r.json()["detail"] in REJECT_CODES
        return
    assert r.status_code == 200, r.text
    doc, n = r.json()["id"], r.json()["n_pages"]
    s = client.get("/api/tiers").json()["2"]["settings"]
    for path, body in ((f"/api/doc/{doc}/summary", {"settings": s}),
                       (f"/api/doc/{doc}/elements", {"settings": s, "page": n - 1}),
                       (f"/api/doc/{doc}/processed.png", {"settings": s, "page": 0, "width": 200}),
                       (f"/api/doc/{doc}/words", {})):
        assert client.post(path, json=body).status_code == 200, path
    assert client.get(f"/api/doc/{doc}/original/0.png?w=200").status_code == 200
    for settings, pages in ((s, n), ({**s, "grayscale": True, "nup": 4}, -(-n // 4))):
        r = client.post(f"/api/doc/{doc}/export", json={"settings": settings})
        assert r.status_code == 200, r.text
        assert len(pikepdf.open(io.BytesIO(r.content)).pages) == pages
