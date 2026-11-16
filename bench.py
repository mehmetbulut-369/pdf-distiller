"""Hız testi.   python bench.py [dosya.pdf]

Dosya verilmezse 500 sayfalık sentetik ders slaytı destesi üretilir (her sayfa
benzersiz içerik akışı; her 3 sayfada bir benzersiz fotoğraf; her sayfada ~300
vektör öğeli grafik ile ağırlaştırılmış).
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
    import pikepdf
    import make_samples

    pdf = make_samples.dark_deck(pages)
    for i, page in enumerate(pdf.pages):  # ağır vektör grafik ekle (gerçek grafik/diyagram yükü)
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
        print(f"sentetik PDF üretildi: {len(data) / 1e6:.1f} MB, {time.perf_counter() - t:.1f} sn")

    doc = DistillDocument(data)
    t = time.perf_counter()
    doc.analyze()
    n_el = sum(len(p.elements) for p in doc.pages)
    print(f"analiz:   {doc.n_pages} sayfa, {n_el} öğe, {time.perf_counter() - t:.2f} sn")

    ov = Overrides()
    for name, s in [("kademe 1", tier_settings(1)), ("kademe 2", tier_settings(2)),
                    ("kademe 3", tier_settings(3)),
                    ("kademe 1 + gri + N-up 4", Settings.from_dict({**tier_settings(1).to_dict(),
                                                                     "grayscale": True, "nup": 4}))]:
        t = time.perf_counter()
        out = doc.export(s, ov)
        print(f"{name:26s} dışa aktarma: {time.perf_counter() - t:.2f} sn  ({len(out) / 1e6:.1f} MB)")
    t = time.perf_counter()
    est = doc.ink_estimate(tier_settings(1), ov)
    print(f"mürekkep tahmini: {time.perf_counter() - t:.2f} sn  -> tasarruf %{est['saving'] * 100:.0f}")
    t = time.perf_counter()
    doc.render_processed(10, tier_settings(2), ov)
    print(f"tek sayfa önizleme: {(time.perf_counter() - t) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
