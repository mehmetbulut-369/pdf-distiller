"""Writes docs/inside.{en,de,tr}.svg: the long README film, "what happens inside PDF Distiller".

    python docs/make_explainer.py

Seven chapters, 66 s, looping: offline and no AI model inside → read (pikepdf) → measure → decide →
rewrite → check (pypdfium2) → why, and what it is built with. Same one-line style as docs/story.*.svg.
Pure SVG + CSS so GitHub plays it from an <img>; with reduced motion the end card shows.
Every number on screen comes from the repo: 91 % is the Light saving on samples/dark_slides.pdf
(README results), 90 is the test count.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
T = 66.0
BG, INK, DARK, GREY, PANEL = "#0F2C4C", "#F5F7FA", "#1E2733", "#5C6B7E", "#0A2038"
MAGENTA, YELLOW, SKY, GREEN, BLUE = "#F0679E", "#F2C230", "#6BBEEC", "#4CC38A", "#6FA8E8"
MONO = 'ui-monospace, Menlo, Consolas, monospace'
CH = [0, 9, 18, 27, 36, 45, 54, 59.5]  # chapter starts; the last one runs to T

TEXT = {
    "en": {
        "cap": ["It runs on your computer. Nothing is uploaded, and there is no AI model inside.",
                "1 · Read: pikepdf opens the page's own drawing instructions, one by one.",
                "2 · Measure: size, darkness, and what repeats on every page.",
                "3 · Decide: the level sets the rules, and your click always wins.",
                "4 · Rewrite: the same instructions, minus what you removed. Text stays text.",
                "5 · Check: pypdfium2 draws every page before and after, and counts the ink.",
                "I built it for students like me: less ink to buy, fewer empty cartridges.",
                "Open source, readable rules, 90 tests. Built with an AI assistant, no AI inside."],
        "upload": "no upload", "ai": "no AI model", "mit": "MIT licence · source on GitHub",
        "stream": "content stream · page 1",
        "m_logo": "Logo: same image, same place on 6 of 6 pages → repeated",
        "m_bg": "Background: fills the whole page, dark → background",
        "m_photo": "Photo: big, no text inside → large image",
        "m_text": "Text: always kept, turned black when its background goes",
        "kept": "kept by you", "black": "text colour → black",
        "lens": ["Text stays text:", "sharp at any zoom,", "still searchable."],
        "before": "before", "after": "after", "less": "91 % less ink on the dark sample deck",
        "without": "without", "with": "with PDF Distiller",
    },
    "de": {
        "cap": ["Läuft auf Ihrem Rechner. Nichts wird hochgeladen, und es steckt kein KI-Modell darin.",
                "1 · Lesen: pikepdf öffnet die Zeichenbefehle der Seite, einen nach dem anderen.",
                "2 · Messen: Größe, Helligkeit und was sich auf jeder Seite wiederholt.",
                "3 · Entscheiden: Die Stufe setzt die Regeln, Ihr Klick hat immer Vorrang.",
                "4 · Neu schreiben: dieselben Befehle, ohne das Entfernte. Text bleibt Text.",
                "5 · Prüfen: pypdfium2 zeichnet jede Seite vorher und nachher und zählt die Tinte.",
                "Gebaut für Studierende wie mich: weniger Tinte kaufen, weniger leere Patronen.",
                "Open Source, lesbare Regeln, 90 Tests. Mit KI-Assistenz gebaut, ohne KI darin."],
        "upload": "kein Upload", "ai": "kein KI-Modell", "mit": "MIT-Lizenz · Quellcode auf GitHub",
        "stream": "Content-Stream · Seite 1",
        "m_logo": "Logo: gleiches Bild, gleiche Stelle auf 6 von 6 Seiten → wiederholt",
        "m_bg": "Hintergrund: füllt die ganze Seite, dunkel → Hintergrund",
        "m_photo": "Foto: groß, ohne Text → großes Bild",
        "m_text": "Text: bleibt immer, wird schwarz, wenn sein Hintergrund wegfällt",
        "kept": "von Ihnen behalten", "black": "Textfarbe → schwarz",
        "lens": ["Text bleibt Text:", "scharf bei jedem Zoom,", "weiter durchsuchbar."],
        "before": "vorher", "after": "nachher", "less": "91 % weniger Tinte beim dunklen Beispielsatz",
        "without": "ohne", "with": "mit PDF Distiller",
    },
    "tr": {
        "cap": ["Kendi bilgisayarınızda çalışır. Hiçbir şey yüklenmez, içinde yapay zekâ modeli yok.",
                "1 · Oku: pikepdf sayfanın kendi çizim komutlarını tek tek açar.",
                "2 · Ölç: boyut, koyuluk ve her sayfada tekrar eden ne varsa.",
                "3 · Karar ver: kademe kuralları koyar, son söz her zaman sizin tıklamanızın.",
                "4 · Yeniden yaz: aynı komutlar, çıkardıklarınız hariç. Metin metin olarak kalır.",
                "5 · Kontrol et: pypdfium2 her sayfayı önce ve sonra çizer, mürekkebi sayar.",
                "Benim gibi öğrenciler için yaptım: daha az mürekkep, daha az boş kartuş.",
                "Açık kaynak, okunabilir kurallar, 90 test. Yapay zekâ yardımıyla yazıldı, içinde yok."],
        "upload": "yükleme yok", "ai": "yapay zekâ modeli yok", "mit": "MIT lisansı · kaynak kodu GitHub'da",
        "stream": "içerik akışı · sayfa 1",
        "m_logo": "Logo: aynı görsel, aynı yer, 6 sayfanın 6'sında → tekrar eden",
        "m_bg": "Arka plan: bütün sayfayı kaplıyor, koyu → arka plan",
        "m_photo": "Fotoğraf: büyük, içinde yazı yok → büyük görsel",
        "m_text": "Metin: hep kalır, arka planı kalkınca siyaha döner",
        "kept": "sizin seçiminiz", "black": "metin rengi → siyah",
        "lens": ["Metin metin kalır:", "her yakınlaştırmada keskin,", "aranabilir."],
        "before": "önce", "after": "sonra", "less": "Koyu örnek sette %91 daha az mürekkep",
        "without": "olmadan", "with": "PDF Distiller ile",
    },
}


def i18n(lang: str) -> dict:
    return json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text("utf-8"))


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------- timing helpers (seconds → % of the loop)
CSS: list[str] = []


def pct(t: float) -> str:
    return f"{max(0.0, min(100.0, t / T * 100)):.3f}%"


def anim(name: str, stops: list[tuple[float, str]], base: str = "") -> str:
    """A class whose keyframes are given in seconds; the first and last stop are held to the loop ends."""
    stops = [(0.0, stops[0][1])] + stops + [(T, stops[-1][1])]
    body = " ".join(f"{pct(t)} {{ {css} }}" for t, css in stops)
    CSS.append(f"@keyframes {name} {{ {body} }}\n.{name} {{ animation-name: {name}; {base} }}\n")
    return name


def show(name: str, t0: float, t1: float, d: float = 0.4) -> str:
    return anim(name, [(t0, "opacity: 0"), (t0 + d, "opacity: 1"), (t1 - d, "opacity: 1"), (t1, "opacity: 0")], "opacity: 0;")


def gone(name: str, t: float, back: float | None = None, d: float = 0.4) -> str:
    """Visible, fades out at t (and back in at `back`)."""
    st = [(t, "opacity: 1"), (t + d, "opacity: 0")]
    if back is not None:
        st += [(back, "opacity: 0"), (back + d, "opacity: 1")]
    return anim(name, st)


# ---------------------------------------------------------------- drawing helpers
def slide(x: float, y: float, w: float, h: float, cls: dict[str, str] | None = None, logo_only=False) -> str:
    """A dark lecture slide: white paper, dark background, logo, photo, title and bullets."""
    c = cls or {}
    sx, sy = w / 360, h / 203
    def r(px, py, pw, ph, **kw):
        attrs = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items())
        return f'<rect x="{x + px * sx:.1f}" y="{y + py * sy:.1f}" width="{pw * sx:.1f}" height="{ph * sy:.1f}" {attrs}/>'
    words = "".join(r(24, yy, ww, 11, rx=5) for yy, ww in ((26, 170), (70, 150), (98, 130), (126, 140)))
    mountain = (f'<path d="M{x + 206 * sx:.1f},{y + 146 * sy:.1f} l{30 * sx:.1f},{-40 * sy:.1f} l{22 * sx:.1f},{24 * sy:.1f}'
                f' l{18 * sx:.1f},{-16 * sy:.1f} l{40 * sx:.1f},{32 * sy:.1f} z" fill="{DARK}"/>')
    return (f'<g>{r(0, 0, 360, 203, fill=INK, rx=4)}'
            f'<g class="a {c.get("bg", "")}">{r(0, 0, 360, 203, fill=DARK, rx=4)}</g>'
            f'<g class="a {c.get("photo", "")}">{r(200, 60, 136, 92, fill=GREY, rx=3)}{mountain}</g>'
            f'<g class="a {c.get("logo", "")}">{r(300, 170, 48, 22, fill=GREY, rx=4)}</g>'
            f'<g class="a {c.get("words", "")}" fill="{INK}">{words}</g></g>')


def dashed(x, y, w, h, colour, cls) -> str:
    return (f'<rect class="a {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="none" stroke="{colour}"'
            f' stroke-width="3" stroke-dasharray="7 6"/>')


def label(x, y, text, size=16, fill=INK, cls="", anchor="start", weight=400, family=None) -> str:
    fam = f' font-family="{family}"' if family else ""
    return (f'<text class="a {cls}" x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}"'
            f' text-anchor="{anchor}"{fam}>{esc(text)}</text>')


def cursor(cls) -> str:
    return (f'<path class="a {cls}" d="M0,0 l0,24 l6,-6 l5,10 l4,-2 l-5,-10 l9,0 z" fill="{INK}" stroke="{BG}"'
            f' stroke-width="1.5"/>')


# ---------------------------------------------------------------- chapters
def ch0(L) -> str:  # offline, no AI, open source
    s, e = CH[0], CH[1]
    show("k0", s, e)
    anim("k0file", [(s + 0.8, "transform: translate(0, -120px); opacity: 0"), (s + 1.1, "opacity: 1"),
                    (s + 2.2, "transform: translate(0, 0); opacity: 1")], "transform: translate(0, -120px);")
    show("k0cloud", s + 3, e)
    show("k0ai", s + 4.5, e)
    show("k0mit", s + 6, e)
    def cross(cx, cy):
        return f'<path d="M{cx - 44},{cy + 32} L{cx + 44},{cy - 32}" stroke="{MAGENTA}" stroke-width="5" stroke-linecap="round"/>'
    return f"""<g class="a k0">
  <g fill="none" stroke="{INK}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round">
    <path d="M370,280 V150 Q370,140 380,140 H580 Q590,140 590,150 V280 M340,280 H620 L600,300 H360 Z"/>
  </g>
  <g transform="translate(456,170)"><g class="a k0file">
    <path d="M0,0 H34 L48,14 V70 H0 Z" fill="{INK}"/><path d="M34,0 V14 H48" fill="none" stroke="{GREY}" stroke-width="2"/>
    <text x="24" y="52" font-size="13" font-weight="700" fill="{MAGENTA}" text-anchor="middle">PDF</text></g></g>
  <g class="a k0cloud" transform="translate(760,210)">
    <path d="M-50,22 a24,24 0 0 1 6,-46 a34,34 0 0 1 64,-6 a26,26 0 0 1 32,52 Z" fill="none" stroke="{INK}" stroke-width="4"/>
    {cross(0, 0)}{label(0, 70, L["upload"], 17, anchor="middle")}</g>
  <g class="a k0ai" transform="translate(200,210)">
    <rect x="-36" y="-36" width="72" height="72" rx="10" fill="none" stroke="{INK}" stroke-width="4"/>
    <path d="M-20,-36 v-12 M0,-36 v-12 M20,-36 v-12 M-20,36 v12 M0,36 v12 M20,36 v12 M-36,-20 h-12 M-36,0 h-12 M-36,20 h-12 M36,-20 h12 M36,0 h12 M36,20 h12" stroke="{INK}" stroke-width="4" stroke-linecap="round"/>
    <text x="0" y="9" font-size="26" font-weight="700" fill="{INK}" text-anchor="middle">AI</text>
    {cross(0, 0)}{label(0, 84, L["ai"], 17, anchor="middle")}</g>
  <g class="a k0mit">{label(480, 350, L["mit"], 18, GREEN, anchor="middle", weight=600)}</g>
