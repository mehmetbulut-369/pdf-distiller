"""Run every PDF of a folder (or the synthetic weird set) through the app the way a user would.

    python tools/corpus_check.py --weird              # tests/weird_pdfs.py
    python tools/corpus_check.py DIR [--jobs 8]       # any folder of PDFs (e.g. the pdf.js test corpus)

Each file runs in its own process with a timeout, through the HTTP API (so error handling is tested
too): open -> summary -> elements/render page 0 at each tier -> words -> export (+ gray, 4-up)
-> re-open the export. A file passes when it either works end to end or is refused with a known
error code. Anything else (HTTP 500, crash, timeout, unreadable export) is a failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 120
SLOW = 20.0


def worker(path: str) -> dict:
    import io

    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    import pikepdf
    from fastapi.testclient import TestClient

    from app.server import app

    if path.startswith("weird:"):
        import weird_pdfs
        data = weird_pdfs.ALL[path[6:]][0]()
    else:
        data = Path(path).read_bytes()
    c = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    t = time.perf_counter()
    steps = []

    def call(name, r):
        steps.append(name)
        if r.status_code >= 500:
            raise RuntimeError(f"{name}: HTTP {r.status_code} {r.text[:200]}")
        return r

    r = call("open", c.post("/api/open", files={"file": ("x.pdf", data, "application/pdf")}))
    if r.status_code != 200:
        return {"status": "rejected", "code": r.json().get("detail"), "sec": time.perf_counter() - t}
    info = r.json()
    doc, n = info["id"], info["n_pages"]
    pages = sorted({0, n // 2, n - 1})
    tiers = call("tiers", c.get("/api/tiers")).json()
    for tier in ("0", "2", "3"):
        s = tiers[tier]["settings"]
        call(f"summary{tier}", c.post(f"/api/doc/{doc}/summary", json={"settings": s}))
        for p in pages:
            call(f"elements{tier}/{p}", c.post(f"/api/doc/{doc}/elements", json={"settings": s, "page": p}))
            call(f"render{tier}/{p}", c.post(f"/api/doc/{doc}/processed.png", json={"settings": s, "page": p, "width": 300}))
    for p in pages:
        call(f"original/{p}", c.get(f"/api/doc/{doc}/original/{p}.png?w=300"))
    call("words", c.post(f"/api/doc/{doc}/words", json={}))
    s2 = tiers["2"]["settings"]
    for name, settings, expect in (("export", s2, n), ("export_gray_4up", {**s2, "grayscale": True, "nup": 4}, -(-n // 4))):
        r = call(name, c.post(f"/api/doc/{doc}/export", json={"settings": settings}))
        if r.status_code != 200:
            raise RuntimeError(f"{name}: HTTP {r.status_code} {r.text[:200]}")
        out = pikepdf.open(io.BytesIO(r.content))
        if len(out.pages) != expect:
            raise RuntimeError(f"{name}: {len(out.pages)} pages, expected {expect}")
    return {"status": "ok", "pages": n, "sec": time.perf_counter() - t}


def run_one(target: str) -> dict:
    t = time.perf_counter()
    try:
        p = subprocess.run([sys.executable, __file__, "--worker", target], capture_output=True, text=True,
                           timeout=TIMEOUT, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return {"file": target, "status": "timeout", "sec": TIMEOUT}
    last = p.stdout.strip().splitlines()[-1:] or [""]
    try:
        res = json.loads(last[0])
    except json.JSONDecodeError:
        res = {"status": "crash", "error": (p.stderr or p.stdout).strip()[-600:]}
    res.setdefault("sec", time.perf_counter() - t)
    res["file"] = target
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--weird", action="store_true")
    ap.add_argument("--worker")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", default="corpus_report.json")
    a = ap.parse_args()
    if a.worker:
        try:
            res = worker(a.worker)
        except Exception as e:  # noqa: BLE001 - report, don't crash the runner
            import traceback
            res = {"status": "error", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
        print(json.dumps(res, default=str))
        return
    if a.weird:
        sys.path.insert(0, str(ROOT / "tests"))
        import weird_pdfs
        targets = [f"weird:{k}" for k in weird_pdfs.ALL]
    else:
        targets = sorted(str(p) for p in Path(a.folder).rglob("*.pdf"))
    results = []
    with ThreadPoolExecutor(a.jobs) as ex:
        for i, r in enumerate(ex.map(run_one, targets), 1):
            results.append(r)
            if r["status"] not in ("ok", "rejected") or r["sec"] > SLOW:
                err = r.get("error", "")[:160]
                print(f"[{i}/{len(targets)}] {r['status']:8} {r['sec']:6.1f}s {Path(r['file']).name}  {err}", flush=True)
    Path(a.out).write_text(json.dumps(results, indent=1, default=str))
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    slow = sum(r["sec"] > SLOW for r in results)
    print(json.dumps({"total": len(results), **counts, "slow": slow}))


if __name__ == "__main__":
    main()
