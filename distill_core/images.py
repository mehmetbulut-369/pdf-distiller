"""Converting remaining raster images to gray and fading them (ink saving)."""
from __future__ import annotations

import io

import numpy as np
import pikepdf
from pikepdf import Name
from PIL import Image

from .imgfeat import too_big_to_decode


def process_images(pdf: pikepdf.Pdf, objgens, grayscale: bool, fade: float) -> int:
    """Converts the given image objects in place. Returns the number of converted images."""
    if not grayscale and fade <= 0:
        return 0
    done = 0
    for og in objgens:
        try:
            obj = pdf.get_object(og)
            if bool(obj.get("/ImageMask", False)) or too_big_to_decode(obj):  # oversized: left as it is
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

        # A JPEG stays a JPEG. Anything else stays lossless: re-encoding a screenshot of a table or formula as
        # JPEG blurs its letters, and text that stays sharp is the point of this tool.
        if was_jpeg:
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
        # A colour-key mask is defined in the old colour space; it becomes invalid.
        if "/Mask" in obj and isinstance(obj.Mask, pikepdf.Array):
            del obj["/Mask"]
        done += 1
    return done