</g>"""


CODE = [  # (operator line, colour, what it draws) — real PDF operators of the kind the sample decks use
    ("0.12 0.15 0.20 rg 0 0 720 405 re f", MAGENTA),
    ("q 300 0 0 200 380 80 cm /Im1 Do Q", SKY),
    ("q 96 0 0 44 600 18 cm /Logo Do Q", YELLOW),
    ("BT /F1 22 Tf 1 1 1 rg (Kapitel 1) Tj ET", GREEN),
]


def code_panel(x, y, w, h, title, cls_prefix, lines_cls=None) -> str:
    rows = []
    for i, (code, colour) in enumerate(CODE):
        cl = (lines_cls or [""] * 4)[i]
        yy = y + 62 + i * 38
        rows.append(f'<g class="a {cl}"><rect x="{x + 14}" y="{yy - 17}" width="5" height="24" rx="2" fill="{colour}"/>'
                    f'{label(x + 30, yy, code, 14.5, INK, family=MONO)}</g>')
    return (f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" stroke="{INK}" stroke-opacity=".35" stroke-width="2"/>'
            f'{label(x + 16, y + 26, title, 13, BLUE, family=MONO)}{"".join(rows)}</g>')


def ch1(L) -> str:  # read
    s, e = CH[1], CH[2]
    show("k1", s, e)
    for i in range(4):
        show(f"k1l{i}", s + 1.2 + i * 1.6, e)
    boxes = [dashed(76, 106, 368, 211, MAGENTA, "k1l0"), dashed(278, 167, 146, 102, SKY, "k1l1"),
             dashed(376, 278, 60, 32, YELLOW, "k1l2"), dashed(98, 128, 186, 28, GREEN, "k1l3")]
    return f"""<g class="a k1">
  {slide(80, 110, 360, 203)}
  {"".join(boxes)}
  {code_panel(470, 110, 450, 203, L["stream"], "k1", [f"k1l{i}" for i in range(4)])}
