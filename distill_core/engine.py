"""High-level API. Front ends (web, desktop, batch) only use this class.

    doc = DistillDocument(pdf_bytes)
    doc.analyze()
    png = doc.render_processed(0, settings, overrides)
    out_bytes = doc.export(settings, overrides, page_ops)
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pikepdf
import pypdfium2 as pdfium

from . import render
from .classify import classify, signature_pages
from .images import process_images
from .imgfeat import image_features
from .interpreter import Caches, PageWalker, apply, invert, page_box, page_rotation, user_to_view, view_mapper, view_to_user
from .model import FILL, IMAGE, SHADING, TEXT, Overrides, PageInfo, PageOp, Settings
from .pageops import apply_page_ops, nup
from .render import MAX_RENDER_SIDE, PDFIUM_LOCK, ink_coverage, to_png  # noqa: F401  (public helpers)

log = logging.getLogger("distill")


FEATURE_MIN_AREA = 0.02  # content analysis only for images larger than this (logos/icons are skipped)
INK_HEAVY_PAGE = 0.15    # a printed page above this ink coverage gets a warning (a text page is ~3-6 %)
INK_MAX_PAGES = 400      # pages the ink gauge renders at most (evenly spread beyond that)
INK_HOTSPOT = 0.04       # a kept element costing at least this share of its page in ink is a hotspot


def _analyze_range(data: bytes, start: int, stop: int):
    pdf = pikepdf.open(io.BytesIO(data))
    caches = Caches()
    pages = [_analyze_page(pdf, i, caches) for i in range(start, stop)]
    return pages, _features_for(pdf, pages)


def _features_for(pdf, pages, known=None) -> dict:
    """Content features of large images, keyed by signature (each image is analysed once)."""
    feats = {}
    known = known or {}
    for p in pages:
        for e in p.elements:
            if (e.kind == IMAGE and e.obj is not None and e.area >= FEATURE_MIN_AREA
                    and e.sig not in feats and e.sig not in known):
                feats[e.sig] = image_features(pdf, e.obj)
    return feats


def _analyze_page(pdf, i, caches) -> PageInfo:
    page = pdf.pages[i]
    box = page_box(page.obj)
    rot = page_rotation(page.obj)
    w, h = box[2] - box[0], box[3] - box[1]
    if rot in (90, 270):
        w, h = h, w
    walker = PageWalker(pdf, i, page.obj, rewrite=False, to_view=view_mapper(box, rot), caches=caches)
    try:
        walker.run()
    except Exception as e:  # one broken page must not take the document down; it is exported unchanged
        log.warning("page %d could not be analysed: %s", i + 1, e)
        return PageInfo(i, w, h, rot, [], box, failed=True)
    return PageInfo(i, w, h, rot, walker.elements, box)


def settings_key(s: Settings, ov: Overrides) -> str:
    """One short id per (settings, overrides) pair: the key of every cache that depends on them."""
    return hashlib.md5(json.dumps([s.to_dict(), ov.to_dict()], sort_keys=True).encode()).hexdigest()


def _needs_rewrite(drops, s: Settings) -> bool:
    return bool(drops) or s.text_mode != "keep" or s.grayscale


def distill_pages(pdf: pikepdf.Pdf, items, drops: dict, s: Settings, clips: dict | None = None) -> set:
    """items: [(page_object, source_index)] – rewrites the pages in place.
    Returns the set of image objgens that remain visible."""
    caches = Caches()
    kept = set()
    for page_obj, idx in items:
        d = drops.get(idx, set())
        c = (clips or {}).get(idx)
        if not _needs_rewrite(d, s) and not c:
            if s.image_fade > 0:
                w = PageWalker(pdf, idx, page_obj, rewrite=True, drops=set(), caches=caches)
                try:
                    w.run()
                except Exception as e:  # e.g. PageTooComplex: the page's images just aren't faded
                    log.warning("page %d could not be walked: %s", idx + 1, e)
                    continue
                kept |= w.kept_images
            continue
        w = PageWalker(pdf, idx, page_obj, rewrite=True, drops=d, text_mode=s.text_mode,
                       grayscale=s.grayscale, caches=caches, clips=c, image_fade=s.image_fade)
        try:
            w.run()
        except Exception as e:  # page keeps its original content (Contents is only replaced at the end of run)
            log.warning("page %d could not be rewritten: %s", idx + 1, e)
            continue
        kept |= w.kept_images
    return kept


def _pdfium_rebuild(data: bytes) -> bytes | None:
    try:
        src = pdfium.PdfDocument(data)
    except pdfium.PdfiumError:
        return None  # unreadable, or needs a password: then it really is locked
    if len(src) == 0:
        return None
    new = pdfium.PdfDocument.new()
    for i in range(len(src)):  # fresh page tree / xref; page by page so one bad page doesn't sink the rest
        try:
            new.import_pages(src, [i])
        except pdfium.PdfiumError:
            continue
    if len(new) == 0:
        return None
    buf = io.BytesIO()
    new.save(buf)
    return buf.getvalue()


def _pdfium_rewrite(data: bytes, timeout: float = 60) -> bytes | None:
    """Second-chance repair for files qpdf can't open. Runs in a child process: this path only sees
    badly damaged files, and a native crash there must not take the app down."""
    try:
        with ProcessPoolExecutor(max_workers=1) as ex:
            return ex.submit(_pdfium_rebuild, data).result(timeout=timeout)
    except Exception as e:  # BrokenProcessPool (native crash), timeout, ...
        log.warning("pdfium repair failed: %s", e)
        return None


class EmptyPdf(ValueError):
    """The PDF has no pages."""


class DistillDocument:
    def __init__(self, data: bytes, name: str = "document.pdf"):
        self.data = data
        self.name = name
        self.lock = threading.RLock()
        self.uid = uuid.uuid4().hex  # this document's name in the render process
        try:
            self.pdf = pikepdf.open(io.BytesIO(data))
        except pikepdf.PdfError as e:  # PasswordError included
            # second chance: pdfium is more lenient than qpdf; let it rewrite a clean copy
            fixed = _pdfium_rewrite(data)
            if fixed is None:
                raise e from None
            self.data = data = fixed
            self.pdf = pikepdf.open(io.BytesIO(data))
        self.n_pages = len(self.pdf.pages)
        svc = render.service()  # pdfium only ever runs in the render process (render.py)
        if svc.pages(data, keep=self.uid) is None:
            if self.n_pages == 0:
                raise EmptyPdf("no pages")
            # qpdf repaired what pdfium can't read (truncated file, broken xref): render from qpdf's copy
            buf = io.BytesIO()
            self.pdf.save(buf)
            self.data = data = buf.getvalue()
            if svc.pages(data, keep=self.uid) is None:
                raise RuntimeError("pdfium cannot read the file, not even after repair")
        self.pages: list[PageInfo] = []
        self.sig_pages: dict = {}
        self._decisions: dict = {}
        self._region_n: dict = {}               # region box -> pages with text in it
        self._text_boxes = None                  # [page, x0, y0, x1, y1] of every text box (region_pages)
        self._ink_orig: dict = {}               # (page, width) -> ink coverage of the untouched page
        self.analysis_seconds = 0.0
        self.failed_pages: list[int] = []        # pages whose content could not be analysed (kept unchanged)
        self._page_text: dict[int, str] = {}     # page text extracted with pdfium
        self._el_text: dict[str, str] = {}       # text box id -> readable text
        self.img_feats: dict = {}                # image signature -> content features (imgfeat)
        self._by_id: dict = {}
        self._by_sig: dict = {}

    # -------------------------------------------------------------- analysis
    def analyze(self, workers: int | None = None) -> list[PageInfo]:
        t = time.perf_counter()
        n = self.n_pages
        workers = workers if workers is not None else (min(os.cpu_count() or 1, 8) if n >= 120 else 1)
        if workers > 1:
            chunk = (n + workers - 1) // workers
            ranges = [(a, min(a + chunk, n)) for a in range(0, n, chunk)]
            try:
                with ProcessPoolExecutor(max_workers=len(ranges)) as ex:
                    parts = list(ex.map(_analyze_range, [self.data] * len(ranges),
                                        [r[0] for r in ranges], [r[1] for r in ranges]))
                self.pages = [p for part in parts for p in part[0]]
                self.img_feats = {k: v for part in parts for k, v in part[1].items()}
            except Exception:
                self.pages, self.img_feats = _analyze_range(self.data, 0, n)
        else:
            caches = Caches()
            self.pages = [_analyze_page(self.pdf, i, caches) for i in range(n)]
            self.img_feats = _features_for(self.pdf, self.pages)
        self.failed_pages = [p.index for p in self.pages if p.failed]
        self.sig_pages = signature_pages(self.pages)
        self._by_id = {e.id: e for p in self.pages for e in p.elements}
        self._by_sig: dict = defaultdict(list)
        for p in self.pages:
            for e in p.elements:
                if e.kind == IMAGE:
                    self._by_sig[e.sig].append(e)
        self._decisions.clear()
        self._region_n.clear()
        self._text_boxes = None
        self.analysis_seconds = time.perf_counter() - t
        return self.pages

    # -------------------------------------------------------------- decisions
    def decide(self, s: Settings, ov: Overrides):
        """(drops, labels) – see classify."""
        return self.decide_full(s, ov)[:2]

    def decide_full(self, s: Settings, ov: Overrides):
        """(drops, labels, clips). clips: {page: {image_id: {"keep": [polygon], "erase": [polygon]}}}
        Polygons are in the image's unit square (PDF image space, bottom-left origin)."""
        key = settings_key(s, ov)
        r = self._decisions.get(key)
        if r is None:
            clips, forced = self._manual_clips(ov)
            drops, labels = classify(self.pages, s, ov, self.sig_pages, self.img_feats, forced)
            if s.auto_crop_photos:
                self._auto_clips(clips, drops)
            r = (drops, labels, clips)
            if len(self._decisions) > 32:
                self._decisions.clear()
            self._decisions[key] = r
        return r

    # -------------------------------------------------------------- cropping
    def features(self, e) -> dict | None:
        """Content features of an image (cached; computed on demand for small images)."""
        if e.sig not in self.img_feats:
            with self.lock:
                self.img_feats[e.sig] = image_features(self.pdf, e.obj) if e.obj else None
        return self.img_feats.get(e.sig)

    @staticmethod
    def _photo_polys(f) -> list:
        # analysis boxes have a top-left origin; the PDF image unit square has a bottom-left origin
        return [[(u0, 1 - v1), (u1, 1 - v1), (u1, 1 - v0), (u0, 1 - v0)] for u0, v0, u1, v1 in f["photos"]]

    def _manual_clips(self, ov: Overrides):
        clips: dict = defaultdict(dict)
        forced: set = set()
        for c in ov.crops:
            ref = self._by_id.get(c["id"])
            if ref is None or ref.kind != IMAGE or ref.m is None:
                continue
            if c["mode"] == "auto":
                f = self.features(ref)
                polys, kind = (self._photo_polys(f) if f else []), "erase"
            else:
                inv = invert(ref.m)
                if inv is None:
                    continue
                page = self.pages[ref.page]
                v2u = view_to_user(page.box, page.rotate)
                polys = [[apply(inv, *v2u(x, y)) for x, y in c["points"]]]
                kind = c["mode"]
            targets = self._by_sig.get(ref.sig, [ref]) if c["all"] else [ref]
            for t in targets:
                spec = clips[t.page].setdefault(t.id, {"keep": [], "erase": []})
                spec[kind].extend(polys)
                forced.add(t.id)
        return clips, forced

    def _auto_clips(self, clips, drops):
        for p in self.pages:
            d = drops.get(p.index, ())
            for e in p.elements:
                if e.kind != IMAGE or e.id in d or e.area < FEATURE_MIN_AREA or e.id in clips.get(p.index, {}):
                    continue
                f = self.img_feats.get(e.sig)
                # mixed images only: ones that also contain text (removing a pure photo entirely is not a crop)
                if f and f["photos"] and f["text"] >= 0.35:
                    clips[p.index][e.id] = {"keep": [], "erase": self._photo_polys(f)}

    def clip_view(self, e, spec) -> dict:
        page = self.pages[e.page]
        u2v = user_to_view(page.box, page.rotate)
        conv = lambda poly: [[round(v, 4) for v in u2v(*apply(e.m, x, y))] for x, y in poly]  # noqa: E731
        return {"keep": [conv(p) for p in spec.get("keep", [])], "erase": [conv(p) for p in spec.get("erase", [])]}

    def page_elements(self, i: int, s: Settings, ov: Overrides, min_area: float = 0.0008):
        """For the UI: a page's clickable elements with class and removal state.
        Text boxes also carry their readable text ("text") and the number of pages with text at the
        same position. "z" is the drawing order (higher = painted later, i.e. on top) for the layer list."""
        drops, labels, clips = self.decide_full(s, ov)
        d = drops.get(i, set())
        pclips = clips.get(i, {})
        out = []
        for z, e in enumerate(self.pages[i].elements):
            is_text = e.kind == TEXT
            if e.area < min_area and not is_text:
                continue
            item = e.to_dict()
            item["z"] = z
            item["cls"] = labels.get(e.id, "other")
            item["drop"] = e.id in d
            item["pages_with_sig"] = len(self.sig_pages.get(e.sig, ()))
            if e.kind == IMAGE:
                f = self.img_feats.get(e.sig)
                item["ti"] = f["text"] if f else None
                item["has_photos"] = bool(f and f["photos"])
                item["pages_with_sig"] = len(self._by_sig.get(e.sig, ()))
                if e.id in pclips:
                    item["clips"] = self.clip_view(e, pclips[e.id])
            if is_text:
                item["text"] = self.element_text(e)
                item["region"] = [round(v, 4) for v in region_for(e.view)]
                item["pages_with_region"] = self.region_pages(item["region"])
            out.append(item)
        return out

    def element_text(self, e) -> str:
        t = self._el_text.get(e.id)
        if t is None:
            x0, y0, x1, y1 = e.bbox
            h = y1 - y0  # query slightly inside the edges so letters from neighbouring lines don't leak in
            t = render.service().text(self.uid, self.data, e.page, (x0, y0 + h * 0.2, x1, y1 - h * 0.2)) or ""
            t = " ".join(t.split())
            self._el_text[e.id] = t
        return t

    def region_pages(self, box) -> int:
        """Pages with a text box inside `box` (the rule of classify.in_region). Every text box of the page in
        view asks this, so it runs on arrays of all text boxes at once: a 1000-page text document has 120 000.
        Cached per box."""
        key = tuple(box)
        n = self._region_n.get(key)
        if n is None:
            if self._text_boxes is None:
                rows = [(p.index, *e.view) for p in self.pages for e in p.elements if e.kind == TEXT]
                self._text_boxes = np.array(rows, dtype=np.float64).reshape(-1, 5)
            t = self._text_boxes
            cy = (t[:, 2] + t[:, 4]) / 2
            hit = (box[1] <= cy) & (cy <= box[3]) & (t[:, 1] < box[2]) & (t[:, 3] > box[0])
            n = int(np.unique(t[hit, 0]).size)
            self._region_n[key] = n
        return n

    # -------------------------------------------------------------- word counter
    def page_text(self, i: int) -> str:
        t = self._page_text.get(i)
        if t is None:
            t = render.service().text(self.uid, self.data, i) or ""
            self._page_text[i] = t
        return t

    def word_counts(self, s: Settings, ov: Overrides, pages: list[int] | None = None,
                    exclude_removed: bool = True) -> list[dict]:
        """Words in the document: [{w, n, pages}] – case-insensitive, shown in their most common spelling.
        exclude_removed: words in text boxes that will be removed (e.g. a footer) are not counted."""
        drops, _ = self.decide(s, ov) if exclude_removed else ({}, {})
        idx = sorted({p for p in (pages if pages is not None else range(self.n_pages)) if 0 <= p < self.n_pages})
        counts: Counter = Counter()
        where: dict = defaultdict(set)
        forms: dict = defaultdict(Counter)
        for i in idx:
            c = Counter(tokenize(self.page_text(i)))
            d = drops.get(i)
            if d:
                for e in self.pages[i].elements:
                    if e.kind == TEXT and e.id in d:
                        c.subtract(tokenize(self.element_text(e)))
            for tok, k in c.items():
                if k <= 0:
                    continue
                key = tok.casefold()
                counts[key] += k
                where[key].add(i)
                forms[key][tok] += k
        return [{"w": forms[k].most_common(1)[0][0], "n": n, "pages": sorted(where[k]),
                 "num": k[0].isdigit()} for k, n in counts.most_common()]

    def summary(self, s: Settings, ov: Overrides) -> dict:
        drops, labels = self.decide(s, ov)
        counts: dict[str, int] = {}
        for lbl in labels.values():
            counts[lbl] = counts.get(lbl, 0) + 1
        return {"elements": len(labels), "removed": sum(len(v) for v in drops.values()), "classes": counts}

    # -------------------------------------------------------------- render
    def _placeholder(self, i: int, width: int) -> bytes:
        """A plain grey sheet in the page's proportions: shown when pdfium could not draw the page."""
        from PIL import Image
        p = self.pages[i] if i < len(self.pages) else None
        ratio = (p.height / p.width) if p and p.width > 0 else 1.414
        h = max(min(int(width * ratio), MAX_RENDER_SIDE), 1)
        return to_png(Image.new("RGB", (max(int(width), 1), h), (236, 237, 239)))

    def render_original(self, i: int, width: int = 900) -> bytes:
        png = render.service().png(self.uid, self.data, i, width)
        return png if png is not None else self._placeholder(i, width)

    def _distilled(self, pdf: pikepdf.Pdf, idx: list[int], s: Settings, ov: Overrides) -> bytes:
        """Copies pages idx of pdf into a new PDF, cleans them and returns its bytes."""
        drops, _, clips = self.decide_full(s, ov)
        new = pikepdf.new()
        for i in idx:
            new.pages.append(pdf.pages[i])
        kept = distill_pages(new, [(new.pages[j].obj, i) for j, i in enumerate(idx)], drops, s, clips)
        process_images(new, kept, s.grayscale, s.image_fade)
        buf = io.BytesIO()
        new.save(buf, fix_metadata_version=False)
        return buf.getvalue()

    def processed_page_pdf(self, i: int, s: Settings, ov: Overrides) -> bytes:
        with self.lock:
            return self._distilled(self.pdf, [i], s, ov)

    def render_processed(self, i: int, s: Settings, ov: Overrides, width: int = 900) -> bytes:
        svc = render.service()
        if svc.failed(self.uid, i):  # the original already crashed or hung pdfium: don't wait for it again
            return self._placeholder(i, width)
        data = self.processed_page_pdf(i, s, ov)
        key = f"{self.uid}:p:{uuid.uuid4().hex[:8]}"
        try:
            png = svc.png(key, data, 0, width)
        finally:
            svc.drop(key)
        return png if png is not None else self._placeholder(i, width)

    # -------------------------------------------------------------- ink estimate
    def ink_estimate(self, s: Settings, ov: Overrides, samples: int | None = None, width: int = 160,
                     ops: list[PageOp] | None = None) -> dict:
        """Ink coverage of the pages before and after cleaning, measured on rendered pages.

        original:    average share of a source page covered with ink
        processed:   the same for the pages that will be printed (ops: deleted pages are not printed)
        saving:      1 - processed / original: what the cleaning saves per page
        saved_pages: ink saved in full-page units, counting deleted pages and N-up (each page printed at
                     1/N of a sheet): original x source pages - processed x printed pages / N
        Measured on every page by default (a 24-page sample read 49 % where all 160 pages give 28 %);
        past INK_MAX_PAGES pages an even sample keeps a 20 000-page file from taking a minute."""
        n = self.n_pages
        out = [o.src for o in ops if 0 <= o.src < n] if ops is not None else list(range(n))
        res = {"original": 0, "processed": 0, "saving": 0, "pages": 0, "saved_pages": 0,
               "src_pages": n, "out_pages": len(out), "nup": s.nup}
        if n == 0:
            return res
        o_idx, p_idx = _spread(list(range(n)), samples), _spread(sorted(set(out)), samples)
        svc = render.service()
        o_vals = []
        for i in o_idx:
            if (i, width) not in self._ink_orig:  # the original never changes: measure it once
                self._ink_orig[i, width] = svc.ink(self.uid, self.data, i, width)
            if self._ink_orig[i, width] is not None:  # a page pdfium cannot draw is left out of the average
                o_vals.append(self._ink_orig[i, width])
        p_vals = []
        if p_idx:
            # Works on its own copy, so the page preview does not wait for it (0.02 s alone, 2 s behind one lock).
            with pikepdf.open(io.BytesIO(self.data)) as src:
                data = self._distilled(src, p_idx, s, ov)
            key = f"{self.uid}:ink:{uuid.uuid4().hex[:8]}"
            try:
                for j, i in enumerate(p_idx):
                    if self._ink_orig.get((i, width)) is None:
                        continue  # the original could not be drawn either: no fair comparison
                    v = svc.ink(key, data, j, width)
                    if v is not None:
                        p_vals.append(v)
            finally:
                svc.drop(key)
        if not o_vals:
            return res
        o = sum(o_vals) / len(o_vals)
        p = sum(p_vals) / len(p_vals) if p_vals else 0.0
        return {**res, "original": round(o, 4), "processed": round(p, 4),
                "saving": round(1 - p / o, 4) if o > 0 else 0.0, "pages": len(o_vals),
                "saved_pages": round(o * n - p * len(out) / max(s.nup, 1), 4)}

    def _ink_cost(self, e, s: Settings) -> float:
        """Estimated ink of one element as a share of its page (area x darkness). No rendering."""
        if e.kind == IMAGE:
            f = self.img_feats.get(e.sig)
            ink = f.get("ink", 0.5) if f else 0.5
            return e.area * ink * (1.0 - s.image_fade)
        if e.kind in (FILL, SHADING):
            return e.area * (1.0 - e.lum)
        return 0.0  # text and thin strokes: small, and needed

    def ink_report(self, s: Settings, ov: Overrides, top: int = 8) -> dict:
        """Per-page ink estimate of the print output and the elements that cost the most ink.

        Analytic (area x darkness of every kept element), so it is instant and covers every page;
        overlaps are counted twice and capped at 100 %. The rendered gauge (ink_estimate) stays the
        reference for the overall saving.
        pages:    [estimate per source page]
        heavy:    source pages above INK_HEAVY_PAGE
        hotspots: kept elements >= INK_HOTSPOT, grouped by signature, most total ink first
        page_hot: {heavy source page: [ids of its hotspot elements]} for highlighting in the preview
        """
        drops, labels, clips = self.decide_full(s, ov)
        pages, groups, page_hot = [], {}, {}
        for p in self.pages:
            d, pc = drops.get(p.index, ()), clips.get(p.index, {})
            total, hot_ids = 0.0, []
            for e in p.elements:
                if e.id in d:
                    continue
                c = self._ink_cost(e, s) * (0.5 if e.id in pc else 1.0)  # cropped: assume half stays
                total += c
                if c < INK_HOTSPOT:
                    continue
                hot_ids.append(e.id)
                g = groups.get(e.sig)
                if g is None:
                    g = groups[e.sig] = {"id": e.id, "sig": e.sig, "page": p.index, "kind": e.kind,
                                         "cls": labels.get(e.id, "other"), "share": 0.0, "pages": 0, "cost": 0.0}
                g["pages"] += 1
                g["cost"] += c
                if c > g["share"]:
                    g["share"], g["id"], g["page"] = c, e.id, p.index
            pages.append(round(min(total, 1.0), 3))
            if total >= INK_HEAVY_PAGE and hot_ids:
                page_hot[p.index] = hot_ids
        hot = sorted(groups.values(), key=lambda g: -g["cost"])[:top]
        for g in hot:
            g["share"], g["cost"] = round(min(g["share"], 1.0), 3), round(g["cost"], 3)
        return {"pages": pages, "heavy": [i for i, v in enumerate(pages) if v >= INK_HEAVY_PAGE],
                "limit": INK_HEAVY_PAGE, "hotspots": hot, "page_hot": page_hot}

    # -------------------------------------------------------------- export
    def export(self, s: Settings, ov: Overrides, ops: list[PageOp] | None = None) -> bytes:
        drops, _, clips = self.decide_full(s, ov)
        pdf = pikepdf.open(io.BytesIO(self.data))
        ops = ops if ops is not None else [PageOp(i) for i in range(len(pdf.pages))]
        needed = sorted({o.src for o in ops if 0 <= o.src < len(pdf.pages)})
        kept = distill_pages(pdf, [(pdf.pages[i].obj, i) for i in needed], drops, s, clips)
        process_images(pdf, kept, s.grayscale, s.image_fade)
        out = apply_page_ops(pdf, ops)
        try:
            out = nup(out, s.nup, s.paper)
        except Exception as e:  # e.g. JBIG2 images that can't be copied without jbig2dec: 1-up beats no file
            log.warning("N-up failed, exporting one page per sheet: %s", e)
        buf = io.BytesIO()
        try:
            out.remove_unreferenced_resources()
        except Exception as e:  # size optimisation only
            log.warning("could not prune resources: %s", e)
        out.save(buf, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 fix_metadata_version=False)
        data = buf.getvalue()
        try:  # never hand out an unreadable file (qpdf can write an xref stream without /Size for repaired input)
            with pikepdf.open(io.BytesIO(data)) as chk:
                len(chk.pages)
        except pikepdf.PdfError:
            log.warning("export failed verification; saving without object streams")
            buf = io.BytesIO()
            out.save(buf, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.disable,
                     fix_metadata_version=False)
            data = buf.getvalue()
        return data

    def close(self):
        render.service().drop(self.uid)
        with self.lock:  # a render still using self.pdf finishes first
            self.pdf.close()


def _spread(seq: list, samples: int | None) -> list:
    """At most min(samples, INK_MAX_PAGES) items of seq, evenly spread, in order."""
    k = min(len(seq), samples if samples is not None else len(seq), INK_MAX_PAGES)
    if k <= 0:
        return []
    return sorted({seq[round(j * (len(seq) - 1) / max(k - 1, 1))] for j in range(k)})


_WORD = re.compile(r"[^\W\d_](?:[\w'’-]*[^\W_])?|\d+(?:[.,/:]\d+)*")


def tokenize(text: str) -> list[str]:
    """Words and numbers. Joins end-of-line hyphenation (Wahrschein-\nlichkeit)."""
    text = re.sub(r"(\w)-\s*\r?\n\s*(\w)", r"\1\2", text)
    return _WORD.findall(text)


def region_for(view):
    """A "same position" region from a text box, with some slack in both directions
    (when the page number goes from 9 to 10 the box grows by a few points)."""
    x0, y0, x1, y1 = view
    h = y1 - y0
    return (max(0.0, x0 - 0.02), max(0.0, y0 - 0.3 * h), min(1.0, x1 + 0.02), min(1.0, y1 + 0.3 * h))

