"""Raster görsel içerik analizi: görsel yazı mı (tablo, formül, ekran görüntüsü), fotoğraf mı?

Görsel küçültülüp ~16 px'lik döşemelere bölünür. Her döşeme:
  blank  – neredeyse düz renk (açık zemin)
  text   – açık zemin üstünde koyu, keskin, az renkli izler (veya tersi)
  photo  – orta tonlar, renk, doku ya da düz renkli dolu alanlar
Sonuç:
  text:   yazı döşemelerinin dolu döşemelere oranı (0..1)
  photos: fotoğraf bölgelerinin kutuları, görselin kendi koordinatlarında (0..1, sol-üst orijin)

OCR yapılmaz; hızlı ve bağımlılıksızdır (numpy + Pillow). Sezgiseldir: emin olunmayan
durumlarda kullanıcı elle kırpar veya korur.
"""
from __future__ import annotations

import io

import numpy as np
import pikepdf
from PIL import Image

MAX_SIDE = 640
TILE = 16
TEXT_IMAGE = 0.6       # bundan yüksek metin skoru: "yazılı görsel"
MIN_PHOTO = 0.015      # görsel alanının bu oranından küçük fotoğraf parçaları yok sayılır


def load_small(pdf: pikepdf.Pdf, objgen) -> Image.Image | None:
    try:
        obj = pdf.get_object(objgen)
        if bool(obj.get("/ImageMask", False)):
            return None
        filt = obj.get("/Filter")
        if isinstance(filt, pikepdf.Name) and str(filt) == "/DCTDecode":
            im = Image.open(io.BytesIO(obj.read_raw_bytes()))
            im.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG'i doğrudan küçük çöz (çok hızlı)
        else:
            im = pikepdf.PdfImage(obj).as_pil_image()
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        if "/SMask" in obj:  # saydam alanlar beyaz kağıt gibi görünür
            try:
                a = pikepdf.PdfImage(obj.SMask).as_pil_image().convert("L").resize(im.size)
                white = Image.new("RGB", im.size, (255, 255, 255))
                im = Image.composite(im, white, a)
            except Exception:
                pass
        return im
    except Exception:
        return None


def tile_classes(im: Image.Image) -> np.ndarray:
    """0 = blank, 1 = text, 2 = photo"""
    a = np.asarray(im, dtype=np.float32) / 255.0
    h, w = a.shape[:2]
    rows, cols = max(1, h // TILE), max(1, w // TILE)
    a = a[: rows * TILE, : cols * TILE]
    g = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    sat = a.max(axis=2) - a.min(axis=2)

    def tiles(x):
        return x.reshape(rows, TILE, cols, TILE).swapaxes(1, 2).reshape(rows, cols, TILE * TILE)

    gt, st = tiles(g), tiles(sat)
    std = gt.std(axis=2)
    light = (gt > 0.78).mean(axis=2)
    dark = (gt < 0.40).mean(axis=2)
    mid = 1.0 - light - dark
    colored = (st > 0.28).mean(axis=2)

    cls = np.full((rows, cols), 2, dtype=np.uint8)
    flat = std < 0.035
    cls[flat & (colored < 0.5)] = 0                             # düz açık/gri/koyu zemin
    texty = (((light >= 0.5) | (dark >= 0.6)) & (mid <= 0.4) & (colored < 0.35)) | \
            ((light >= 0.7) & (colored < 0.2))                  # ince, keskin izler
    cls[~flat & texty] = 1
    return cls


def _components(mask: np.ndarray):
    rows, cols = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for r in range(rows):
        for c in range(cols):
            if not mask[r, c] or seen[r, c]:
                continue
            stack = [(r, c)]
            seen[r, c] = True
            r0 = r1 = r
            c0 = c1 = c
            n = 0
            while stack:
                y, x = stack.pop()
                n += 1
                r0, r1, c0, c1 = min(r0, y), max(r1, y), min(c0, x), max(c1, x)
                for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= yy < rows and 0 <= xx < cols and mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
            out.append((r0, c0, r1, c1, n))
    return out


def _dilate(m: np.ndarray) -> np.ndarray:
    o = m.copy()
    o[1:, :] |= m[:-1, :]
    o[:-1, :] |= m[1:, :]
    o[:, 1:] |= m[:, :-1]
    o[:, :-1] |= m[:, 1:]
    return o


def _merge(boxes):
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                    boxes[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    del boxes[j]
                    changed = True
                    break
            if changed:
                break
    return boxes


def analyze_image(im: Image.Image) -> dict:
    cls = tile_classes(im)
    rows, cols = cls.shape
    text_n = int((cls == 1).sum())
    photo_n = int((cls == 2).sum())
    score = text_n / max(1, text_n + photo_n)

    photo = cls == 2
    # Yazı kenarlarındaki tek tük "fotoğraf" döşemelerini ele: komşusu az olanları at.
    nb = np.zeros_like(cls, dtype=np.int32)
    p = np.pad(photo, 1)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                nb += p[1 + dy: 1 + dy + rows, 1 + dx: 1 + dx + cols]
    core = photo & (nb >= 3)
    grown = _dilate(_dilate(core)) & (photo | _dilate(core))
    boxes = []
    total = rows * cols
    for r0, c0, r1, c1, n in _components(grown):
        if n / total < MIN_PHOTO:
            continue
        boxes.append((max(0, c0 - 0.5) / cols, max(0, r0 - 0.5) / rows,
                      min(cols, c1 + 1.5) / cols, min(rows, r1 + 1.5) / rows))
    boxes = [tuple(round(v, 4) for v in b) for b in _merge(boxes)]
    return {"text": round(score, 3), "photos": boxes, "grid": [rows, cols]}


def image_features(pdf: pikepdf.Pdf, objgen) -> dict | None:
    im = load_small(pdf, objgen)
    if im is None or im.width < 24 or im.height < 24:
        return None
    return analyze_image(im)
