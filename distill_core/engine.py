"""Üst seviye API. Arayüzler (web, masaüstü, toplu işlem) sadece bu sınıfı kullanır.

    doc = DistillDocument(pdf_bytes)
    doc.analyze()
    png = doc.render_processed(0, settings, overrides)
    out_bytes = doc.export(settings, overrides, page_ops)
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from collections import Counter, defaultdict
import threading
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pikepdf
import pypdfium2 as pdfium

from .classify import classify, in_region, signature_pages
from .images import process_images
from .imgfeat import image_features
from .interpreter import (Caches, PageWalker, apply, invert, page_box, page_rotation, user_to_view,
                          view_mapper, view_to_user)
from .model import IMAGE, TEXT, Overrides, PageInfo, PageOp, Settings
from .pageops import apply_page_ops, nup

# pdfium iş parçacığı güvenli değildir; tüm render çağrıları bu kilitten geçer.
PDFIUM_LOCK = threading.RLock()


FEATURE_MIN_AREA = 0.02  # içerik analizi bu boyuttan büyük görsellere yapılır (logo/ikonlar atlanır)


def _analyze_range(data: bytes, start: int, stop: int):
    pdf = pikepdf.open(io.BytesIO(data))
    caches = Caches()
    pages = [_analyze_page(pdf, i, caches) for i in range(start, stop)]
    return pages, _features_for(pdf, pages)


def _features_for(pdf, pages, known=None) -> dict:
    """Büyük görsellerin içerik özellikleri, imzaya göre (aynı görsel bir kez analiz edilir)."""
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
    walker.run()
    return PageInfo(i, w, h, rot, walker.elements, box)


def _needs_rewrite(drops, s: Settings) -> bool:
    return bool(drops) or s.text_mode != "keep" or s.grayscale


def distill_pages(pdf: pikepdf.Pdf, items, drops: dict, s: Settings, clips: dict | None = None) -> set:
    """items: [(sayfa_nesnesi, kaynak_indeks)] – sayfaları yerinde yeniden yazar.
    Görünür kalan görsel objgen kümesini döner."""
    caches = Caches()
    kept = set()
    for page_obj, idx in items:
        d = drops.get(idx, set())
        c = (clips or {}).get(idx)
        if not _needs_rewrite(d, s) and not c:
            if s.image_fade > 0:
                w = PageWalker(pdf, idx, page_obj, rewrite=True, drops=set(), caches=caches)
                w.run()
                kept |= w.kept_images
            continue
        w = PageWalker(pdf, idx, page_obj, rewrite=True, drops=d, text_mode=s.text_mode,
                       grayscale=s.grayscale, caches=caches, clips=c)
        w.run()
        kept |= w.kept_images
    return kept


def ink_coverage(img) -> float:
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    return float((765.0 - a.sum(axis=2)).mean() / 765.0)


class DistillDocument:
    def __init__(self, data: bytes, name: str = "document.pdf"):
        self.data = data
        self.name = name
        self.lock = threading.RLock()
        self.pdf = pikepdf.open(io.BytesIO(data))
        self.n_pages = len(self.pdf.pages)
        self.pages: list[PageInfo] = []
        self.sig_pages: dict = {}
        self._decisions: dict = {}
        self._pdfium = None
        self.analysis_seconds = 0.0
        self._page_text: dict[int, str] = {}     # pdfium ile çıkarılan sayfa metni
        self._el_text: dict[str, str] = {}       # metin kutusu kimliği -> okunur metin
        self.img_feats: dict = {}                # görsel imzası -> içerik özellikleri (imgfeat)
        self._by_id: dict = {}
        self._by_sig: dict = {}

    # -------------------------------------------------------------- analiz
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
        self.sig_pages = signature_pages(self.pages)
        self._by_id = {e.id: e for p in self.pages for e in p.elements}
        self._by_sig: dict = defaultdict(list)
        for p in self.pages:
            for e in p.elements:
                if e.kind == IMAGE:
                    self._by_sig[e.sig].append(e)
        self._decisions.clear()
        self.analysis_seconds = time.perf_counter() - t
        return self.pages

    # -------------------------------------------------------------- kararlar
    def decide(self, s: Settings, ov: Overrides):
        """(drops, labels) – bkz. classify."""
        return self.decide_full(s, ov)[:2]

    def decide_full(self, s: Settings, ov: Overrides):
        """(drops, labels, clips). clips: {sayfa: {görsel_id: {"keep": [çokgen], "erase": [çokgen]}}}
        çokgenler görselin birim karesinde (PDF görsel uzayı, sol-alt orijin)."""
        key = hashlib.md5(json.dumps([s.to_dict(), ov.to_dict()], sort_keys=True).encode()).hexdigest()
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

    # -------------------------------------------------------------- kırpma
    def features(self, e) -> dict | None:
        """Görselin içerik özellikleri (önbellekli; küçük görseller için istek anında hesaplanır)."""
        if e.sig not in self.img_feats:
            with self.lock:
                self.img_feats[e.sig] = image_features(self.pdf, e.obj) if e.obj else None
        return self.img_feats.get(e.sig)

    @staticmethod
    def _photo_polys(f) -> list:
        # analiz kutuları sol-üst orijinli; PDF görsel birim karesi sol-alt orijinli
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
                # sadece karma görseller: içinde yazı da olan (saf fotoğrafı tamamen silmek kırpma değil)
                if f and f["photos"] and f["text"] >= 0.35:
                    clips[p.index][e.id] = {"keep": [], "erase": self._photo_polys(f)}

    def clip_view(self, e, spec) -> dict:
        page = self.pages[e.page]
        u2v = user_to_view(page.box, page.rotate)
        conv = lambda poly: [[round(v, 4) for v in u2v(*apply(e.m, x, y))] for x, y in poly]  # noqa: E731
        return {"keep": [conv(p) for p in spec.get("keep", [])], "erase": [conv(p) for p in spec.get("erase", [])]}

    def page_elements(self, i: int, s: Settings, ov: Overrides, min_area: float = 0.0008):
        """Arayüz için: bir sayfanın tıklanabilir öğeleri, sınıf ve silinme durumu ile.
        Metin kutularında okunur metin ("text") ve aynı konumda metin bulunan sayfa sayısı da döner."""
        drops, labels, clips = self.decide_full(s, ov)
        d = drops.get(i, set())
        pclips = clips.get(i, {})
        out = []
        for e in self.pages[i].elements:
            is_text = e.kind == TEXT
            if e.area < min_area and not is_text:
                continue
            item = e.to_dict()
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
            with PDFIUM_LOCK:
                tp = self._pdfium_doc()[e.page].get_textpage()
                # kenarlardan biraz içeride sor: komşu satırdan harf taşımasın
                h = y1 - y0
                t = tp.get_text_bounded(x0, y0 + h * 0.2, x1, y1 - h * 0.2)
                tp.close()
            t = " ".join(t.split())
            self._el_text[e.id] = t
        return t

    def region_pages(self, box) -> int:
        n = 0
        for p in self.pages:
            if any(e.kind == TEXT and in_region(e.view, box) for e in p.elements):
                n += 1
        return n

    # -------------------------------------------------------------- kelime sayacı
    def page_text(self, i: int) -> str:
        t = self._page_text.get(i)
        if t is None:
            with PDFIUM_LOCK:
                tp = self._pdfium_doc()[i].get_textpage()
                t = tp.get_text_range()
                tp.close()
            self._page_text[i] = t
        return t

    def word_counts(self, s: Settings, ov: Overrides, pages: list[int] | None = None,
                    exclude_removed: bool = True) -> list[dict]:
        """Belgedeki kelimeler: [{w, n, pages}] – büyük/küçük harf duyarsız, en sık yazılış biçimiyle.
        exclude_removed: kaldırılacak metin kutularındaki kelimeler sayılmaz (ör. alt bilgi)."""
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
    def _pdfium_doc(self):
        if self._pdfium is None:
            self._pdfium = pdfium.PdfDocument(self.data)
        return self._pdfium

    @staticmethod
    def _render(doc, i: int, width: int):
        page = doc[i]
        w, _h = page.get_size()
        scale = max(width / max(w, 1.0), 0.02)
        return page.render(scale=scale).to_pil()

    def render_original(self, i: int, width: int = 900) -> bytes:
        with PDFIUM_LOCK:
            img = self._render(self._pdfium_doc(), i, width)
        return _png(img)

    def processed_page_pdf(self, i: int, s: Settings, ov: Overrides) -> bytes:
        drops, _, clips = self.decide_full(s, ov)
        with self.lock:
            new = pikepdf.new()
            new.pages.append(self.pdf.pages[i])
            kept = distill_pages(new, [(new.pages[0].obj, i)], drops, s, clips)
            process_images(new, kept, s.grayscale, s.image_fade)
            buf = io.BytesIO()
            new.save(buf)
        return buf.getvalue()

    def render_processed(self, i: int, s: Settings, ov: Overrides, width: int = 900) -> bytes:
        data = self.processed_page_pdf(i, s, ov)
        with PDFIUM_LOCK:
            doc = pdfium.PdfDocument(data)
            img = self._render(doc, 0, width)
            doc.close()
        return _png(img)

    # -------------------------------------------------------------- mürekkep tahmini
    def ink_estimate(self, s: Settings, ov: Overrides, samples: int = 24, width: int = 160) -> dict:
        n = self.n_pages
        if n == 0:
            return {"original": 0, "processed": 0, "saving": 0, "pages": 0}
        k = min(samples, n)
        idx = sorted({round(j * (n - 1) / max(k - 1, 1)) for j in range(k)})
        drops, _, clips = self.decide_full(s, ov)
        with self.lock:
            new = pikepdf.new()
            for i in idx:
                new.pages.append(self.pdf.pages[i])
            kept = distill_pages(new, [(new.pages[j].obj, i) for j, i in enumerate(idx)], drops, s, clips)
            process_images(new, kept, s.grayscale, s.image_fade)
            buf = io.BytesIO()
            new.save(buf)
        o_sum = p_sum = 0.0
        with PDFIUM_LOCK:
            od = self._pdfium_doc()
            pd = pdfium.PdfDocument(buf.getvalue())
            for j, i in enumerate(idx):
                o_sum += ink_coverage(self._render(od, i, width))
                p_sum += ink_coverage(self._render(pd, j, width))
            pd.close()
        o, p = o_sum / len(idx), p_sum / len(idx)
        return {"original": round(o, 4), "processed": round(p, 4),
                "saving": round(1 - p / o, 4) if o > 0 else 0.0, "pages": len(idx)}

    # -------------------------------------------------------------- dışa aktarma
    def export(self, s: Settings, ov: Overrides, ops: list[PageOp] | None = None) -> bytes:
        drops, _, clips = self.decide_full(s, ov)
        pdf = pikepdf.open(io.BytesIO(self.data))
        ops = ops if ops is not None else [PageOp(i) for i in range(len(pdf.pages))]
        needed = sorted({o.src for o in ops if 0 <= o.src < len(pdf.pages)})
        kept = distill_pages(pdf, [(pdf.pages[i].obj, i) for i in needed], drops, s, clips)
        process_images(pdf, kept, s.grayscale, s.image_fade)
        out = apply_page_ops(pdf, ops)
        out = nup(out, s.nup)
        buf = io.BytesIO()
        out.remove_unreferenced_resources()
        out.save(buf, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        return buf.getvalue()

    def close(self):
        with PDFIUM_LOCK:
            if self._pdfium is not None:
                self._pdfium.close()
                self._pdfium = None
        self.pdf.close()


_WORD = re.compile(r"[^\W\d_](?:[\w'’-]*[^\W_])?|\d+(?:[.,/:]\d+)*")


def tokenize(text: str) -> list[str]:
    """Kelimeler ve sayılar. Satır sonundaki tirelemeyi birleştirir (Wahrschein-\nlichkeit)."""
    text = re.sub(r"(\w)-\s*\r?\n\s*(\w)", r"\1\2", text)
    return _WORD.findall(text)


def region_for(view):
    """Bir metin kutusundan "aynı konum" alanı: yatayda ve dikeyde biraz pay bırakır
    (sayfa numarası 9'dan 10'a geçince kutu birkaç punto genişler)."""
    x0, y0, x1, y1 = view
    h = y1 - y0
    return (max(0.0, x0 - 0.02), max(0.0, y0 - 0.3 * h), min(1.0, x1 + 0.02), min(1.0, y1 + 0.3 * h))


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
