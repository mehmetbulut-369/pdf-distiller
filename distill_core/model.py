"""Data models: settings, tiers, elements, manual overrides, page operations.

This file is UI-independent; the web UI, a desktop wrapper or a batch script
exchange the same models as JSON.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Literal

TextMode = Literal["keep", "auto", "black"]

# Element kinds
IMAGE = "image"      # raster image (XObject or inline)
FILL = "fill"        # filled vector shape
STROKE = "stroke"    # line / stroke
SHADING = "shading"  # shading (sh operator)
TEXT = "text"        # consecutive text pieces on one line (a "text box")


@dataclass
class Settings:
    """All settings of one distillation. Tiers are presets of this."""

    remove_backgrounds: bool = False   # backgrounds covering most of the page
    remove_repeated: bool = False      # theme elements repeated on most pages
    remove_large_images: bool = False  # raster images above the threshold
    remove_large_shapes: bool = False  # filled shapes / shadings above the threshold
    remove_all_graphics: bool = False  # everything except text (white fills excepted)
    remove_repeated_text: bool = False # text repeated at the same place with the same content (header/footer)
    keep_text_images: bool = True      # images containing text (tables, formulas, screenshots) are not removed automatically
    auto_crop_photos: bool = False     # automatically crop photo regions out of kept images

    large_threshold: float = 0.10      # "large" threshold as a share of the page area
    repeat_ratio: float = 0.30         # an element on at least this share of pages counts as "repeated"
    background_coverage: float = 0.60  # a fill covering more than this share of the page = background

    text_mode: TextMode = "auto"       # keep | auto (make light text black) | black (all text black)
    grayscale: bool = False            # convert vector colours and images to gray
    image_fade: float = 0.0            # fade remaining images towards white (0 = off, 0.8 = very faint)
    nup: int = 1                       # pages per sheet: 1, 2, 4, 6

    @classmethod
    def from_dict(cls, d: dict | None) -> Settings:
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
    """Tier presets. Thresholds and extra switches (gray, N-up) are kept from `base`."""
    s = Settings.from_dict(base.to_dict() if base else {})
    s.remove_backgrounds = tier >= 1
    s.remove_repeated = tier >= 1
    s.remove_large_images = tier >= 2
    s.remove_large_shapes = tier >= 2
    s.remove_all_graphics = tier >= 3
    s.text_mode = "black" if tier >= 3 else ("auto" if tier >= 1 else "keep")
    return s


TIERS = {
    0: "Original",
    1: "Light",
    2: "Medium",
    3: "Maximum",
}


@dataclass
class Overrides:
    """The user's manual decisions. They override the automatic classification.

    elements:   {"<page>-<seq>": "keep" | "remove"}  a single element (text box id: "<page>-t<seq>")
    signatures: {"<sig>": "keep" | "remove"}         all elements with that signature
                                                     (for text: same content + same position)
    crops:      [{"id": "<image element id>", "all": bool, "mode": "keep"|"erase"|"auto",
                  "points": [[x, y], ...]}]  polygon in view coordinates (quad = 4 points).
                keep: only the inside is printed; erase: the inside is removed; auto: the photo
                regions of the image are removed. all=True applies to every copy of the same image
                on all pages. A cropped image is kept automatically.
    regions:    [{"box": [x0,y0,x1,y1], "action": "remove"|"keep"}]
                region in view coordinates (0..1); applied on every page to the TEXT boxes in it
                (even if the content differs, e.g. a footer with page numbers)
    Priority: element > signature > region > automatic.
    """

    elements: dict[str, str] = field(default_factory=dict)
    signatures: dict[str, str] = field(default_factory=dict)
    regions: list[dict] = field(default_factory=list)
    crops: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict | None) -> Overrides:
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
    """One output page: source page index + extra rotation (multiple of 90)."""

    src: int
    rotate: int = 0


@dataclass
class Element:
    """A removable visual element found during analysis."""

    id: str               # "<page>-<seq>": deterministic, by drawing order on the page
    page: int
    kind: str             # image | fill | stroke | shading
    bbox: tuple           # (x0, y0, x1, y1) in PDF user space, intersected with the clip
    view: tuple           # normalised (0..1) view box, top-left origin, rotation applied
    area: float           # share of the page area (0..1)
    lum: float            # luminance 0 (black) .. 1 (white); 0.5 if unknown
    sig: str              # signature for repeat detection
    m: tuple | None = None    # images: CTM at draw time (unit square -> page); for cropping
    obj: tuple | None = None  # images: XObject objgen; for content analysis

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
    width: float          # view width (pt), rotation applied
    height: float
    rotate: int
    elements: list[Element] = field(default_factory=list)
    box: tuple = (0.0, 0.0, 612.0, 792.0)  # visible box in PDF user space (CropBox)
    failed: bool = False  # content could not be analysed; the page is kept as it is
