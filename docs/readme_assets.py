"""Regenerates the README before/after image and prints the ink-saving table.

    python docs/readme_assets.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from distill_core import DistillDocument, Overrides, tier_settings  # noqa: E402

SAMPLES = ["dark_slides.pdf", "light_slides.pdf", "beamer_slides.pdf", "hochschule_slides.pdf", "mixed_images.pdf"]
TIERS = [(1, "Light"), (2, "Medium"), (3, "Maximum")]


def before_after(doc: DistillDocument, page: int, tier: int, out: Path, width: int = 640) -> None:
    a = Image.open(io.BytesIO(doc.render_original(page, width)))
    b = Image.open(io.BytesIO(doc.render_processed(page, tier_settings(tier), Overrides(), width)))
    gap = 24
    img = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height)), (230, 233, 237))
    img.paste(a, (0, 0))
    img.paste(b, (a.width + gap, 0))
    d = ImageDraw.Draw(img)
    for x0, x1 in ((0, a.width), (a.width + gap, img.width)):
        d.rectangle((x0, 0, x1 - 1, img.height - 1), outline=(150, 155, 160))
    img.save(out, optimize=True)


def main() -> None:
    print("| Sample | " + " | ".join(name for _, name in TIERS) + " |")
    print("|---|" + "---:|" * len(TIERS))
    for name in SAMPLES:
        doc = DistillDocument((ROOT / "tests" / "samples" / name).read_bytes())
        doc.analyze()
        cells = [f"{doc.ink_estimate(tier_settings(t), Overrides())['saving'] * 100:.0f}%" for t, _ in TIERS]
        print(f"| `{name}` | " + " | ".join(cells) + " |")
        if name == "dark_slides.pdf":
            before_after(doc, 1, 2, ROOT / "docs" / "before-after.png")


if __name__ == "__main__":
    main()
