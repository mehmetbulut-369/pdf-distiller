"""Kalan raster görselleri griye çevirme ve soldurma (mürekkep tasarrufu)."""
from __future__ import annotations

import io

import numpy as np
import pikepdf
from PIL import Image
from pikepdf import Name


def process_images(pdf: pikepdf.Pdf, objgens, grayscale: bool, fade: float) -> int:
    """Verilen görsel nesnelerini yerinde dönüştürür. Dönüştürülen görsel sayısını döner."""
    if not grayscale and fade <= 0:
        return 0
    done = 0
    for og in objgens:
        try:
            obj = pdf.get_object(og)
            if bool(obj.get("/ImageMask", False)):
                continue
            pim = pikepdf.PdfImage(obj)
            img = pim.as_pil_image()
        except Exception:
            continue
        if img.mode == "1":
            continue
        was_jpeg = "/DCTDecode" in str(obj.get("/Filter", ""))
        try:
            if grayscale:
                img = img.convert("L")
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            if fade > 0:
                arr = np.asarray(img, dtype=np.float32)
                arr = 255.0 - (255.0 - arr) * (1.0 - fade)
                img = Image.fromarray(arr.clip(0, 255).astype(np.uint8), img.mode)
        except Exception:
            continue

        big = img.width * img.height > 40_000
        if was_jpeg or big:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            obj.write(buf.getvalue(), filter=Name.DCTDecode)
        else:
            import zlib
            obj.write(zlib.compress(img.tobytes()), filter=Name.FlateDecode)
        obj.ColorSpace = Name.DeviceGray if img.mode == "L" else Name.DeviceRGB
        obj.BitsPerComponent = 8
        for k in ("/Decode", "/DecodeParms"):
            if k in obj:
                del obj[k]
        # Renk anahtarı maskesi eski renk uzayına göre tanımlıdır; geçersiz olur.
        if "/Mask" in obj and isinstance(obj.Mask, pikepdf.Array):
            del obj["/Mask"]
        done += 1
    return done
