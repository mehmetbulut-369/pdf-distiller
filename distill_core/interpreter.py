"""PDF content stream interpreter.

This module is the heart of the project. It walks a page's content stream
operator by operator, tracks the graphics state (CTM, clipping, colour) and:

  * in analysis mode: records every removable visual element (image, fill,
    stroke, shading) with page coordinates, area share, luminance and a
    repetition signature;
  * in rewrite mode: performs the same walk, removes the elements in `drops`,
    fixes text colour and optionally converts colours to gray.

Because both modes share one code path, element ids ("<page>-<seq>") are
identical in both passes. If that consistency breaks, the wrong element gets
removed; always run the tests when changing this file.

How removal works:
  * Path drawing: path construction operators are kept and the painting
    operator is replaced with `n` (end path without painting). If the same path
    is also a clip (W), the clip still applies; only the ink is gone.
  * Images and shadings: `Do` / `sh` / inline images are skipped.
  * Form XObjects: the walker descends into them; a changed form is added as a
    new copy with the changed content (identical results share one copy).
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Callable

import pikepdf
from pikepdf import ContentStreamInlineImage, Name, Operator
from pikepdf import ContentStreamInstruction as Instr

from .model import FILL, IMAGE, SHADING, STROKE, TEXT, Element

IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
MAX_DEPTH = 16
BACKDROP_MIN_AREA = 0.003  # smallest backdrop considered for the text colour decision


def mul(m, n):
    """Apply m first, then n (PDF row-vector convention: p' = p × m × n)."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


def apply(m, x, y):
    return (x * m[0] + y * m[2] + m[4], x * m[1] + y * m[3] + m[5])


def rect_bbox(m, x0, y0, x1, y1):
    pts = (apply(m, x0, y0), apply(m, x1, y0), apply(m, x0, y1), apply(m, x1, y1))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def intersect(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return (x0, y0, x0, y0)
    return (x0, y0, x1, y1)


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def nums(operands):
    out = []
    for o in operands:
        try:
            out.append(float(o))
        except (TypeError, ValueError):
            pass
    return out


# ---------------------------------------------------------------- colour helpers

def lum_of(kind: str, c: list[float]) -> float:
    try:
        if kind == "gray" and len(c) >= 1:
            return min(max(c[0], 0.0), 1.0)
        if kind == "rgb" and len(c) >= 3:
            return min(max(0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2], 0.0), 1.0)
        if kind == "cmyk" and len(c) >= 4:
            k = c[3]
            r, g, b = (1 - c[0]) * (1 - k), (1 - c[1]) * (1 - k), (1 - c[2]) * (1 - k)
            return min(max(0.299 * r + 0.587 * g + 0.114 * b, 0.0), 1.0)
    except Exception:
        pass
    return 0.5


_DEVICE = {"/DeviceGray": "gray", "/G": "gray", "/DeviceRGB": "rgb", "/RGB": "rgb",
           "/DeviceCMYK": "cmyk", "/CMYK": "cmyk", "/Pattern": "pattern"}


def cs_kind(name, resources) -> str:
    key = str(name)
    if key in _DEVICE:
        return _DEVICE[key]
    try:
        obj = resources.get("/ColorSpace", {}).get(key) if resources is not None else None
    except Exception:
        obj = None
    if obj is None:
        return "other"
    if isinstance(obj, Name):
        return _DEVICE.get(str(obj), "other")
    try:
        fam = str(obj[0])
        if fam == "/ICCBased":
            n = int(obj[1].get("/N", 0))
            return {1: "gray", 3: "rgb", 4: "cmyk"}.get(n, "other")
        if fam == "/CalRGB":
            return "rgb"
        if fam == "/CalGray":
            return "gray"
        if fam == "/Pattern":
            return "pattern"
    except Exception:
        pass
    return "other"


_NCOMP = {"gray": 1, "rgb": 3, "cmyk": 4}
_DEVICE_CS = {"gray": "/DeviceGray", "rgb": "/DeviceRGB", "cmyk": "/DeviceCMYK"}


class Color:
    """Colour state of one side (fill or stroke).

    kind:    gray | rgb | cmyk | pattern | other
    lum:     luminance of the original colour
    cs:      the `cs`/`CS` command needed to re-establish the original colour space
    restore: command list that re-establishes the original colour (as converted)
    dirty:   whether the actual colour space in the output differs from the original
             (gray conversion / forced text colour)
    """

    __slots__ = ("kind", "lum", "cs", "restore", "dirty")

    def __init__(self):
        self.kind = "gray"
        self.lum = 0.0
        self.cs = None
        self.restore = []
        self.dirty = False

    def copy(self):
        c = Color.__new__(Color)
        c.kind, c.lum, c.cs, c.restore, c.dirty = self.kind, self.lum, self.cs, self.restore, self.dirty
        return c


class GState:
    __slots__ = ("ctm", "clip", "fill", "stroke", "tr", "tl", "fs", "tc", "tw", "th", "font")

    def __init__(self, clip):
        self.ctm = IDENT
        self.clip = clip
        self.fill = Color()
        self.stroke = Color()
        self.tr = 0      # text rendering mode
        self.tl = 0.0    # leading
        self.fs = 0.0    # font size
        self.tc = 0.0    # character spacing
        self.tw = 0.0    # word spacing
        self.th = 1.0    # horizontal scaling (Tz / 100)
        self.font = None  # FontInfo

    def copy(self):
        g = GState.__new__(GState)
        g.ctm, g.clip, g.tr, g.tl, g.fs = self.ctm, self.clip, self.tr, self.tl, self.fs
        g.tc, g.tw, g.th, g.font = self.tc, self.tw, self.th, self.font
        g.fill, g.stroke = self.fill.copy(), self.stroke.copy()
        return g


# ---------------------------------------------------------------- font widths

class FontInfo:
    """Just enough font information (glyph widths) to compute text boxes."""

    __slots__ = ("name", "two_byte", "widths", "default", "scale")

    def __init__(self):
        self.name = ""
        self.two_byte = False
        self.widths: dict = {}
        self.default = 500.0
        self.scale = 0.001

    def advance(self, data: bytes, fs: float, tc: float, tw: float, th: float) -> float:
        """Advance of a string in text space (PDF 9.4.4)."""
        total = 0.0
        w, d, sc = self.widths, self.default, self.scale * fs
        if self.two_byte:
            for i in range(0, len(data) - 1, 2):
                total += w.get((data[i] << 8) | data[i + 1], d) * sc + tc
        else:
            for c in data:
                total += w.get(c, d) * sc + tc + (tw if c == 32 else 0.0)
        return total * th


def load_font(fobj) -> FontInfo:
    fi = FontInfo()
    try:
        fi.name = str(fobj.get("/BaseFont", ""))
        subtype = str(fobj.get("/Subtype", ""))
        if subtype == "/Type0":
            fi.two_byte = True  # 2-byte encodings like Identity-H (the most common in practice)
            desc = fobj.DescendantFonts[0]
            fi.default = float(desc.get("/DW", 1000))
            W = desc.get("/W")
            i = 0
            n = len(W) if W is not None else 0
            while i + 1 < n:
                c = int(W[i])
                nxt = W[i + 1]
                if isinstance(nxt, pikepdf.Array):
                    for k, v in enumerate(nxt):
                        fi.widths[c + k] = float(v)
                    i += 2
                else:
                    c2, v = int(nxt), float(W[i + 2])
                    for cc in range(c, min(c2, c + 20000) + 1):
                        fi.widths[cc] = v
                    i += 3
        else:
            ws = fobj.get("/Widths")
            fc = int(fobj.get("/FirstChar", 0))
            if ws is not None:
                for k, v in enumerate(ws):
                    fi.widths[fc + k] = float(v)
            fd = fobj.get("/FontDescriptor")
            mw = fd.get("/MissingWidth") if fd is not None else None
            # Standard 14 fonts may lack a widths table: use an average glyph width.
            fi.default = float(mw) if mw is not None else (0.0 if ws is not None else 520.0)
            if subtype == "/Type3":
                fm = nums(fobj.get("/FontMatrix", []))
                fi.scale = fm[0] if fm else 0.001
    except Exception:
        pass
    return fi


PATH_CONSTRUCT = {"m", "l", "c", "v", "y", "re", "h"}
PAINT = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}
STROKE_ONLY = {"S", "s"}
SHOW = {"Tj", "TJ", "'", '"'}
FILL_COLOR = {"g", "rg", "k", "cs", "sc", "scn"}
STROKE_COLOR = {"G", "RG", "K", "CS", "SC", "SCN"}


