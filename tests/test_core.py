"""Core engine tests.  Run:  python -m pytest -q

These tests must pass after any change, including changes made with smaller models.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pikepdf
import pypdfium2 as pdfium
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402

from distill_core import DistillDocument, Overrides, PageOp, Settings, tier_settings  # noqa: E402


def _bytes(pdf: pikepdf.Pdf) -> bytes:
    b = io.BytesIO()
    pdf.save(b)
    return b.getvalue()


@pytest.fixture(scope="module")
def dark():
    d = DistillDocument(_bytes(make_samples.dark_deck(12)))
    d.analyze()
    return d


@pytest.fixture(scope="module")
def light():
    d = DistillDocument(_bytes(make_samples.light_deck(10)))
    d.analyze()
    return d


@pytest.fixture(scope="module")
def beamer():
    d = DistillDocument(_bytes(make_samples.form_deck(8)))
    d.analyze()
    return d


def render(data: bytes, i: int, width=720):
    doc = pdfium.PdfDocument(data)
    page = doc[i]
    w, _ = page.get_size()
    img = page.render(scale=width / w).to_pil().convert("RGB")
    doc.close()
    return np.asarray(img).astype(int)


def reanalyze(data: bytes) -> DistillDocument:
    d = DistillDocument(data)
    d.analyze(workers=1)
    return d


# ----------------------------------------------------------------------------- classification
def test_classes_dark(dark):
    _, labels = dark.decide(Settings(), Overrides())
    cls = {}
    for e in dark.pages[0].elements:
        cls.setdefault(labels[e.id], []).append(e.kind)
    assert "fill" in cls["background"]                     # dark full-page background
    assert "image" in cls["repeated"]                      # logo
    assert "stroke" in cls["repeated"]                     # bottom rule


def test_white_fill_never_removed(light):
    drops, labels = light.decide(tier_settings(3), Overrides())
    for p in light.pages:
        for e in p.elements:
            if labels[e.id] == "white":
                assert e.id not in drops.get(p.index, set())


def test_tier3_leaves_only_text(dark):
    out = dark.export(tier_settings(3), Overrides())
    d2 = reanalyze(out)
    assert sum(1 for p in d2.pages for e in p.elements if e.kind != "text") == 0


def test_ids_are_stable_between_passes(dark):
    """The element removed must be exactly the one chosen in analysis: remove the logo, then re-analyse."""
    logo = next(e for e in dark.pages[0].elements if e.kind == "image")
    ov = Overrides(elements={logo.id: "remove"})
    data = dark.processed_page_pdf(0, Settings(), ov)
    d2 = reanalyze(data)
    kinds = [e.kind for e in d2.pages[0].elements if e.kind != "text"]
    assert "image" not in kinds
    assert len(kinds) == sum(1 for e in dark.pages[0].elements if e.kind != "text") - 1


# ----------------------------------------------------------------------------- text colour
def test_light_text_becomes_black_when_background_removed(dark):
    data = dark.processed_page_pdf(0, tier_settings(1), Overrides())
    img = render(data, 0)
    title = img[15:40, 20:280]  # title area
    assert title.min() < 60, "white title text should have turned black"
    assert img.mean() > 240, "background should be white"


def test_text_on_kept_dark_box_stays_light(dark):
    data = dark.processed_page_pdf(2, tier_settings(1), Overrides())  # page 3: dark red box
    img = render(data, 0)
    box = img[405 - 140:405 - 70, 120:400]
    red = (box[..., 0] > 100) & (box[..., 1] < 60)
    assert red.mean() > 0.5, "box should be kept"
    assert (box.sum(axis=2) > 600).any(), "white text in the box should stay white"


def test_keep_mode_does_not_touch_text(dark):
    data = dark.processed_page_pdf(0, Settings(text_mode="keep"), Overrides())
    assert reanalyze(data).pages[0].elements  # content unchanged
    orig = render(dark.processed_page_pdf(0, Settings(), Overrides()), 0)
    assert np.abs(orig - render(data, 0)).max() < 3


# ----------------------------------------------------------------------------- gray / fade
def test_grayscale(dark):
    data = dark.processed_page_pdf(1, Settings(grayscale=True), Overrides())  # page with a photo
    img = render(data, 0)
    sat = img.max(axis=2) - img.min(axis=2)
    assert sat.max() < 12


def test_image_fade_reduces_ink(dark):
    a = render(dark.processed_page_pdf(1, Settings(), Overrides()), 0)
    b = render(dark.processed_page_pdf(1, Settings(image_fade=0.6), Overrides()), 0)
    region = (slice(405 - 260, 405 - 60), slice(390, 690))
    assert b[region].mean() > a[region].mean() + 30


# ----------------------------------------------------------------------------- manual overrides
def test_override_keep_background(dark):
    bg = next(e for e in dark.pages[0].elements if e.area > 0.9)
    drops, _ = dark.decide(tier_settings(1), Overrides(elements={bg.id: "keep"}))
    assert bg.id not in drops[0]
    assert all(dark.pages[p].elements[0].id in drops[p] for p in range(1, 12))


def test_signature_override_removes_everywhere(dark):
    logo = next(e for e in dark.pages[0].elements if e.kind == "image")
    drops, _ = dark.decide(Settings(), Overrides(signatures={logo.sig: "remove"}))
    assert len(drops) == 12


# ----------------------------------------------------------------------------- forms and rotation
def test_beamer_theme_form_is_deduplicated(beamer):
    out = beamer.export(tier_settings(1), Overrides())
    pdf = pikepdf.open(io.BytesIO(out))
    copies = set()
    for p in pdf.pages:
        for k, v in p.Resources.XObject.items():
            if k.startswith("/DZ"):
                copies.add(v.objgen)
    assert len(copies) == 1
    assert sum(1 for p in reanalyze(out).pages for e in p.elements if e.kind != "text") == 0


def test_rotated_page_view_coordinates(beamer):
    p = beamer.pages[7]
    assert p.rotate == 90 and p.width < p.height
    box = next(e for e in p.elements if e.kind == "fill" and 0.05 < e.area < 0.1)  # 200x80 dark box
    x0, y0, x1, y1 = box.view
    assert x1 - x0 < y1 - y0  # should look vertical once rotated


# ----------------------------------------------------------------------------- page operations
def test_page_ops_and_nup(light):
    ops = [PageOp(3, 90), PageOp(0), PageOp(1)]
    out = light.export(Settings(), Overrides(), ops)
    pdf = pikepdf.open(io.BytesIO(out))
    assert len(pdf.pages) == 3 and int(pdf.pages[0].obj.get("/Rotate", 0)) == 90
    out4 = light.export(Settings(nup=4), Overrides())
    assert len(pikepdf.open(io.BytesIO(out4)).pages) == 3  # 10 pages / 4


def test_ink_estimate_monotonic(dark):
    ov = Overrides()
    vals = [dark.ink_estimate(tier_settings(t), ov)["processed"] for t in range(4)]
    assert vals[0] > vals[1] > vals[2] >= vals[3]


# ----------------------------------------------------------------------------- text selection
@pytest.fixture(scope="module")
def hhn():
    d = DistillDocument(_bytes(make_samples.hhn_deck(6)))
    d.analyze()
    return d


def _text(d, page, needle):
    return next(it for it in d.page_elements(page, Settings(), Overrides())
                if it["kind"] == "text" and it["text"] == needle)


def _dark_pixels(img, view, w=720, h=405):
    x0, y0, x1, y1 = view
    box = img[int(y0 * h):int(y1 * h) + 1, int(x0 * w):int(x1 * w) + 1]
    return int((box.sum(axis=2) < 450).sum())


def test_text_pieces_grouped_into_one_box(hhn):
    footer = _text(hhn, 2, "Prof. Dr. Dieter Maier Winter 26-27")
    assert footer["pages_with_sig"] == 6


def test_same_text_same_place_removed_everywhere_only_there(hhn):
    head = _text(hhn, 0, "Informatik 1")  # top-left corner
    assert head["pages_with_sig"] == 6
    ov = Overrides(signatures={head["sig"]: "remove"})
    for page in (0, 3):
        img = render(hhn.processed_page_pdf(page, Settings(), ov), 0)
        assert _dark_pixels(img, head["view"]) == 0, "top-left title should be removed"
        body = next(it for it in hhn.page_elements(page, Settings(), ov)
                    if it["kind"] == "text" and "Informatik 1" in it["text"] and it["view"][1] > 0.25)
        assert not body["drop"]
        assert _dark_pixels(img, body["view"]) > 50, "'Informatik 1' in the body should stay"


def test_removed_text_keeps_neighbours_in_place(hhn):
    """Removal works by making text invisible: later pieces on the same line must not shift."""
    date = _text(hhn, 1, "22/09/2026")
    prof = _text(hhn, 1, "Prof. Dr. Dieter Maier Winter 26-27")
    a = render(hhn.processed_page_pdf(1, Settings(), Overrides()), 0)
    b = render(hhn.processed_page_pdf(1, Settings(), Overrides(elements={date["id"]: "remove"})), 0)
    assert _dark_pixels(b, date["view"]) == 0
    assert np.abs(a - b)[int(prof["view"][1] * 405):, int(prof["view"][0] * 720):].max() < 3


def test_region_removes_footer_with_changing_page_number(hhn):
    pn = _text(hhn, 0, "Info1 Kapitel 0: Organisation - 1")
    assert pn["pages_with_sig"] == 1 and pn["pages_with_region"] == 6
    drops, _ = hhn.decide(Settings(), Overrides(regions=[{"box": pn["region"], "action": "remove"}]))
    assert all(len(drops[p]) == 1 for p in range(6))


def test_repeated_text_setting(hhn):
    drops, labels = hhn.decide(Settings(remove_repeated_text=True), Overrides())
    removed = {hhn.element_text(e) for p in hhn.pages for e in p.elements if e.id in drops.get(p.index, ())}
    assert {"Informatik 1", "22/09/2026", "Prof. Dr. Dieter Maier Winter 26-27"} <= removed
    assert not any("Kapitel 1" in t for t in removed)


def test_tiers_never_remove_text(hhn):
    drops, _ = hhn.decide(tier_settings(3), Overrides())
    assert not any("-t" in i for v in drops.values() for i in v)


# ----------------------------------------------------------------------------- word counter
def test_word_counts(hhn):
    words = {w["w"]: w for w in hhn.word_counts(Settings(), Overrides())}
    assert words["Informatik"]["n"] == 18 and len(words["Informatik"]["pages"]) == 6
    assert words["22/09/2026"]["num"]
    head = _text(hhn, 0, "Informatik 1")
    after = {w["w"]: w["n"] for w in hhn.word_counts(Settings(), Overrides(signatures={head["sig"]: "remove"}))}
    assert after["Informatik"] == 12  # the 6 in the top left are not counted


# ----------------------------------------------------------------------------- images with text and cropping
@pytest.fixture(scope="module")
def mixed():
    d = DistillDocument(_bytes(make_samples.mixed_deck(4)))
    d.analyze()
    return d


def _image(d, page, min_area=0.2):
    return next(e for e in d.pages[page].elements if e.kind == "image" and e.area > min_area)


def _px(img, x0, y0, x1, y1):  # PDF coordinates (bottom-left) -> 720x405 render region
    return img[405 - y1:405 - y0, x0:x1]


def test_image_content_analysis(mixed):
    shot, table = _image(mixed, 0), _image(mixed, 1)
    fs, ft = mixed.features(shot), mixed.features(table)
    assert ft["text"] > 0.9 and not ft["photos"]
    assert fs["text"] > 0.6 and len(fs["photos"]) >= 2
    assert any(b[0] > 0.6 for b in fs["photos"])  # photos on the right were found


def test_text_images_kept_in_tier3(mixed):
    table = _image(mixed, 1)
    photo = next(e for e in mixed.pages[1].elements if e.kind == "image" and e is not table)
    drops, labels = mixed.decide(tier_settings(3), Overrides())
    assert labels[table.id] == "text_image" and table.id not in drops[1]
    assert photo.id in drops[1]
    s = Settings.from_dict({**tier_settings(3).to_dict(), "keep_text_images": False})
    assert table.id in mixed.decide(s, Overrides())[0][1]


def test_auto_crop_removes_photos_keeps_text(mixed):
    s = Settings(auto_crop_photos=True)
    img = render(mixed.processed_page_pdf(0, s, Overrides()), 0)
    ref = render(mixed.processed_page_pdf(0, Settings(), Overrides()), 0)
    right_photo = _px(img, 450, 260, 610, 380)        # top-right corner of the image (photo)
    assert _px(ref, 450, 260, 610, 380).mean() < 200   # dark/coloured in the original
    assert right_photo.mean() > 250                    # white once cropped
    left_text = _px(img, 30, 250, 300, 380)
    assert (left_text.sum(axis=2) < 300).sum() > 200   # text on the left is still there


def test_rect_keep_crop_and_all_pages(mixed):
    shot = _image(mixed, 0)
    x0, y0, x1, y1 = shot.view
    keep_left = [[x0, y0], [x0 + (x1 - x0) * 0.5, y0], [x0 + (x1 - x0) * 0.5, y1], [x0, y1]]
    ov = Overrides(crops=[{"id": shot.id, "all": True, "mode": "keep", "points": keep_left}])
    for page in (0, 2):
        img = render(mixed.processed_page_pdf(page, Settings(), ov), 0)
        assert _px(img, 330, 20, 610, 385).mean() > 252, "right half should not be printed"
        assert (_px(img, 30, 250, 300, 380).sum(axis=2) < 300).sum() > 200, "left half should stay"


def test_freehand_erase_crop(mixed):
    table = _image(mixed, 1)
    x0, y0, x1, y1 = table.view
    tri = [[x0, y0], [x1, y0], [x0, y1]]  # top-left triangle is erased
    ov = Overrides(crops=[{"id": table.id, "all": False, "mode": "erase", "points": tri}])
    img = render(mixed.processed_page_pdf(1, Settings(), ov), 0)
    ref = render(mixed.processed_page_pdf(1, Settings(), Overrides()), 0)
    tl = _px(img, 40, 280, 140, 330)       # top left: erased
    assert _px(ref, 40, 280, 140, 330).min() < 100 and tl.min() > 240
    br = _px(img, 173, 131, 253, 160)      # below the diagonal ("Beispiele" digits): still there
    assert br.min() < 100


def test_crop_forces_keep(mixed):
    photo = next(e for e in mixed.pages[1].elements if e.kind == "image" and e.area < 0.1)
    x0, y0, x1, y1 = photo.view
    ov = Overrides(crops=[{"id": photo.id, "all": False, "mode": "keep", "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}])
    drops, _ = mixed.decide(tier_settings(3), ov)
    assert photo.id not in drops.get(1, set())
    els = {e["id"]: e for e in mixed.page_elements(1, tier_settings(3), ov)}
    assert els[photo.id]["clips"]["keep"]


# ----------------------------------------------------------------------------- ink warnings
def test_image_ink_measure():
    from PIL import Image

    from distill_core.imgfeat import analyze_image
    assert analyze_image(Image.new("RGB", (200, 200), "white"))["ink"] < 0.01
    assert analyze_image(Image.new("RGB", (200, 200), (40, 40, 40)))["ink"] > 0.8


def test_dark_photo_is_not_protected_as_text_image(mixed):
    table = _image(mixed, 1)
    real = dict(mixed.img_feats[table.sig])
    try:
        # a dark photo that the tile test mistakes for text (cars, machines on lecture title slides)
        mixed.img_feats[table.sig] = {**real, "text": 0.9, "ink": 0.55}
        mixed._decisions.clear()
        drops, labels = mixed.decide(tier_settings(3), Overrides())
        assert labels[table.id] != "text_image" and table.id in drops[1]
    finally:
        mixed.img_feats[table.sig] = real
        mixed._decisions.clear()


def test_ink_report_flags_heavy_pages_and_groups_hotspots(dark):
    r0 = dark.ink_report(Settings(), Overrides())
    assert len(r0["pages"]) == dark.n_pages
    assert r0["heavy"] == list(range(dark.n_pages))           # dark backgrounds on every page
    top = r0["hotspots"][0]
    assert top["pages"] == dark.n_pages and top["share"] > 0.5  # the shared background, grouped once
    assert r0["page_hot"][0]                                 # heavy pages name what to highlight
    r1 = dark.ink_report(tier_settings(1), Overrides())
    assert sum(r1["pages"]) < sum(r0["pages"]) / 2              # removing backgrounds saves most ink
    assert all(h["sig"] != top["sig"] for h in r1["hotspots"])
