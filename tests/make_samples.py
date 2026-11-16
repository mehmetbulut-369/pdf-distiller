"""Generates synthetic lecture-slide PDFs for tests (mimicking the typical structure of real slides).

    python tests/make_samples.py            -> samples into samples/
    python tests/make_samples.py --pages 500 -> samples/bench_500.pdf (benchmark)
"""
from __future__ import annotations

import argparse
import io
import math
import random
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name
from PIL import Image, ImageDraw

W, H = 720.0, 405.0  # 16:9 slide
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"


def jpeg_image(pdf, img: Image.Image):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return pdf.make_stream(buf.getvalue(), Type=Name.XObject, Subtype=Name.Image, Width=img.width,
                           Height=img.height, ColorSpace=Name.DeviceRGB, BitsPerComponent=8,
                           Filter=Name.DCTDecode)


def logo(pdf):
    img = Image.new("RGB", (240, 100), (200, 30, 40))
    d = ImageDraw.Draw(img)
    d.ellipse((10, 10, 90, 90), fill=(255, 210, 0))
    d.rectangle((110, 35, 230, 65), fill=(255, 255, 255))
    return jpeg_image(pdf, img)


def photo(pdf, seed: int):
    rnd = random.Random(seed)
    img = Image.new("RGB", (480, 320))
    px = img.load()
    a, b, c = rnd.random() * 6, rnd.random() * 6, rnd.random() * 6
    for y in range(320):
        for x in range(0, 480, 2):
            v = (int(127 + 120 * math.sin(x / 40 + a)), int(127 + 120 * math.sin(y / 30 + b)),
                 int(127 + 120 * math.sin((x + y) / 50 + c)))
            px[x, y] = v
            px[x + 1, y] = v
    return jpeg_image(pdf, img)


def font(pdf):
    return pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica,
                                        Encoding=Name.WinAnsiEncoding))


def text(x, y, size, s, rgb=None):
    col = "%.3f %.3f %.3f rg " % rgb if rgb else ""
    s = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT {col}/F1 {size} Tf {x} {y} Td ({s}) Tj ET\n"


def add_page(pdf, content: str, xobjects: dict, fnt, rotate=0, extra_res=None):
    res = Dictionary(Font=Dictionary(F1=fnt), XObject=Dictionary(**xobjects))
    if extra_res:
        for k, v in extra_res.items():
            res[k] = v
    page = Dictionary(Type=Name.Page, MediaBox=Array([0, 0, W, H]), Resources=res,
                      Contents=pdf.make_stream(content.encode("latin-1")))
    if rotate:
        page.Rotate = rotate
    pdf.pages.append(pikepdf.Page(page))


def dark_deck(n=12) -> pikepdf.Pdf:
    pdf = pikepdf.new()
    fnt, lg = font(pdf), logo(pdf)
    for i in range(n):
        xo = {"Logo": lg}
        c = "q 0.10 0.12 0.20 rg 0 0 720 405 re f Q\n"           # dark full-page background
        c += "q 0.20 0.40 0.80 rg 0 360 720 45 re f Q\n"          # repeated title band
        c += "q 60 0 0 25 645 370 cm /Logo Do Q\n"                # repeated logo
        c += text(30, 375, 22, f"Vorlesung 3 - Folie {i + 1}", (1, 1, 1))
        for k, line in enumerate(["Grundlagen der Wahrscheinlichkeit", "Bayes-Theorem und Anwendungen",
                                  "Beispiel: Klassifikation mit Naive Bayes"]):
            c += text(40, 310 - k * 32, 16, "- " + line, (0.92, 0.92, 0.95))
        if i % 3 == 1:                                             # large content photo
            xo["Photo"] = photo(pdf, i)
            c += "q 300 0 0 200 390 60 cm /Photo Do Q\n"
        if i % 4 == 2:                                             # dark info box, white text
            x = 40 + (i * 37) % 120
            c += f"q 0.55 0.08 0.10 rg {x} 70 300 70 re f Q\n"
            c += text(x + 12, 100, 14, "Merke: P(A|B) = P(B|A)P(A)/P(B)", (1, 1, 1))
        if i % 5 == 3:                                             # small bar chart
            for b in range(6):
                hgt = 20 + (b * 23 + i * 7) % 90
                c += f"q 0.30 0.75 0.45 rg {420 + b * 40} 60 28 {hgt} re f Q\n"
        c += "q 0.6 0.6 0.7 RG 1 w 30 30 m 690 30 l S Q\n"        # repeated bottom rule
        c += text(660, 12, 10, str(i + 1), (0.7, 0.7, 0.75))
        add_page(pdf, c, xo, fnt)
    return pdf


