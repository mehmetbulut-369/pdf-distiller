"""Veri modelleri: ayarlar, kademeler, öğeler, manuel düzeltmeler, sayfa işlemleri.

Bu dosya arayüzden bağımsızdır; web arayüzü, masaüstü sarmalayıcı veya toplu
işlem betiği aynı modelleri JSON olarak gönderip alır.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Literal

TextMode = Literal["keep", "auto", "black"]

# Öğe türleri
IMAGE = "image"      # raster görsel (XObject veya satır içi)
FILL = "fill"        # dolgulu vektör şekil
STROKE = "stroke"    # çizgi / kontur
SHADING = "shading"  # gradyan (sh operatörü)
TEXT = "text"        # aynı satırdaki ardışık metin parçaları (bir "metin kutusu")


@dataclass
class Settings:
    """Bir distilasyon işleminin tüm ayarları. Kademeler bunun hazır halleridir."""

    remove_backgrounds: bool = False   # sayfanın büyük kısmını kaplayan zeminler
    remove_repeated: bool = False      # sayfaların çoğunda tekrar eden tema öğeleri
    remove_large_images: bool = False  # eşik üstü raster görseller
    remove_large_shapes: bool = False  # eşik üstü dolgulu şekiller / gradyanlar
    remove_all_graphics: bool = False  # metin dışı her şey (beyaz dolgular hariç)
    remove_repeated_text: bool = False # aynı yerde, aynı içerikle tekrar eden metin (üst/alt bilgi)
    keep_text_images: bool = True      # yazı içeren görseller (tablo, formül, ekran görüntüsü) otomatik silinmez
    auto_crop_photos: bool = False     # korunan görsellerin içindeki fotoğraf bölgelerini otomatik kırp

    large_threshold: float = 0.10      # sayfa alanına oranla "büyük" eşiği
    repeat_ratio: float = 0.30         # bir öğe sayfaların en az bu oranında geçerse "tekrarlayan"
    background_coverage: float = 0.60  # sayfanın bu oranından fazlasını kaplayan dolgu = zemin

    text_mode: TextMode = "auto"       # keep | auto (açık renkli metni siyah yap) | black (tüm metin siyah)
    grayscale: bool = False            # vektör renkleri ve görselleri griye çevir
    image_fade: float = 0.0            # kalan görselleri beyaza doğru soldur (0 = kapalı, 0.8 = çok soluk)
    nup: int = 1                       # kâğıt başına sayfa: 1, 2, 4, 6

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        d = d or {}
        names = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in d.items() if k in names})
        s.large_threshold = min(max(float(s.large_threshold), 0.005), 1.0)
        s.repeat_ratio = min(max(float(s.repeat_ratio), 0.05), 1.0)
        s.background_coverage = min(max(float(s.background_coverage), 0.2), 1.0)
        s.image_fade = min(max(float(s.image_fade), 0.0), 0.9)
        if s.text_mode not in ("keep", "auto", "black"):
            s.text_mode = "auto"
        if int(s.nup) not in (1, 2, 4, 6):
            s.nup = 1
        s.nup = int(s.nup)
        return s

    def to_dict(self) -> dict:
        return asdict(self)


def tier_settings(tier: int, base: Settings | None = None) -> Settings:
    """Kademe hazır ayarları. Eşikler ve ek anahtarlar (gri, N-up) `base`'den korunur."""
    s = Settings.from_dict(base.to_dict() if base else {})
    s.remove_backgrounds = tier >= 1
    s.remove_repeated = tier >= 1
    s.remove_large_images = tier >= 2
    s.remove_large_shapes = tier >= 2
    s.remove_all_graphics = tier >= 3
    s.text_mode = "black" if tier >= 3 else ("auto" if tier >= 1 else "keep")
    return s


TIERS = {
    0: "Orijinal",
    1: "Hafif – tekrarlayan tema ve zeminler",
    2: "Orta – + büyük görsel ve şekiller",
    3: "Maksimum – sadece metin",
}