</g>"""


def ch2(L) -> str:  # measure
    s, e = CH[2], CH[3]
    show("k2", s, e)
    thumbs = []
    for i in range(6):
        x = 60 + i * 142
        thumbs.append(slide(x, 104, 120, 68))
        thumbs.append(dashed(x + 96, 158, 22, 13, YELLOW, show(f"k2t{i}", s + 0.8 + i * 0.4, e)))
    lines = []
    for i, (key, colour) in enumerate((("m_logo", YELLOW), ("m_bg", MAGENTA), ("m_photo", SKY), ("m_text", GREEN))):
        show(f"k2m{i}", s + 3.6 + i * 1.1, e)
        y = 222 + i * 38
        lines.append(f'<g class="a k2m{i}"><circle cx="78" cy="{y - 6}" r="7" fill="{colour}"/>{label(96, y, L[key], 18)}</g>')
    return f'<g class="a k2">{"".join(thumbs)}{"".join(lines)}</g>'


def ch3(L, lang) -> str:  # decide
    s, e = CH[3], CH[4]
    show("k3", s, e)
    names = [i18n(lang)[f"tier.{k}.name"] for k in range(4)]
    t_light, t_medium, t_click = s + 2.4, s + 4.6, s + 6.8
    gone("k3bg", t_light)
    gone("k3logo", t_light)
    gone("k3photo", t_medium, back=t_click + 0.2)
    anim("k3words", [(t_light, f"fill: {INK}"), (t_light + 0.4, f"fill: {DARK}")], f"fill: {INK};")
    anim("k3pill", [(s + 0.6, "transform: translateY(0)"), (t_light - 0.3, "transform: translateY(0)"),
                    (t_light, "transform: translateY(52px)"), (t_medium - 0.3, "transform: translateY(52px)"),
                    (t_medium, "transform: translateY(104px)")])
    anim("k3cur", [(t_medium + 0.4, "transform: translate(560px, 330px); opacity: 0"), (t_medium + 0.7, "opacity: 1"),
                   (t_click - 0.2, "transform: translate(320px, 200px); opacity: 1"), (t_click, "transform: translate(318px, 203px); opacity: 1"),
                   (t_click + 0.3, "transform: translate(320px, 200px); opacity: 1"), (e - 0.5, "opacity: 1"), (e, "opacity: 0")],
         "opacity: 0;")
    show("k3kept", t_click + 0.4, e)
    pills = "".join(f'<rect x="600" y="{124 + i * 52}" width="230" height="40" rx="20" fill="none" stroke="{INK}" stroke-opacity=".4" stroke-width="2"/>'
                    f'{label(715, 150 + i * 52, n, 17, anchor="middle")}' for i, n in enumerate(names))
    return f"""<g class="a k3">
  {slide(80, 114, 400, 225, {"bg": "k3bg", "logo": "k3logo", "photo": "k3photo", "words": "k3words"})}
  <rect class="a k3pill" x="600" y="124" width="230" height="40" rx="20" fill="{BLUE}" fill-opacity=".35"/>
  {pills}
  <g class="a k3kept">{dashed(298, 178, 156, 108, GREEN, "")}{label(376, 304, L["kept"], 15, GREEN, anchor="middle", weight=600)}</g>
  {cursor("k3cur")}
