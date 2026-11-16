"""Speed benchmark.   python bench.py [file.pdf]

Without a file, a synthetic 500-page lecture deck is generated (a unique content
stream per page, a unique photo every 3rd page, and a ~300-element vector chart
on every page as extra load).
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from distill_core import DistillDocument, Overrides, Settings, tier_settings  # noqa: E402


def synthetic(pages=500) -> bytes:
    import make_samples

    pdf = make_samples.dark_deck(pages)
    for page in pdf.pages:  # add heavy vector graphics (realistic chart/diagram load)
        extra = "".join(f"q {0.2 + (k % 7) / 10:.2f} 0.5 0.6 rg {300 + (k * 13) % 380} {50 + (k * 7) % 250} 6 6 re f Q\n"
                        for k in range(300))
        page.obj.Contents = pdf.make_stream(page.obj.Contents.read_bytes() + extra.encode())
    b = io.BytesIO()
    pdf.save(b)
    return b.getvalue()


def main():
    if len(sys.argv) > 1:
        data = Path(sys.argv[1]).read_bytes()
    else:
        t = time.perf_counter()
        data = synthetic()
        print(f"synthetic PDF generated: {len(data) / 1e6:.1f} MB, {time.perf_counter() - t:.1f} s")

    doc = DistillDocument(data)
    t = time.perf_counter()
    doc.analyze()
    n_el = sum(len(p.elements) for p in doc.pages)
    print(f"analysis: {doc.n_pages} pages, {n_el} elements, {time.perf_counter() - t:.2f} s")

    ov = Overrides()
    for name, s in [("Light", tier_settings(1)), ("Medium", tier_settings(2)),
                    ("Maximum", tier_settings(3)),
                    ("Light + gray + 4-up", Settings.from_dict({**tier_settings(1).to_dict(),
                                                                     "grayscale": True, "nup": 4}))]:
        t = time.perf_counter()
        out = doc.export(s, ov)
        print(f"{name:26s} export: {time.perf_counter() - t:.2f} s  ({len(out) / 1e6:.1f} MB)")
    t = time.perf_counter()
    est = doc.ink_estimate(tier_settings(1), ov)
    print(f"ink estimate: {time.perf_counter() - t:.2f} s  -> saving {est['saving'] * 100:.0f}%")
    t = time.perf_counter()
    doc.render_processed(10, tier_settings(2), ov)
    print(f"single-page preview: {(time.perf_counter() - t) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
