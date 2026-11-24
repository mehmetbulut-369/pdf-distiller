"""Desktop bridge: open by path, recent list, missing files. No window is created here."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import desktop  # noqa: E402
from app.server import app  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "RECENT", tmp_path / "recent.json")
    return desktop.Api("http://127.0.0.1:1/")


def test_open_by_path_adds_to_recent_and_leaves_file_untouched(api, tmp_path):
    src = tmp_path / "slides.pdf"
    src.write_bytes((ROOT / "tests" / "samples" / "dark_slides.pdf").read_bytes())
    before = src.read_bytes()
    meta = api.open(str(src))
    assert meta["n_pages"] > 0 and "error" not in meta
    assert src.read_bytes() == before
    [item] = api.recent()
    assert item["path"] == str(src) and item["missing"] is False and item["thumb"].startswith("data:image/png")
    # the second window loads the same document by id
    r = TestClient(app, base_url="http://127.0.0.1").get(f"/api/doc/{meta['id']}")
    assert r.status_code == 200 and r.json()["n_pages"] == meta["n_pages"]


def test_moved_file_is_reported_not_crashing(api, tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes((ROOT / "tests" / "samples" / "light_slides.pdf").read_bytes())
    api.open(str(src))
    src.rename(tmp_path / "b.pdf")
    assert api.recent()[0]["missing"] is True
    assert api.open(str(src)) == {"error": "recent.missing"}
    api.forget(str(src))
    assert api.recent() == []


def test_not_a_pdf(api, tmp_path):
    f = tmp_path / "x.pdf"
    f.write_text("hello")
    assert api.open(str(f)) == {"error": "error.not_pdf"}
    assert api.recent() == []
