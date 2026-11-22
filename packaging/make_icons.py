"""Makes the app icons from app/static/logo.svg (macOS only: Quick Look renders the SVG, iconutil packs it).

    python packaging/make_icons.py   ->  packaging/icon.icns, packaging/icon.ico, packaging/icon.svg

The logo sits on a light rounded tile, as macOS expects of an app icon; the light colours are used,
since a Dock icon does not follow the page theme.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
LOGO = HERE.parent / "app" / "static" / "logo.svg"


def icon_svg() -> str:
    s = LOGO.read_text("utf-8")
    s = re.sub(r"<\?xml[^>]*\?>\s*", "", s)
    s = re.sub(r"@media \(prefers-color-scheme: dark\) \{.*?\}\s*\}", "", s, flags=re.S)  # light only
    s = re.sub(r'<svg [^>]*>', '<svg x="162" y="162" width="700" height="700" viewBox="0 0 1024 1024">', s, count=1)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">\n'
            '<defs><linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#E9EDF1"/></linearGradient></defs>\n'
            '<rect x="100" y="100" width="824" height="824" rx="185" fill="url(#tile)" stroke="#D5DBE1" stroke-width="2"/>\n'
            f"{s}\n</svg>\n")


def main() -> None:
    svg = HERE / "icon.svg"
    svg.write_text(icon_svg(), "utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        subprocess.run(["qlmanage", "-t", "-s", "1024", "-o", str(t), str(svg)], check=True, capture_output=True)
        big = Image.open(t / "icon.svg.png").convert("RGBA")
        assert big.size == (1024, 1024), big.size
        iconset = t / "icon.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            big.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
            big.resize((px * 2, px * 2), Image.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)
        big.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        shutil.copy(t / "icon.svg.png", HERE / "icon-1024.png")
    print("icon.icns, icon.ico, icon-1024.png written")


if __name__ == "__main__":
    main()