@dataclass
class Overrides:
    """Kullanıcının manuel kararları. Otomatik sınıflandırmanın üstüne yazılır.

    elements:   {"<sayfa>-<sıra>": "keep" | "remove"}  tek bir öğe (metin kutusu kimliği "<sayfa>-t<sıra>")
    signatures: {"<imza>": "keep" | "remove"}          aynı imzalı tüm öğeler (metinde: aynı içerik + aynı konum)
    crops:      [{"id": "<görsel öğe kimliği>", "all": bool, "mode": "keep"|"erase"|"auto",
                  "points": [[x, y], ...]}]  görüntü koordinatlarında çokgen (dörtgen = 4 nokta).
                keep: sadece çokgenin içi basılır; erase: çokgenin içi silinir; auto: görseldeki fotoğraf
                bölgeleri silinir. all=True aynı görselin tüm sayfalardaki kopyalarına uygular.
                Kırpılan görsel otomatik olarak korunur.
    regions:    [{"box": [x0,y0,x1,y1], "action": "remove"|"keep"}]
                görüntü koordinatlarında (0..1) alan; her sayfada bu alandaki METİN kutularına uygulanır
                (içerik farklı olsa da: sayfa numaralı alt bilgi gibi)
    Öncelik: element > signature > region > otomatik.
    """

    elements: dict[str, str] = field(default_factory=dict)
    signatures: dict[str, str] = field(default_factory=dict)
    regions: list[dict] = field(default_factory=list)
    crops: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Overrides":
        d = d or {}
        regions = []
        for r in d.get("regions") or []:
            try:
                box = [float(v) for v in r["box"]][:4]
                if len(box) == 4 and r.get("action") in ("remove", "keep"):
                    regions.append({"box": box, "action": r["action"]})
            except (KeyError, TypeError, ValueError):
                continue
        crops = []
        for c in d.get("crops") or []:
            try:
                mode = c.get("mode")
                pts = [[float(x), float(y)] for x, y in (c.get("points") or [])][:400]
                if mode not in ("keep", "erase", "auto") or (mode != "auto" and len(pts) < 3):
                    continue
                crops.append({"id": str(c["id"]), "all": bool(c.get("all")), "mode": mode, "points": pts})
            except (KeyError, TypeError, ValueError):
                continue
        return cls(elements=dict(d.get("elements") or {}), signatures=dict(d.get("signatures") or {}),
                   regions=regions, crops=crops)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageOp:
    """Çıktıdaki bir sayfa: kaynak sayfa indeksi + ek döndürme (90'ın katı)."""

    src: int
    rotate: int = 0


@dataclass
class Element:
    """Analizde bulunan, silinebilir bir görsel öğe."""

    id: str               # "<sayfa>-<sıra>": aynı sayfada çizim sırasına göre deterministik
    page: int
    kind: str             # image | fill | stroke | shading
    bbox: tuple           # PDF kullanıcı uzayında (x0, y0, x1, y1), kırpma ile kesişmiş
    view: tuple           # görüntüde normalize (0..1) kutu, sol-üst orijinli, döndürme uygulanmış
    area: float           # sayfa alanına oranı (0..1)
    lum: float            # parlaklık 0 (siyah) .. 1 (beyaz); bilinmiyorsa 0.5
    sig: str              # tekrar tespiti imzası
    m: tuple | None = None    # görsellerde: çizim anındaki CTM (birim kare -> sayfa); kırpma için
    obj: tuple | None = None  # görsellerde: XObject objgen; içerik analizi için

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "view": [round(v, 4) for v in self.view],
            "area": round(self.area, 5),
            "lum": round(self.lum, 3),
            "sig": self.sig,
        }


@dataclass
class PageInfo:
    index: int
    width: float          # görüntü genişliği (pt), döndürme uygulanmış
    height: float
    rotate: int
    elements: list[Element] = field(default_factory=list)
    box: tuple = (0.0, 0.0, 612.0, 792.0)  # PDF kullanıcı uzayında görünür kutu (CropBox)