</g>"""


def ch4(L) -> str:  # rewrite
    s, e = CH[4], CH[5]
    show("k4", s, e)
    t_strike = s + 1.5
    strikes = []
    for i in (0, 2):  # the background and logo instructions go
        anim(f"k4s{i}", [(t_strike, "stroke-dashoffset: 1"), (t_strike + 0.8, "stroke-dashoffset: 0")], "stroke-dashoffset: 1;")
        gone(f"k4l{i}", t_strike + 2.2)
        y = 110 + 62 + i * 38 - 5
        strikes.append(f'<path class="a draw k4s{i} k4l{i}" pathLength="1" d="M90,{y} H{90 + len(CODE[i][0]) * 8.7:.0f}"'
                       f' stroke="{MAGENTA}" stroke-width="3"/>')
    show("k4black", s + 4.2, e)
    show("k4lens", s + 5.4, e)
    lens = L["lens"]
    return f"""<g class="a k4">
  {code_panel(60, 110, 450, 203, L["stream"], "k4", ["k4l0", "", "k4l2", ""])}
  {"".join(strikes)}
  <g class="a k4black"><path d="M180,298 V318" stroke="{GREEN}" stroke-width="2"/><rect x="132" y="322" width="96" height="26" rx="6" fill="{GREEN}" fill-opacity=".25" stroke="{GREEN}"/>
    {label(180, 340, "0 0 0 rg", 14, INK, anchor="middle", family=MONO)}{label(240, 340, L["black"], 15, GREEN, weight=600)}</g>
  <g class="a k4lens">
    <circle cx="700" cy="200" r="92" fill="{INK}"/><circle cx="700" cy="200" r="92" fill="none" stroke="{INK}" stroke-width="6"/>
    <path d="M766,266 L820,320" stroke="{INK}" stroke-width="14" stroke-linecap="round"/>
    <text x="700" y="236" font-size="104" font-weight="700" fill="{DARK}" text-anchor="middle" font-family="Georgia, serif">Ag</text>
    {label(700, 330, lens[0], 16, anchor="middle", weight=600)}{label(700, 352, lens[1], 15, anchor="middle")}{label(700, 372, lens[2], 15, anchor="middle")}
  </g>
