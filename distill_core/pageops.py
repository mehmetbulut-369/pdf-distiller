"""Page layout: delete, reorder, rotate and N-up (several pages per sheet)."""
from __future__ import annotations

import pikepdf
from pikepdf import Rectangle

from .interpreter import page_box, page_rotation
from .model import PageOp

A4 = (595.28, 841.89)
MARGIN = 24.0
GUTTER = 12.0


def apply_page_ops(pdf: pikepdf.Pdf, ops: list[PageOp]) -> pikepdf.Pdf:
    """Returns a PDF with the pages in the requested order/rotation. Returns the same object for the identity."""
    n = len(pdf.pages)
    identity = len(ops) == n and all(o.src == i and o.rotate % 360 == 0 for i, o in enumerate(ops))
    if identity:
        return pdf
    out = pikepdf.new()
    for o in ops:
        if 0 <= o.src < n:
            out.pages.append(pdf.pages[o.src])
            if o.rotate % 360:
                p = out.pages[-1]
                p.obj.Rotate = (page_rotation(p.obj) + o.rotate) % 360
    return out


def _display_size(page) -> tuple[float, float]:
    x0, y0, x1, y1 = page_box(page.obj)
    w, h = x1 - x0, y1 - y0
    return (h, w) if page_rotation(page.obj) in (90, 270) else (w, h)


def best_grid(n: int, pw: float, ph: float):
    """Pick the grid that gives the largest scale on A4 for the slide aspect ratio."""
    best = None
    for cols in range(1, n + 1):
        if n % cols:
            continue
        rows = n // cols
        for sw, sh in (A4, (A4[1], A4[0])):
            cw = (sw - 2 * MARGIN - (cols - 1) * GUTTER) / cols
            ch = (sh - 2 * MARGIN - (rows - 1) * GUTTER) / rows
            scale = min(cw / pw, ch / ph)
            if best is None or scale > best[0]:
                best = (scale, cols, rows, sw, sh, cw, ch)
    return best


def nup(pdf: pikepdf.Pdf, n: int) -> pikepdf.Pdf:
    if n <= 1 or len(pdf.pages) == 0:
        return pdf
    pw, ph = (max(v, 1.0) for v in _display_size(pdf.pages[0]))
    _, cols, rows, sw, sh, cw, ch = best_grid(n, pw, ph)
    out = pikepdf.new()
    pages = list(pdf.pages)
    for start in range(0, len(pages), n):
        sheet = out.add_blank_page(page_size=(sw, sh))
        for k, src in enumerate(pages[start:start + n]):
            r, c = divmod(k, cols)
            x0 = MARGIN + c * (cw + GUTTER)
            y1 = sh - MARGIN - r * (ch + GUTTER)
            try:
                sheet.add_overlay(src, Rectangle(x0, y1 - ch, x0 + cw, y1))
            except pikepdf.PdfError:  # undecodable content stream: pdfium shows the page blank anyway
                src.obj.Contents = pdf.make_stream(b"")
                sheet.add_overlay(src, Rectangle(x0, y1 - ch, x0 + cw, y1))
    return out
