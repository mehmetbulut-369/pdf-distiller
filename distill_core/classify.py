"""Öğe sınıflandırması ve silme kararları.

Analiz bir kez yapılır; kaydırıcılar/kademeler değiştikçe sadece bu modül
yeniden çalışır (hızlıdır, sayfaları tekrar okumaz).
"""
from __future__ import annotations

import math
from collections import defaultdict

from .imgfeat import TEXT_IMAGE
from .model import FILL, IMAGE, SHADING, TEXT, Overrides, PageInfo, Settings

WHITE_LUM = 0.95          # bundan açık dolgular mürekkep harcamaz; asla silinmez (altını açığa çıkarmamak için)
REPEAT_MIN_AREA = 0.0005  # madde imi gibi minik tekrarlar tema sayılmaz


def in_region(view, box) -> bool:
    """Metin kutusu alanın içinde mi: dikey merkezi alanın içinde ve yatayda kesişiyor."""
    cy = (view[1] + view[3]) / 2
    return box[1] <= cy <= box[3] and view[0] < box[2] and view[2] > box[0]


def signature_pages(pages: list[PageInfo]) -> dict[str, set]:
    sp: dict[str, set] = defaultdict(set)
    for p in pages:
        for e in p.elements:
            sp[e.sig].add(p.index)
    return sp


def classify(pages: list[PageInfo], s: Settings, ov: Overrides, sig_pages: dict | None = None,
             img_feats: dict | None = None, forced_keep: set | None = None):
    """Döner: (drops: {sayfa: {id,...}}, labels: {id: sınıf})

    sınıflar: white | background | repeated | large | other | text | text_repeated | text_image
    img_feats:   görsel imzası -> {"text": skor, ...}; yazılı görseller otomatik silinmez (ayarla)
    forced_keep: kırpılan görseller – kullanıcı açıkça "kaldır" demedikçe korunur
    """
    img_feats = img_feats or {}
    forced_keep = forced_keep or set()
    sig_pages = sig_pages if sig_pages is not None else signature_pages(pages)
    n = len(pages)
    min_pages = max(2, math.ceil(s.repeat_ratio * n)) if n > 1 else 10 ** 9

    drops: dict[int, set] = {}
    labels: dict[str, str] = {}
    el_ov, sig_ov, regions = ov.elements, ov.signatures, ov.regions

    for p in pages:
        d = set()
        for e in p.elements:
            if e.kind == TEXT:
                # Metin otomatik kademelerle silinmez; sadece seçimle veya "tekrarlayan metin" ayarıyla.
                rep = len(sig_pages.get(e.sig, ())) >= min_pages
                labels[e.id] = "text_repeated" if rep else "text"
                drop = s.remove_repeated_text and rep
                o = el_ov.get(e.id) or sig_ov.get(e.sig)
                if not o:
                    for r in reversed(regions):  # son eklenen kural öncelikli
                        if in_region(e.view, r["box"]):
                            o = r["action"]
                            break
                if o:
                    drop = o == "remove"
                if drop:
                    d.add(e.id)
                continue
            white = e.lum > WHITE_LUM  # raster görsellerde lum=0.5 olduğundan sadece dolgu/çizgi/maske etkilenir
            visual = e.kind in (FILL, IMAGE, SHADING)
            is_bg = visual and not white and e.area >= s.background_coverage
            is_rep = (not white and e.area >= REPEAT_MIN_AREA
                      and len(sig_pages.get(e.sig, ())) >= min_pages)
            is_large = visual and not white and e.area >= s.large_threshold

            f = img_feats.get(e.sig) if e.kind == IMAGE else None
            text_img = bool(f) and f["text"] >= TEXT_IMAGE
            if white:
                label = "white"
            elif text_img:
                label = "text_image"
            elif is_bg:
                label = "background"
            elif is_rep:
                label = "repeated"
            elif is_large:
                label = "large"
            else:
                label = "other"
            labels[e.id] = label

            drop = (
                (s.remove_backgrounds and is_bg)
                or (s.remove_repeated and is_rep)
                or (s.remove_large_images and is_large and e.kind == IMAGE)
                or (s.remove_large_shapes and is_large and e.kind != IMAGE)
                or (s.remove_all_graphics and not white)
            )
            if text_img and s.keep_text_images:
                drop = False
            o = el_ov.get(e.id) or sig_ov.get(e.sig)
            if o == "remove":
                drop = True
            elif o == "keep":
                drop = False
            if e.id in forced_keep and el_ov.get(e.id) != "remove":
                drop = False
            if drop:
                d.add(e.id)
        if d:
            drops[p.index] = d
    return drops, labels