</g>"""


def ch5(L, lang) -> str:  # check: render, ink gauge, export
    s, e = CH[5], CH[6]
    show("k5", s, e)
    anim("k5bo", [(s + 1.2, "transform: scaleY(0)"), (s + 2.4, "transform: scaleY(1)")], "transform: scaleY(0); transform-origin: bottom;")
    anim("k5ba", [(s + 2.4, "transform: scaleY(0)"), (s + 3.4, "transform: scaleY(1)")], "transform: scaleY(0); transform-origin: bottom;")
    show("k5less", s + 3.8, e)
    anim("k5btn", [(s + 6.0, "fill-opacity: 1"), (s + 6.2, "fill-opacity: .6"), (s + 6.5, "fill-opacity: 1")], "fill-opacity: 1;")
    anim("k5cur", [(s + 4.6, "transform: translate(860px, 380px); opacity: 0"), (s + 4.9, "opacity: 1"),
                   (s + 5.9, "transform: translate(800px, 318px); opacity: 1"), (s + 6.1, "transform: translate(798px, 321px); opacity: 1"),
                   (s + 6.4, "transform: translate(800px, 318px); opacity: 1"), (e - 0.4, "opacity: 1"), (e, "opacity: 0")], "opacity: 0;")
    clean = {"bg": "k5x", "logo": "k5x", "photo": "k5x", "words": "k5w"}
    CSS.append(f".k5x {{ opacity: 0; }} .k5w {{ fill: {DARK}; }}\n")
    export = i18n(lang)["export"]
    return f"""<g class="a k5">
  <rect x="50" y="96" width="860" height="276" rx="12" fill="{PANEL}" stroke="{INK}" stroke-opacity=".35" stroke-width="2"/>
  {label(80, 128, "PDF Distiller", 16, weight=700)}
  <rect class="a k5btn" x="706" y="108" width="186" height="34" rx="8" fill="{SKY}"/>{label(799, 130, export, 14, BG, anchor="middle", weight=700)}
  {slide(80, 160, 280, 158)}{label(220, 342, L["before"], 15, anchor="middle")}
  {slide(386, 160, 280, 158, clean)}{label(526, 342, L["after"], 15, anchor="middle")}
  <rect x="712" y="178" width="58" height="140" fill="none" stroke="{INK}" stroke-opacity=".3"/>
  <rect x="800" y="178" width="58" height="140" fill="none" stroke="{INK}" stroke-opacity=".3"/>
  <rect class="a k5bo" x="712" y="{318 - 105}" width="58" height="105" fill="{MAGENTA}"/>
  <rect class="a k5ba" x="800" y="{318 - 10}" width="58" height="10" fill="{GREEN}"/>
  {label(741, 342, L["before"], 14, anchor="middle")}{label(829, 342, L["after"], 14, anchor="middle")}
  <g class="a k5less">{label(480, 364, L["less"], 15, GREEN, anchor="middle", weight=600)}</g>
  {cursor("k5cur")}