def light_deck(n=10) -> pikepdf.Pdf:
    pdf = pikepdf.new()
    fnt, lg = font(pdf), logo(pdf)
    band = Image.new("RGB", (720, 50))
    d = ImageDraw.Draw(band)
    for x in range(720):
        d.line((x, 0, x, 50), fill=(20 + x // 6, 80, 160))
    band_img = jpeg_image(pdf, band)
    for i in range(n):
        xo = {"Logo": lg, "Band": band_img}
        c = "q 1 1 1 rg 0 0 720 405 re f Q\n"                     # white background (must not be removed)
        c += "q 720 0 0 50 0 355 cm /Band Do Q\n"                 # repeated coloured band image
        c += "q 50 0 0 21 20 10 cm /Logo Do Q\n"                  # bottom logo
        c += text(30, 372, 22, f"Kapitel {i + 1}: Datenstrukturen", (1, 1, 1))
        for k in range(4):
            c += text(40, 310 - k * 30, 15, f"- Punkt {k + 1}: Listen, Baeume und Graphen", (0.1, 0.1, 0.1))
        if i % 2 == 0:
            xo["Photo"] = photo(pdf, 100 + i)
            c += "q 280 0 0 190 410 80 cm /Photo Do Q\n"
        if i % 3 == 1:                                             # large light-coloured box
            c += "q 0.80 0.88 1.0 rg 30 40 660 140 re f Q\n"
            c += text(45, 150, 14, "Definition: Ein Graph G = (V, E)", (0.0, 0.0, 0.3))
        add_page(pdf, c, xo, fnt)
    return pdf


def form_deck(n=8) -> pikepdf.Pdf:
    """Beamer-like: theme in a shared Form XObject, with a shading background. One page is rotated."""
    pdf = pikepdf.new()
    fnt = font(pdf)
    func = Dictionary(FunctionType=2, Domain=Array([0, 1]), C0=Array([0.05, 0.1, 0.3]),
                      C1=Array([0.3, 0.5, 0.9]), N=1)
    shading = pdf.make_indirect(Dictionary(ShadingType=2, ColorSpace=Name.DeviceRGB,
                                           Coords=Array([0, 0, 0, 405]), Function=func, Extend=Array([True, True])))
    theme_content = ("q 0 0 720 405 re W n /Sh0 sh Q\n"
                     "q 0.95 0.75 0.1 rg 0 0 720 8 re f Q\n"
                     "q 0.9 0.9 0.9 rg 600 20 100 30 re f Q\n")
    theme = pdf.make_stream(theme_content.encode(), Type=Name.XObject, Subtype=Name.Form,
                            BBox=Array([0, 0, 720, 405]),
                            Resources=Dictionary(Shading=Dictionary(Sh0=shading)))
    for i in range(n):
        c = "/Theme Do\n"
        c += text(30, 360, 24, f"Beamer Folie {i + 1}", (1, 1, 1))
        c += text(40, 300, 16, "Text auf Verlaufshintergrund", (0.85, 0.9, 1.0))
        c += "q 0.2 0.2 0.2 rg 40 120 200 80 re f Q\n"             # dark box, light text (must be kept)
        c += text(50, 150, 14, "Kasten mit hellem Text", (1, 1, 0.8))
        add_page(pdf, c, {"Theme": theme}, fnt, rotate=90 if i == n - 1 else 0)
    return pdf


def hhn_deck(n=6) -> pikepdf.Pdf:
    """Imitates a university template: blue "Informatik 1" top left, white "Informatik 1" in a blue band,
    a body title that again contains "Informatik 1"; a footer split into one Tj per word
    (like a PowerPoint export) and a section line with page numbers. Font with a widths table."""
    pdf = pikepdf.new()
    fnt = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica,
                                       Encoding=Name.WinAnsiEncoding, FirstChar=32, LastChar=255,
                                       Widths=Array([556] * 224)))
    lg = logo(pdf)
    cw = 0.556  # glyph width per em (same as Widths)

    def words(x, y, size, s, rgb):
        out = ""
        for w in s.split(" "):
            out += text(x, y, size, w, rgb)
            x += (len(w) + 1) * cw * size
        return out

    for i in range(n):
        c = "q 1 1 1 rg 0 0 720 405 re f Q\n"
        c += text(30, 370, 16, "Informatik 1", (0.15, 0.4, 0.75))                 # top-left title
        c += "q 70 0 0 28 610 355 cm /Logo Do Q\n"
        c += "q 0.35 0.6 0.9 rg 18 318 684 22 re f Q\n"                          # blue band
        c += text(310, 324, 13, "Informatik 1", (1, 1, 1))
        body = ["Vorlesung Informatik 1", "Hochschule Heilbronn", "Bachelor ESE & KID"] if i == 0 else \
               [f"Kapitel {i}: Algorithmen und Informatik 1", "Komplexitaet und Sortieren"]
        for k, line in enumerate(body):
            c += text(200, 270 - k * 26, 15, line, (0, 0, 0))
        c += text(20, 12, 7, "22/09/2026", (0, 0, 0))
        c += words(80, 14, 7, "Prof. Dr. Dieter Maier Winter 26-27", (0, 0, 0))   # piece by piece
        c += text(560, 16, 6, f"Info1 Kapitel 0: Organisation - {i + 1}", (0.5, 0.5, 0.5))
        add_page(pdf, c, {"Logo": lg}, fnt)
    return pdf


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # old Pillow
        return ImageFont.load_default()