def _q(v: float) -> float:
    return round(float(v), 4)


class Caches:
    """Caches shared for the lifetime of one Pdf object."""

    def __init__(self):
        self.streams: dict = {}     # form objgen -> parsed commands
        self.img_hash: dict = {}    # image objgen -> content hash
        self.forms: dict = {}       # (form objgen, new content hash) -> new form object
        self.fonts: dict = {}       # font objgen -> FontInfo


class PageWalker:
    """Analyses or rewrites a single page."""

    def __init__(self, pdf: pikepdf.Pdf, page_index: int, page_obj, *, rewrite: bool,
                 drops: set | None = None, text_mode: str = "keep", grayscale: bool = False,
                 to_view: Callable | None = None, caches: Caches | None = None, clips: dict | None = None):
        self.pdf = pdf
        self.page_index = page_index
        self.page_obj = page_obj
        self.rewrite = rewrite
        self.drops = drops or set()
        self.clips = clips or {}          # image element id -> {"keep": [polygon], "erase": [polygon]} (unit square)
        self.last_id = None
        self.text_mode = text_mode
        self.grayscale = grayscale
        self.to_view = to_view or (lambda b: b)
        self.caches = caches or Caches()

        self.page_box = page_box(page_obj)
        self.page_area = max(area(self.page_box), 1.0)
        self.counter = 0
        self.elements: list[Element] = []
        self.kept_images: set = set()     # image objgens that stay visible after rewriting
        self.backdrops: list = []         # (bbox, lum) – kept elements that may sit under text
        self.override = False             # whether the text colour is currently forced
        self.changed = False
        self._active_forms: set = set()
        self.tcounter = 0                 # text box counter (separate from the graphics counter)
        self.tgroup = None                # the text box currently being extended
        self.tgroups: list = []           # text boxes found during analysis

    # ------------------------------------------------------------ main entry point
    def run(self) -> bool:
        """Walk the page. In rewrite mode, replaces the page content. Returns whether anything changed."""
        try:
            instrs = pikepdf.parse_content_stream(self.page_obj)
        except Exception:
            return False
        res = page_resources(self.page_obj)
        self.gs = GState(self.page_box)
        self.stack: list[GState] = []
        out, changed = self._walk(instrs, res, 0)
        if self.rewrite and changed:
            self.page_obj.Contents = self.pdf.make_stream(pikepdf.unparse_content_stream(out))
        if not self.rewrite:
            self._finish_text()
        self.changed = changed
        return changed

    # ------------------------------------------------------------ text boxes
    def _text_piece(self, tm, adv: float, raw: bytes) -> bool:
        """Adds a show operator (Tj/TJ/'/") to a text box.

        Consecutive pieces on the same baseline, side by side, form one box. The box id
        "<page>-t<seq>" is the same in both passes. In rewrite mode, returns True if the box is
        to be removed.
        """
        gs = self.gs
        fs = gs.fs or 1.0
        trm = mul(tm, gs.ctm)
        x0, x1 = (0.0, adv) if adv >= 0 else (adv, 0.0)
        bbox = rect_bbox(trm, x0, -0.22 * fs, x1, 0.78 * fs)
        ox, oy = apply(trm, 0.0, 0.0)
        ex, _ = apply(trm, adv, 0.0)
        size = math.hypot(trm[2], trm[3]) * fs or 1.0
        g = self.tgroup
        if (g is not None and abs(oy - g["y"]) < 0.35 * size and -0.6 * size <= ox - g["ex"] <= 1.5 * size
                and abs(size - g["size"]) < 0.3 * size):
            g["ex"] = ex
            if not self.rewrite:
                b = g["bbox"]
                g["bbox"] = (min(b[0], bbox[0]), min(b[1], bbox[1]), max(b[2], bbox[2]), max(b[3], bbox[3]))
                g["raw"].extend(raw)
        else:
            self.tcounter += 1
            g = {"id": "%d-t%d" % (self.page_index, self.tcounter), "y": oy, "ex": ex, "size": size}
            if not self.rewrite:
                font = gs.font.name if gs.font else ""
                g.update(bbox=bbox, ox=ox, oy=oy, lum=gs.fill.lum,
                         raw=bytearray(("%s|%.1f|" % (font, size)).encode() + raw))
                self.tgroups.append(g)
            self.tgroup = g
        return self.rewrite and g["id"] in self.drops

    def _finish_text(self):
        for g in self.tgroups:
            clipped = intersect(g["bbox"], self.page_box)
            a = area(clipped) / self.page_area
            if a <= 0:
                continue
            sig = "t:%s:%d,%d" % (hashlib.md5(bytes(g["raw"])).hexdigest()[:16],
                                  round(g["ox"] / 3), round(g["oy"] / 3))
            self.elements.append(Element(g["id"], self.page_index, TEXT, clipped, self.to_view(clipped),
                                         min(a, 1.0), g["lum"], sig))

    def _show_data(self, ins, op):
        """(raw bytes, advance in text space)"""
        gs = self.gs
        f = gs.font
        fs, tc, tw, th = gs.fs, gs.tc, gs.tw, gs.th
        ops = ins.operands
        if not ops:
            return b"", 0.0
        arg = ops[-1]
        raw = bytearray()
        adv = 0.0
        items = arg if op == "TJ" and isinstance(arg, pikepdf.Array) else [arg]
        for it in items:
            if isinstance(it, pikepdf.String):
                b = bytes(it)
                raw.extend(b)
                if f is not None:
                    adv += f.advance(b, fs, tc, tw, th)
                else:
                    adv += (len(b) * 0.52 * fs + len(b) * tc) * th
            else:
                try:
                    adv -= float(it) / 1000.0 * fs * th
                except (TypeError, ValueError):
                    pass
        return bytes(raw), adv

    def _font(self, name, res):
        try:
            fobj = res.get("/Font", {}).get(str(name)) if res is not None else None
        except Exception:
            fobj = None
        if fobj is None:
            return None
        key = fobj.objgen
        fi = self.caches.fonts.get(key) if key != (0, 0) else None
        if fi is None:
            fi = load_font(fobj)
            if key != (0, 0):
                self.caches.fonts[key] = fi
        return fi

    # ------------------------------------------------------------ element registry
    def _element(self, kind: str, bbox, lum: float, sig: str, m=None, obj=None) -> bool:
        """Register the element; returns True if it is to be removed. The last id is in `self.last_id`."""
        self.counter += 1
        eid = f"{self.page_index}-{self.counter}"
        self.last_id = eid
        if kind == STROKE:  # strokes can have zero area; give them a thin margin
            bbox = (bbox[0] - 0.5, bbox[1] - 0.5, bbox[2] + 0.5, bbox[3] + 0.5)
        clipped = intersect(intersect(bbox, self.gs.clip), self.page_box)
        a = area(clipped) / self.page_area
        if not self.rewrite:
            self.elements.append(Element(eid, self.page_index, kind, clipped, self.to_view(clipped),
                                         min(a, 1.0), lum, sig, m, obj))
            return False
        drop = eid in self.drops
        if not drop and kind != STROKE and a >= BACKDROP_MIN_AREA:
            self.backdrops.append((clipped, 0.35 if kind == IMAGE else lum))
        return drop

    # ------------------------------------------------------------ walk
    def _walk(self, instrs, res, depth):
        rewrite = self.rewrite
        out = [] if rewrite else None
        emit = out.append if rewrite else (lambda _i: None)
        changed = False
        gs = self.gs

        px0 = py0 = float("inf")
        px1 = py1 = float("-inf")
        has_path = False
        pending_clip = False
        tm = tlm = IDENT

        for ins in instrs:
            if isinstance(ins, ContentStreamInlineImage):
                bbox = rect_bbox(gs.ctm, 0, 0, 1, 1)
                try:
                    h = hashlib.md5(bytes(ins.iimage.unparse())).hexdigest()[:16]
                except Exception:
                    h = "x"
                if self._element(IMAGE, bbox, 0.5, "ii:" + h, gs.ctm):
                    changed = True
                    continue
                if self._clipped_emit(ins, emit):
                    changed = True
                continue

            op = str(ins.operator)

            # --- path construction
            if op in PATH_CONSTRUCT:
                if op != "h":
                    v = nums(ins.operands)
                    m = gs.ctm
                    if op == "re" and len(v) == 4:
                        x, y, w, hh = v
                        b = rect_bbox(m, x, y, x + w, y + hh)
                        px0, py0 = min(px0, b[0]), min(py0, b[1])
                        px1, py1 = max(px1, b[2]), max(py1, b[3])
                    else:
                        for i in range(0, len(v) - 1, 2):
                            x, y = apply(m, v[i], v[i + 1])
                            if x < px0: px0 = x
                            if x > px1: px1 = x
                            if y < py0: py0 = y
                            if y > py1: py1 = y
                    has_path = True
                emit(ins)
                continue

            if op == "W" or op == "W*":
                pending_clip = True
                emit(ins)
                continue

            if op in PAINT:
                bbox = (px0, py0, px1, py1) if has_path else None
                if op != "n" and bbox is not None:
                    kind = STROKE if op in STROKE_ONLY else FILL
                    col = gs.stroke if kind == STROKE else gs.fill
                    lum = col.lum if col.kind not in ("pattern", "other") else 0.5
                    sig = "%s:%d,%d,%d,%d:%s:%.2f" % (kind[0], round(bbox[0] / 4), round(bbox[1] / 4),
                                                       round(bbox[2] / 4), round(bbox[3] / 4), col.kind, lum)
                    if self._element(kind, bbox, lum, sig):
                        emit(Instr([], Operator("n")))
                        changed = True
                    else:
                        emit(ins)
                else:
                    emit(ins)
                if pending_clip and bbox is not None:
                    gs.clip = intersect(gs.clip, bbox)
                pending_clip = False
                has_path = False
                px0 = py0 = float("inf")
                px1 = py1 = float("-inf")
                continue

            # --- graphics state
            if op == "q":
                self.stack.append(gs.copy())
                emit(ins)
                continue
            if op == "Q":
                if self.stack:
                    self.gs = gs = self.stack.pop()
                emit(ins)
                continue
            if op == "cm":
                v = nums(ins.operands)
                if len(v) == 6:
                    gs.ctm = mul(tuple(v), gs.ctm)
                emit(ins)
                continue

            # --- colour
            if op in FILL_COLOR or op in STROKE_COLOR:
                if self._color(ins, op, res, emit):
                    changed = True
                continue

            # --- text
            if op == "BT":
                tm = tlm = IDENT
                emit(ins)
                continue
            if op == "ET":
                emit(ins)
                if self.override:
                    for r in gs.fill.restore:
                        emit(r)
                    gs.fill.dirty = False
                    self.override = False
                continue
            if op in SHOW:
                if op == "'" or op == '"':
                    if op == '"':
                        v = nums(ins.operands[:2])
                        if len(v) == 2:
                            gs.tw, gs.tc = v
                    tlm = mul((1, 0, 0, 1, 0, -gs.tl), tlm)
                    tm = tlm
                raw, adv = self._show_data(ins, op)
                if gs.tr == 3:  # invisible text (e.g. an OCR layer): not an element
                    emit(ins)
                elif self._text_piece(tm, adv, raw):
                    # Removed text is made invisible: the advance is kept, so the rest of the line does not shift.
                    emit(Instr([7 if gs.tr >= 4 else 3], Operator("Tr")))
                    emit(ins)
                    emit(Instr([gs.tr], Operator("Tr")))
                    changed = True
                else:
                    if rewrite and self.text_mode != "keep" and gs.tr != 7:
                        if self._text_color(tm, emit):
                            changed = True
                    emit(ins)
                tm = mul((1, 0, 0, 1, adv, 0), tm)
                continue
            if op == "Tf":
                v = nums(ins.operands)
                if v:
                    gs.fs = v[-1]
                if ins.operands:
                    gs.font = self._font(ins.operands[0], res)
                emit(ins)
                continue
            if op == "Tc" or op == "Tw" or op == "Tz":
                v = nums(ins.operands)
                if v:
                    if op == "Tc":
                        gs.tc = v[0]
                    elif op == "Tw":
                        gs.tw = v[0]
                    else:
                        gs.th = v[0] / 100.0
                emit(ins)
                continue
            if op == "Tm":
                v = nums(ins.operands)
                if len(v) == 6:
                    tm = tlm = tuple(v)
                emit(ins)
                continue
            if op == "Td" or op == "TD":
                v = nums(ins.operands)
                if len(v) == 2:
                    tlm = mul((1, 0, 0, 1, v[0], v[1]), tlm)
                    tm = tlm
                    if op == "TD":
                        gs.tl = -v[1]
                emit(ins)
                continue
            if op == "T*":
                tlm = mul((1, 0, 0, 1, 0, -gs.tl), tlm)
                tm = tlm
                emit(ins)
                continue
            if op == "TL":
                v = nums(ins.operands)
                if v:
                    gs.tl = v[0]
                emit(ins)
                continue
            if op == "Tr":
                v = nums(ins.operands)
                if v:
                    gs.tr = int(v[0])
                emit(ins)
                continue

            # --- XObject
            if op == "Do":
                r = self._do(ins, res, depth, emit)
                if r:
                    changed = True
                continue

            # --- shading
            if op == "sh":
                name = str(ins.operands[0]) if ins.operands else ""
                sig = "sh:%s:%d,%d,%d,%d" % ((name,) + tuple(round(c / 4) for c in gs.clip))
                if self._element(SHADING, gs.clip, 0.5, sig):
                    changed = True
                    continue
                emit(ins)
                continue

            emit(ins)

        return out, changed

    # ------------------------------------------------------------ colour operators
    def _color(self, ins, op, res, emit) -> bool:
        """Track a colour operator; convert it in gray mode. True if the output changed."""
        stroke = op in STROKE_COLOR
        gs = self.gs
        col = gs.stroke if stroke else gs.fill
        lo = op.lower()
        gray_op = "G" if stroke else "g"
        cs_op = "CS" if stroke else "cs"
        if not stroke:
            self.override = False  # a new original fill colour cancels the forced colour

        if lo in ("g", "rg", "k"):
            kind = {"g": "gray", "rg": "rgb", "k": "cmyk"}[lo]
            v = nums(ins.operands)
            col.kind, col.lum = kind, lum_of(kind, v)
            col.cs = Instr([Name(_DEVICE_CS[kind])], Operator(cs_op))
            col.dirty = False
            if self.grayscale and kind != "gray":
                new = Instr([_q(col.lum)], Operator(gray_op))
                emit(new)
                col.restore = [new]
                return True
            emit(ins)
            col.restore = [ins]
            return False

        if lo == "cs":
            kind = cs_kind(ins.operands[0], res) if ins.operands else "other"
            col.kind = kind
            col.lum = 0.0 if kind in ("gray", "rgb", "cmyk") else 0.5
            col.cs = ins
            col.dirty = False
            emit(ins)
            col.restore = [ins]
            return False

        # sc / scn
        v = nums(ins.operands)
        has_name = bool(ins.operands) and isinstance(ins.operands[-1], Name)
        kind = col.kind
        col.lum = lum_of(kind, v) if kind in _NCOMP else 0.5
        if (self.grayscale and kind in _NCOMP and kind != "gray" and not has_name
                and len(v) == _NCOMP[kind]):
            new = Instr([_q(col.lum)], Operator(gray_op))
            emit(new)
            col.restore = [new]
            col.dirty = True
            return True
        prefix = []
        if col.dirty and col.cs is not None:
            prefix = [col.cs]
            emit(col.cs)
        emit(ins)
        col.restore = ([col.cs] if col.cs is not None else []) + [ins]
        col.dirty = False
        return bool(prefix)

    # ------------------------------------------------------------ text colour
    def _text_color(self, tm, emit) -> bool:
        gs = self.gs
        fill = gs.fill
        trm = mul(tm, gs.ctm)
        x, y = apply(trm, 0, (gs.fs or 10) * 0.3)
        on_dark = False
        for b, lum in reversed(self.backdrops):
            if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                on_dark = lum < 0.5
                break
        if self.text_mode == "black":
            want = not on_dark and fill.lum > 0.02
        else:  # auto
            want = not on_dark and fill.lum > 0.6 and fill.kind in _NCOMP
        if want and not self.override:
            emit(Instr([0], Operator("g")))
            self.override = True
            fill.dirty = True
            return True
        if not want and self.override:
            for r in fill.restore:
                emit(r)
            self.override = False
            fill.dirty = False
            return True
        return False

    # ------------------------------------------------------------ cropping
    def _clipped_emit(self, ins, emit) -> bool:
        """If a crop is defined for the last image element, writes it as `q <clip path> Do Q`."""
        spec = self.clips.get(self.last_id) if self.rewrite else None
        if not spec:
            emit(ins)
            return False
        emit(Instr([], Operator("q")))
        for instr in clip_instructions(spec):
            emit(instr)
        emit(ins)
        emit(Instr([], Operator("Q")))
        return True

    # ------------------------------------------------------------ XObject
    def _do(self, ins, res, depth, emit) -> bool:
        gs = self.gs
        name = str(ins.operands[0]) if ins.operands else ""
        try:
            xo = res.get("/XObject", {}).get(name) if res is not None else None
        except Exception:
            xo = None
        if xo is None:
            emit(ins)
            return False
        subtype = str(xo.get("/Subtype", ""))

        if subtype == "/Image":
            bbox = rect_bbox(gs.ctm, 0, 0, 1, 1)
            is_mask = bool(xo.get("/ImageMask", False))
            lum = gs.fill.lum if is_mask else 0.5
            if self._element(IMAGE, bbox, lum, "img:" + self._img_hash(xo), gs.ctm, xo.objgen):
                return True
            if self.rewrite and not is_mask:
                self.kept_images.add(xo.objgen)
            return self._clipped_emit(ins, emit)

        if subtype == "/Form" and depth < MAX_DEPTH and xo.objgen not in self._active_forms:
            saved = gs
            stack_len = len(self.stack)
            self.gs = gs = saved.copy()
            m = nums(xo.get("/Matrix", [])) if "/Matrix" in xo else []
            if len(m) == 6:
                gs.ctm = mul(tuple(m), gs.ctm)
            fb = nums(xo.get("/BBox", [])) if "/BBox" in xo else []
            if len(fb) == 4:
                gs.clip = intersect(gs.clip, rect_bbox(gs.ctm, *fb))
            fres = xo.get("/Resources") if "/Resources" in xo else res
            self._active_forms.add(xo.objgen)
            try:
                sub = self._parse_form(xo)
                sub_out, sub_changed = self._walk(sub, fres, depth + 1)
            finally:
                self._active_forms.discard(xo.objgen)
            # the form's leftover state does not leak out (Do implies q/Q)
            del self.stack[stack_len:]
            self.gs = saved
            self.override = False
            if self.rewrite and sub_changed:
                emit(Instr([self._form_copy(xo, sub_out, res)], Operator("Do")))
                return True
            emit(ins)
            return False

        emit(ins)
        return False

    def _parse_form(self, xo):
        key = xo.objgen
        cached = self.caches.streams.get(key) if key != (0, 0) else None
        if cached is None:
            try:
                cached = pikepdf.parse_content_stream(xo)
            except Exception:
                cached = []
            if key != (0, 0):
                self.caches.streams[key] = cached
        return cached

    def _img_hash(self, xo) -> str:
        key = xo.objgen
        h = self.caches.img_hash.get(key)
        if h is None:
            try:
                h = hashlib.md5(xo.read_raw_bytes()).hexdigest()[:16]
            except Exception:
                h = "%d_%d" % key
            self.caches.img_hash[key] = h
        return h

    def _form_copy(self, xo, new_instrs, parent_res) -> Name:
        data = pikepdf.unparse_content_stream(new_instrs)
        digest = hashlib.md5(data).hexdigest()[:12]
        key = (xo.objgen, digest)
        new = self.caches.forms.get(key)
        if new is None:
            new = pikepdf.Stream(self.pdf, data)
            for k, v in xo.items():
                if k not in ("/Length", "/Filter", "/DecodeParms"):
                    new[k] = v
            new = self.pdf.make_indirect(new)
            self.caches.forms[key] = new
        name = Name("/DZ%d" % new.objgen[0])
        if "/XObject" not in parent_res:
            parent_res.XObject = pikepdf.Dictionary()
        xd = parent_res.XObject
        if name not in xd:
            xd[name] = new
        return name