</g>"""


def ch6(L) -> str:  # why: two cartridges
    s, e = CH[6], CH[7]
    show("k6", s, e)
    anim("k6a", [(s + 0.8, "transform: scaleY(1)"), (s + 4.2, "transform: scaleY(0.05)")], "transform-origin: bottom;")
    anim("k6b", [(s + 0.8, "transform: scaleY(1)"), (s + 4.2, "transform: scaleY(0.91)")], "transform-origin: bottom;")
    def cart(x, cls, txt):
        return (f'<g transform="translate({x},140)"><rect width="110" height="170" rx="14" fill="none" stroke="{INK}" stroke-width="5"/>'
                f'<rect class="a {cls}" x="14" y="14" width="82" height="142" rx="6" fill="{MAGENTA}"/>'
                f'{label(55, 205, txt, 17, anchor="middle", weight=600)}</g>')
    return f'<g class="a k6">{cart(290, "k6a", L["without"])}{cart(560, "k6b", L["with"])}</g>'


def ch7(L, lang) -> str:  # built with, end card
    s = CH[7]
    show("k7", s, T)
    chips = ["Python", "pikepdf · qpdf", "pypdfium2 · PDFium", "FastAPI", "pywebview", "plain JavaScript", "pytest · 90 tests"]
    out, x, row = [], 0, 0
    widths = [len(c) * 9.6 + 34 for c in chips]
    rows = [chips[:4], chips[4:]]
    for r_i, row in enumerate(rows):
        total = sum(len(c) * 9.6 + 34 for c in row) + 14 * (len(row) - 1)
        x = 480 - total / 2
        for c in row:
            i = chips.index(c)
            w = widths[i]
            show(f"k7c{i}", s + 0.3 + i * 0.35, T)
            out.append(f'<g class="a k7c{i}"><rect x="{x:.0f}" y="{112 + r_i * 52}" width="{w:.0f}" height="38" rx="19" fill="none" stroke="{BLUE}" stroke-width="2"/>'
                       f'{label(x + w / 2, 137 + r_i * 52, c, 17, anchor="middle", family=MONO)}</g>')
            x += w + 14
    anim("k7end", [(s + 3.2, "opacity: 0; transform: translateY(10px)"), (s + 3.8, "opacity: 1; transform: translateY(0)"),
                   (T - 0.4, "opacity: 1"), (T, "opacity: 0")], "opacity: 1;")
    logo = (ROOT / "app" / "static" / "logo.svg").read_text("utf-8")
    logo = re.sub(r"<\?xml[^>]*\?>\s*", "", logo)
    logo = re.sub(r"@media \(prefers-color-scheme: dark\) \{.*?\}\s*\}", "", logo, flags=re.S)
    logo = re.sub(r"<svg [^>]*>", '<svg x="292" y="232" width="84" height="84" viewBox="0 0 1024 1024">', logo, count=1)
    return f"""<g class="a k7">{"".join(out)}</g>