def screenshot_image(seed=1) -> Image.Image:
    """Imitates a Wikipedia screenshot: a text list on the left (blue underlined links),
    two photos on the right, an orange logo at the bottom."""
    img = Image.new("RGB", (1200, 760), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f = _font(22)
    d.text((30, 20), "Die schnellsten Computer weltweit (Stand: Juni 2022):", fill=(0, 0, 0), font=f)
    for k in range(10):
        y = 60 + k * 36
        d.text((40, y), f"{k + 1}.", fill=(0, 0, 0), font=f)
        d.text((80, y), "Frontier des Oak Ridge National Laboratory", fill=(10, 60, 200), font=f)
        d.line((80, y + 26, 520, y + 26), fill=(10, 60, 200), width=1)
        d.text((540, y), f"mit {100 + 37 * k},2 PFLOPS", fill=(0, 0, 0), font=f)
    ph = Image.new("RGB", (300, 220))
    rnd = random.Random(seed)
    px = ph.load()
    for y in range(220):
        for x in range(300):
            px[x, y] = (int(120 + 100 * math.sin(x / 9 + y / 23)), int(40 + 30 * math.cos(y / 7)),
                        int(140 + 90 * math.sin((x * y) / 900)) + rnd.randint(-15, 15))
    img.paste(ph, (870, 20))
    img.paste(ph.transpose(Image.FLIP_LEFT_RIGHT), (870, 500))
    d.ellipse((330, 560, 470, 700), fill=(240, 140, 30))
    d.text((360, 610), "TOP", fill=(255, 255, 255), font=_font(30))
    d.text((480, 610), "500", fill=(40, 40, 40), font=_font(40))
    return img


def table_image() -> Image.Image:
    """Formula/table image: black text on white, small red arrows ("Regeln")."""
    img = Image.new("RGB", (900, 520), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f = _font(26)
    d.text((20, 20), "Regeln", fill=(0, 0, 0), font=f)
    rules = ["0 + 0 = 0", "0 + 1 = 1", "1 + 0 = 1", "1 + 1 = 10", "1+1 + 1 = 11"]
    for k, r in enumerate(rules):
        d.text((140, 20 + k * 40), r, fill=(0, 0, 0), font=f)
        d.text((560, 20 + k * 40), r.replace("+", "-"), fill=(0, 0, 0), font=f)
    d.text((140, 240), "Übertrag", fill=(0, 0, 0), font=f)
    d.polygon([(270, 250), (290, 235), (290, 265)], fill=(220, 30, 30))
    d.text((20, 330), "Beispiele", fill=(0, 0, 0), font=f)
    for k, r in enumerate(["  1 0 1 0", "+ 1 1 1 1", "1 1 0 0 1"]):
        d.text((300, 330 + k * 40), r, fill=(0, 0, 0), font=f)
    return img


def png_image(pdf, img: Image.Image):
    import zlib
    return pdf.make_stream(zlib.compress(img.convert("RGB").tobytes()), Type=Name.XObject,
                           Subtype=Name.Image, Width=img.width, Height=img.height,
                           ColorSpace=Name.DeviceRGB, BitsPerComponent=8, Filter=Name.FlateDecode)


def mixed_deck(n=4) -> pikepdf.Pdf:
    """Images containing text: the same screenshot on every page (pages 0,2) or a table image (1,3)
    + a separate pure photo. For the cropping and "keep images with text" tests."""
    pdf = pikepdf.new()
    fnt = font(pdf)
    shot = png_image(pdf, screenshot_image())
    table = jpeg_image(pdf, table_image())
    for i in range(n):
        xo = {"Photo": photo(pdf, 300 + i)}
        c = "q 1 1 1 rg 0 0 720 405 re f Q\n"
        c += text(30, 375, 18, f"Folie {i + 1}", (0.1, 0.3, 0.7))
        if i % 2 == 0:
            xo["Shot"] = shot
            c += "q 600 0 0 380 20 10 cm /Shot Do Q\n"
        else:
            xo["Table"] = table
            c += "q 400 0 0 231 40 100 cm /Table Do Q\n"
        c += "q 120 0 0 80 580 20 cm /Photo Do Q\n" if i % 2 else ""
        add_page(pdf, c, xo, fnt)
    return pdf


def bench_deck(pages: int) -> pikepdf.Pdf:
    src = dark_deck(12)
    out = pikepdf.new()
    for i in range(pages):
        out.pages.append(src.pages[i % 12])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=0)
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if a.pages:
        p = OUT / f"bench_{a.pages}.pdf"
        bench_deck(a.pages).save(p)
        print(p)
        return
    for name, fn in (("dark_slides.pdf", dark_deck), ("light_slides.pdf", light_deck), ("hochschule_slides.pdf", hhn_deck),
                     ("mixed_images.pdf", mixed_deck), ("beamer_slides.pdf", form_deck)):
        fn().save(OUT / name)
        print(OUT / name)


if __name__ == "__main__":
    main()
