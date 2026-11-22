"""Makes the app icons from app/static/logo.svg (macOS only: Quick Look renders the SVG, iconutil packs it).

    python packaging/make_icons.py

-> packaging/icon.icns, icon.ico, icon-1024.png (light) and app/static/icons/app-{light,dark}.png.

The app icon is the leaf and pen without the page outline, on a full-bleed square: macOS rounds the
corners itself, and an icon with its own transparent margin is shrunk onto a grey plate. A Finder icon
cannot change with the system theme without Xcode's asset compiler, so the .icns is the light one and the
running app swaps its Dock icon to the dark one (app/desktop.py).
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
LOGO = HERE.parent / "app" / "static" / "logo.svg"
STATIC_ICONS = HERE.parent / "app" / "static" / "icons"
SIZE = 1024
ART = 0.74  # share of the canvas the leaf's longer side takes

THEMES = {
    # (background top, background bottom, logo colour overrides)
    "light": ("#FFFFFF", "#ECEFEA", {}),
    "dark": ("#2A2D2B", "#161817", {"--pdl-blue": "#6FA8E8", "--pdl-green": "#7DB33A", "--pdl-rib": "#4E8A17"}),
}


def leaf_svg(colours: dict[str, str]) -> str:
    s = LOGO.read_text("utf-8")
    s = re.sub(r"<\?xml[^>]*\?>\s*", "", s)
    s = re.sub(r"@media \(prefers-color-scheme: dark\) \{.*?\}\s*\}", "", s, flags=re.S)
    s = re.sub(r'<g id="document-page">.*?</g>', "", s, flags=re.S)
    style = ";".join(f"{k}:{v}" for k, v in colours.items())
    return re.sub(r"<svg ", f'<svg style="{style}" ', s, count=1)


def render(svg: str, tmp: Path, name: str, px: int) -> Image.Image:
    f = tmp / f"{name}.svg"
    f.write_text(svg, "utf-8")
    subprocess.run(["qlmanage", "-t", "-s", str(px), "-o", str(tmp), str(f)], check=True, capture_output=True)
    return Image.open(tmp / f"{name}.svg.png").convert("RGBA")


def gradient(top: str, bottom: str) -> Image.Image:
    a = Image.new("RGBA", (1, 2))
    a.putpixel((0, 0), Image.new("RGBA", (1, 1), top).getpixel((0, 0)))
    a.putpixel((0, 1), Image.new("RGBA", (1, 1), bottom).getpixel((0, 0)))
    return a.resize((SIZE, SIZE), Image.BILINEAR)


def icon(theme: str, tmp: Path) -> Image.Image:
    top, bottom, colours = THEMES[theme]
    art = render(leaf_svg(colours), tmp, theme, 2048)
    # Quick Look renders on white; drop it so only the artwork is pasted
    px = art.load()
    for y in range(art.height):
        for x in range(art.width):
            r, g, b, a = px[x, y]
            if r > 250 and g > 250 and b > 250:
                px[x, y] = (0, 0, 0, 0)
    art = art.crop(art.getbbox())
    k = SIZE * ART / max(art.size)
    art = art.resize((round(art.width * k), round(art.height * k)), Image.LANCZOS)
    out = gradient(top, bottom)
    out.alpha_composite(art, ((SIZE - art.width) // 2, (SIZE - art.height) // 2))
    return out


def main() -> None:
    STATIC_ICONS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        imgs = {th: icon(th, t) for th in THEMES}
        for th, im in imgs.items():
            im.resize((512, 512), Image.LANCZOS).save(STATIC_ICONS / f"app-{th}.png", optimize=True)
        big = imgs["light"]
        big.save(HERE / "icon-1024.png", optimize=True)
        imgs["dark"].save(HERE / "icon-1024-dark.png", optimize=True)
        iconset = t / "icon.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            big.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
            big.resize((px * 2, px * 2), Image.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)
        big.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    (HERE / "icon.svg").unlink(missing_ok=True)
    print("icons written")


if __name__ == "__main__":
    main()