<g class="a k7end">{logo}{label(392, 278, "PDF Distiller", 36, weight=700)}{label(394, 306, i18n(lang)["start.title"], 18)}</g>"""


def svg(lang: str) -> str:
    CSS.clear()
    L = TEXT[lang]
    body = [ch0(L), ch1(L), ch2(L), ch3(L, lang), ch4(L), ch5(L, lang), ch6(L), ch7(L, lang)]
    caps = []
    for i, c in enumerate(L["cap"]):
        a, b = CH[i], (CH[i + 1] if i + 1 < len(CH) else T)
        anim(f"c{i}", [(a, "opacity: 0; transform: translateY(8px)"), (a + 0.5, "opacity: 1; transform: translateY(0)"),
                       (b - 0.4, "opacity: 1"), (b, "opacity: 0")], "opacity: 0;")
        caps.append(label(480, 52, c, 18, anchor="middle", weight=600, cls=f"c{i}"))
    progress = "".join(f'<rect x="{330 + i * 38}" y="380" width="30" height="4" rx="2" fill="{INK}" fill-opacity=".25"/>' for i in range(8))
    anim("prog", [(0, "transform: scaleX(0)"), (T, "transform: scaleX(1)")], "transform-origin: left;")
    head = f"""
svg {{ font-family: Inter, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
.a {{ animation-duration: {T:g}s; animation-iteration-count: infinite; animation-fill-mode: both;
      animation-timing-function: cubic-bezier(.45,0,.25,1); transform-box: fill-box; }}
.prog {{ animation-timing-function: linear; }}
.draw {{ stroke-dasharray: 1; }}
"""
    still = "@media (prefers-reduced-motion: reduce) { .a { animation: none; } .k7end { opacity: 1; } }\n"
    label_text = " ".join(L["cap"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 400" width="960" height="400" role="img" aria-label="{esc(label_text)}">
<style>{head}{"".join(CSS)}{still}</style>
<rect width="960" height="400" rx="16" fill="{BG}"/>
{"".join(body)}
{"".join(caps)}
{progress}<rect class="a prog" x="330" y="380" width="296" height="4" rx="2" fill="{INK}" fill-opacity=".7"/>
</svg>
"""


if __name__ == "__main__":
    for lang in TEXT:
        (HERE / f"inside.{lang}.svg").write_text(svg(lang), "utf-8")
    print("docs/inside.{en,de,tr}.svg written")