# ---------------------------------------------------------------- clip paths

def _poly_area(p):
    return sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p))) / 2


def _path(poly):
    out = [Instr([_q(poly[0][0]), _q(poly[0][1])], Operator("m"))]
    out += [Instr([_q(x), _q(y)], Operator("l")) for x, y in poly[1:]]
    out.append(Instr([], Operator("h")))
    return out


def clip_instructions(spec) -> list:
    """Clip operators from polygons in the image's unit square.

    keep:  union of all polygons (same winding, nonzero rule) -> only the inside is printed
    erase: one clip per polygon (unit square + polygon, even-odd) -> their intersection is the
           complement of the union, so overlapping erase areas also work correctly.
    """
    out = []
    keep = [p for p in spec.get("keep", []) if len(p) >= 3]
    if keep:
        for p in keep:
            out += _path(p if _poly_area(p) >= 0 else p[::-1])
        out += [Instr([], Operator("W")), Instr([], Operator("n"))]
    for p in spec.get("erase", []):
        if len(p) < 3:
            continue
        out.append(Instr([-1, -1, 3, 3], Operator("re")))
        out += _path(p)
        out += [Instr([], Operator("W*")), Instr([], Operator("n"))]
    return out


def invert(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    return (d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det)


# ---------------------------------------------------------------- page helpers

def _inherited(page_obj, key):
    node = page_obj
    for _ in range(64):
        if node is None:
            return None
        if key in node:
            return node[key]
        node = node.get("/Parent")
    return None


def page_resources(page_obj):
    res = _inherited(page_obj, "/Resources")
    if res is None:
        res = pikepdf.Dictionary()
        page_obj.Resources = res
    return res


def page_box(page_obj):
    mb = nums(_inherited(page_obj, "/MediaBox") or [0, 0, 612, 792])
    if len(mb) != 4:
        mb = [0, 0, 612, 792]
    mb = (min(mb[0], mb[2]), min(mb[1], mb[3]), max(mb[0], mb[2]), max(mb[1], mb[3]))
    cb = _inherited(page_obj, "/CropBox")
    if cb is not None:
        c = nums(cb)
        if len(c) == 4:
            c = (min(c[0], c[2]), min(c[1], c[3]), max(c[0], c[2]), max(c[1], c[3]))
            inter = intersect(mb, c)
            if area(inter) > 0:
                return inter
    return mb


def page_rotation(page_obj) -> int:
    try:
        return int(_inherited(page_obj, "/Rotate") or 0) % 360
    except Exception:
        return 0


def view_to_user(box, rotate):
    """Inverse of view_mapper: converts a (0..1) view point to PDF user space."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0

    def f(vx, vy):
        if rotate == 90:
            nx, ny = vy, 1 - vx
        elif rotate == 180:
            nx, ny = 1 - vx, 1 - vy
        elif rotate == 270:
            nx, ny = 1 - vy, vx
        else:
            nx, ny = vx, vy
        return x0 + nx * w, y1 - ny * h

    return f


def user_to_view(box, rotate):
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)

    def f(x, y):
        nx, ny = (x - x0) / w, (y1 - y) / h
        if rotate == 90:
            return 1 - ny, nx
        if rotate == 180:
            return 1 - nx, 1 - ny
        if rotate == 270:
            return ny, 1 - nx
        return nx, ny

    return f


def view_mapper(box, rotate):
    """Converts a PDF user-space box to a normalised (0..1, top-left) view box."""
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)

    def pt(x, y):
        nx, ny = (x - x0) / w, (y1 - y) / h
        if rotate == 90:
            return 1 - ny, nx
        if rotate == 180:
            return 1 - nx, 1 - ny
        if rotate == 270:
            return ny, 1 - nx
        return nx, ny

    def to_view(b):
        a = pt(b[0], b[1])
        c = pt(b[2], b[3])
        return (max(0.0, min(a[0], c[0])), max(0.0, min(a[1], c[1])),
                min(1.0, max(a[0], c[0])), min(1.0, max(a[1], c[1])))

    return to_view
