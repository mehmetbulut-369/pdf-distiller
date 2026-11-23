"""Writes docs/inside.{en,de,tr}.svg: the long README film, "what happens inside PDF Distiller".

    python docs/make_explainer.py

Written for people with no technical background, without bending the facts: your file stays on your
computer; no AI, written rules instead; what each library does in plain words (pikepdf reads the PDF
like a recipe, our own analysis measures, pypdfium2 draws pages, FastAPI + pywebview make the window);
the user's choice beats the rules (shown slowly, with the app's own menu); no savings percentage, only
what depends on what; budget and nature at the end. Same one-line style as docs/story.*.svg.
Pure SVG + CSS so GitHub plays it from an <img>; with reduced motion the end card shows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
T = 90.0
BG, INK, DARK, GREY, PANEL = "#0F2C4C", "#F5F7FA", "#1E2733", "#5C6B7E", "#0A2038"
MAGENTA, YELLOW, SKY, GREEN, BLUE, LEAF = "#F0679E", "#F2C230", "#6BBEEC", "#4CC38A", "#6FA8E8", "#7DB33A"
MONO = "ui-monospace, Menlo, Consolas, monospace"
CH = [0, 9, 18, 28, 37, 48, 57, 66, 74, 84]  # chapter starts; the last one (end card) runs to T

TEXT = {
    "en": {
        "cap": [(0, 9, "Your file never leaves your computer. Everything happens right here."),
                (9, 18, "There is no AI inside. The app follows clear rules, the same way every time."),
                (18, 28, "pikepdf reads your PDF like a recipe: a list of drawing steps."),
                (28, 37, "Our own analysis checks every step: how big, how dark, and does it repeat?"),
                (37, 42, "Some things look like decoration but matter to you, like this chart."),
                (42, 48, "Click it and choose to keep it. Your choice always beats the rules."),
                (48, 57, "pikepdf writes the recipe again, without the steps you removed. Text stays text."),
                (57, 66, "pypdfium2, the PDF engine inside Google Chrome, draws each page to measure the ink."),
                (66, 74, "The window is a small web page that runs only on your computer."),
                (74, 84, "Less ink, fewer cartridges, less raw material: good for your budget and for nature.")],
        "computer": "your computer", "stays": "stays here · processed here",
        "rules": [("fills the page and is dark", "background"), ("same picture, same place on many pages", "repeated"),
                  ("big picture with no text in it", "large image"), ("letters and words", "always kept")],
        "steps": ["Paint the whole page dark", "Place the photo", "Place the logo, bottom right", "Write the title in white"],
        "pikepdf": "pikepdf opens, reads and rewrites PDF files",
        "analysis": "our analysis (Python, NumPy, Pillow): size, brightness, repeats",
        "measure": ["the logo: same place on 6 of 6 pages → repeated", "the background: covers the whole page, dark",
                    "the photo: big, no text inside", "the text: always kept"],
        "removed": "will be removed",
        "black": "white text turns black, so it shows on paper",
        "lens": ["Text stays text:", "sharp at any zoom,", "still searchable."],
        "before": "before", "after": "after", "note": "Dark slides save the most; plain slides save less.",
        "pdfium": "pypdfium2 draws the page as a small picture",
        "fastapi": "FastAPI: a tiny server that lives only inside the app",
        "webview": "pywebview: shows it as a normal app window",
        "money": "less money spent on ink", "cart": "fewer empty cartridges", "nature": "less raw material, less waste",
    },
    "de": {
        "cap": [(0, 9, "Ihre Datei verlässt nie Ihren Rechner. Alles passiert genau hier."),
                (9, 18, "Hier steckt keine KI drin. Die App folgt klaren Regeln, jedes Mal gleich."),
                (18, 28, "pikepdf liest Ihr PDF wie ein Rezept: eine Liste von Zeichenschritten."),
                (28, 37, "Unsere eigene Analyse prüft jeden Schritt: wie groß, wie dunkel, wiederholt er sich?"),
                (37, 42, "Manches sieht nach Dekoration aus, ist Ihnen aber wichtig, wie dieses Diagramm."),
                (42, 48, "Anklicken und Behalten wählen. Ihre Wahl schlägt immer die Regeln."),
                (48, 57, "pikepdf schreibt das Rezept neu, ohne die entfernten Schritte. Text bleibt Text."),
                (57, 66, "pypdfium2, die PDF-Engine aus Google Chrome, zeichnet jede Seite und misst die Tinte."),
                (66, 74, "Das Fenster ist eine kleine Webseite, die nur auf Ihrem Rechner läuft."),
                (74, 84, "Weniger Tinte, weniger Patronen, weniger Rohstoffe: gut für Ihr Budget und die Natur.")],
        "computer": "Ihr Rechner", "stays": "bleibt hier · wird hier bearbeitet",
        "rules": [("füllt die Seite und ist dunkel", "Hintergrund"), ("gleiches Bild, gleiche Stelle auf vielen Seiten", "wiederholt"),
                  ("großes Bild ohne Text darin", "großes Bild"), ("Buchstaben und Wörter", "bleiben immer")],
        "steps": ["Ganze Seite dunkel füllen", "Foto platzieren", "Logo unten rechts platzieren", "Titel in Weiß schreiben"],
        "pikepdf": "pikepdf öffnet, liest und schreibt PDF-Dateien",
        "analysis": "unsere Analyse (Python, NumPy, Pillow): Größe, Helligkeit, Wiederholung",
        "measure": ["das Logo: gleiche Stelle auf 6 von 6 Seiten → wiederholt", "der Hintergrund: bedeckt die ganze Seite, dunkel",
                    "das Foto: groß, ohne Text darin", "der Text: bleibt immer"],
        "removed": "wird entfernt",
        "black": "weiße Schrift wird schwarz, damit sie auf Papier sichtbar ist",
        "lens": ["Text bleibt Text:", "scharf bei jedem Zoom,", "weiter durchsuchbar."],
        "before": "vorher", "after": "nachher", "note": "Dunkle Folien sparen am meisten, schlichte Folien weniger.",
        "pdfium": "pypdfium2 zeichnet die Seite als kleines Bild",
        "fastapi": "FastAPI: ein winziger Server, der nur in der App lebt",
        "webview": "pywebview: zeigt alles als normales App-Fenster",
        "money": "weniger Geld für Tinte", "cart": "weniger leere Patronen", "nature": "weniger Rohstoffe, weniger Abfall",
    },
    "tr": {
        "cap": [(0, 9, "Dosyanız bilgisayarınızdan hiç çıkmaz. Her şey burada, bilgisayarınızda olur."),
                (9, 18, "İçinde yapay zekâ yok. Uygulama açık kurallara uyar, her seferinde aynı şekilde."),
                (18, 28, "pikepdf PDF'inizi bir yemek tarifi gibi okur: adım adım çizim talimatları."),
                (28, 37, "Kendi analizimiz her adımı inceler: ne kadar büyük, ne kadar koyu, tekrar ediyor mu?"),
                (37, 42, "Bazı şeyler süs gibi görünür ama sizin için önemlidir, bu grafik gibi."),
                (42, 48, "Üzerine tıklayıp korumayı seçin. Sizin seçiminiz her zaman kuraldan önce gelir."),
                (48, 57, "pikepdf tarifi yeniden yazar, çıkardığınız adımlar olmadan. Metin metin kalır."),
                (57, 66, "pypdfium2, Google Chrome'daki PDF motoru, her sayfayı çizip mürekkebi ölçer."),
                (66, 74, "Pencere, yalnız bilgisayarınızda çalışan küçük bir web sayfasıdır."),
                (74, 84, "Daha az mürekkep, daha az kartuş, daha az ham madde: bütçenize de doğaya da iyi.")],
        "computer": "bilgisayarınız", "stays": "burada kalır · burada işlenir",
        "rules": [("sayfayı kaplıyor ve koyu", "arka plan"), ("aynı görsel, birçok sayfada aynı yerde", "tekrar eden"),
                  ("içinde yazı olmayan büyük görsel", "büyük görsel"), ("harfler ve kelimeler", "hep kalır")],
        "steps": ["Bütün sayfayı koyuya boya", "Fotoğrafı yerleştir", "Logoyu sağ alta koy", "Başlığı beyazla yaz"],
        "pikepdf": "pikepdf PDF dosyalarını açar, okur, yeniden yazar",
        "analysis": "kendi analizimiz (Python, NumPy, Pillow): boyut, parlaklık, tekrar",
        "measure": ["logo: 6 sayfanın 6'sında aynı yerde → tekrar eden", "arka plan: bütün sayfayı kaplıyor, koyu",
                    "fotoğraf: büyük, içinde yazı yok", "metin: hep kalır"],
        "removed": "kaldırılacak",
        "black": "beyaz yazı siyaha döner, kâğıtta görünsün diye",
        "lens": ["Metin metin kalır:", "her yakınlaştırmada keskin,", "aranabilir."],
        "before": "önce", "after": "sonra", "note": "Koyu slaytlar en çok, sade slaytlar daha az tasarruf eder.",
        "pdfium": "pypdfium2 sayfayı küçük bir resim olarak çizer",
        "fastapi": "FastAPI: yalnız uygulamanın içinde yaşayan minik bir sunucu",
        "webview": "pywebview: hepsini normal bir uygulama penceresi gibi gösterir",
        "money": "mürekkebe daha az para", "cart": "daha az boş kartuş", "nature": "daha az ham madde, daha az atık",
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


def gone(name: str, t: float, d: float = 0.5) -> str:
    return anim(name, [(t, "opacity: 1"), (t + d, "opacity: 0")])


# ---------------------------------------------------------------- drawing helpers
def label(x, y, text, size=16, fill=INK, cls="", anchor="start", weight=400, family=None) -> str:
    fam = f' font-family="{family}"' if family else ""
    return (f'<text class="a {cls}" x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}"'
            f' text-anchor="{anchor}"{fam}>{esc(text)}</text>')


def chip(x, y, text, colour=BLUE, cls="", size=15) -> str:
    """A rounded tag that names a component and says what it does; x is its centre."""
    w = len(text) * size * 0.56 + 28
    return (f'<g class="a {cls}"><rect x="{x - w / 2:.0f}" y="{y}" width="{w:.0f}" height="32" rx="16" fill="{PANEL}"'
            f' stroke="{colour}" stroke-width="2"/>{label(x, y + 21, text, size, anchor="middle")}</g>')


def dashed(x, y, w, h, colour, cls="", width=3) -> str:
    return (f'<rect class="a {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="none" stroke="{colour}"'
            f' stroke-width="{width}" stroke-dasharray="7 6"/>')


def cursor(cls) -> str:
    return (f'<path class="a {cls}" d="M0,0 l0,24 l6,-6 l5,10 l4,-2 l-5,-10 l9,0 z" fill="{INK}" stroke="{BG}"'
            f' stroke-width="1.5"/>')


def slide(x, y, w, h, c: dict[str, str] | None = None, chart=False) -> str:
    """A dark lecture slide on white paper: background, photo (or a bar chart), logo, title and lines."""
    c = c or {}
    sx, sy = w / 360, h / 203

    def r(px, py, pw, ph, **kw):
        attrs = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items())
        return f'<rect x="{x + px * sx:.1f}" y="{y + py * sy:.1f}" width="{pw * sx:.1f}" height="{ph * sy:.1f}" {attrs}/>'

    words = "".join(r(24, yy, ww, 11, rx=5) for yy, ww in ((26, 170), (70, 150), (98, 130), (126, 140)))
    if chart:  # bars and an axis: drawn shapes, which "large shapes" would remove
        pic = (r(206, 150, 130, 3, fill=INK) + r(206, 60, 3, 93, fill=INK) +
               "".join(r(220 + i * 28, 150 - hgt, 18, hgt, fill=col) for i, (hgt, col) in enumerate(
                   ((40, SKY), (70, YELLOW), (55, GREEN), (85, MAGENTA)))))
    else:
        pic = (r(200, 60, 136, 92, fill=GREY, rx=3) +
               f'<path d="M{x + 206 * sx:.1f},{y + 146 * sy:.1f} l{30 * sx:.1f},{-40 * sy:.1f} l{22 * sx:.1f},{24 * sy:.1f}'
               f' l{18 * sx:.1f},{-16 * sy:.1f} l{40 * sx:.1f},{32 * sy:.1f} z" fill="{DARK}"/>')
    return (f'<g>{r(0, 0, 360, 203, fill=INK, rx=4)}'
            f'<g class="a {c.get("bg", "")}">{r(0, 0, 360, 203, fill=DARK, rx=4)}</g>'
            f'<g class="a {c.get("photo", "")}">{pic}</g>'
            f'<g class="a {c.get("logo", "")}">{r(300, 170, 48, 22, fill=GREY, rx=4)}</g>'
            f'<g class="a {c.get("words", "")}" fill="{c.get("wordfill", INK)}">{words}</g></g>')


def laptop(x, y, w, h) -> str:
    return (f'<path d="M{x},{y + h} V{y + 10} Q{x},{y} {x + 10},{y} H{x + w - 10} Q{x + w},{y} {x + w},{y + 10} V{y + h}'
            f' M{x - 30},{y + h} H{x + w + 30} L{x + w + 10},{y + h + 20} H{x - 10} Z" fill="none" stroke="{INK}"'
            f' stroke-width="4" stroke-linejoin="round"/>')


# ---------------------------------------------------------------- chapters
def ch0(L) -> str:  # the file stays on your computer
    s, e = CH[0], CH[1]
    show("k0", s, e)
    anim("k0file", [(s + 0.8, "transform: translate(0, -120px); opacity: 0"), (s + 1.1, "opacity: 1"),
                    (s + 2.2, "transform: translate(0, 0); opacity: 1")], "transform: translate(0, -120px);")
    show("k0zone", s + 2.8, e)
    anim("k0try", [(s + 4.0, "stroke-dashoffset: 1"), (s + 5.6, "stroke-dashoffset: 0")], "stroke-dashoffset: 1;")
    show("k0stays", s + 5.8, e)
    return f"""<g class="a k0">
  {laptop(370, 140, 220, 140)}
  <g transform="translate(456,170)"><g class="a k0file">
    <path d="M0,0 H34 L48,14 V70 H0 Z" fill="{INK}"/><path d="M34,0 V14 H48" fill="none" stroke="{GREY}" stroke-width="2"/>
    <text x="24" y="52" font-size="13" font-weight="700" fill="{MAGENTA}" text-anchor="middle">PDF</text></g></g>
  <g class="a k0zone"><rect x="250" y="100" width="460" height="232" rx="40" fill="none" stroke="{GREEN}" stroke-width="3" stroke-dasharray="10 8"/>
    {label(480, 124, L["computer"], 16, GREEN, anchor="middle", weight=600)}</g>
  <path class="a k0try draw" pathLength="1" d="M520,200 C600,190 660,190 700,205 C716,212 716,226 700,232 C660,246 600,236 560,222"
        fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>
  <g class="a k0stays">{label(480, 360, L["stays"], 19, GREEN, anchor="middle", weight=600)}</g>
</g>"""


def ch1(L) -> str:  # no AI: written rules
    s, e = CH[1], CH[2]
    show("k1", s, e)
    rows = []
    arrow = 320 + max(len(c) for c, _ in L["rules"]) * 8.8 + 24  # German conditions run long
    for i, ((cond, result), colour) in enumerate(zip(L["rules"], (MAGENTA, YELLOW, SKY, GREEN), strict=True)):
        show(f"k1r{i}", s + 1.4 + i * 1.5, e)
        y = 140 + i * 52
        rows.append(f'<g class="a k1r{i}"><circle cx="300" cy="{y - 6}" r="8" fill="{colour}"/>'
                    f'{label(320, y, cond, 17)}{label(arrow, y, "→", 18, BLUE, anchor="middle")}'
                    f'{label(arrow + 22, y, result, 17, colour, weight=700)}</g>')
    return f"""<g class="a k1">
  <g transform="translate(150,206)">
    <rect x="-40" y="-40" width="80" height="80" rx="12" fill="none" stroke="{INK}" stroke-opacity=".5" stroke-width="4"/>
    <text x="0" y="10" font-size="28" font-weight="700" fill="{INK}" fill-opacity=".5" text-anchor="middle">AI</text>
    <path d="M-48,36 L48,-36" stroke="{MAGENTA}" stroke-width="5" stroke-linecap="round"/></g>
  <rect x="270" y="102" width="640" height="220" rx="12" fill="{PANEL}" stroke="{INK}" stroke-opacity=".3" stroke-width="2"/>
  {"".join(rows)}
</g>"""


CODE = ["0.12 0.15 0.20 rg 0 0 720 405 re f", "q 300 0 0 200 380 80 cm /Im1 Do Q",
        "q 96 0 0 44 600 18 cm /Logo Do Q", "BT /F1 22 Tf 1 1 1 rg (Kapitel 1) Tj ET"]
STEP_COLOURS = (MAGENTA, SKY, YELLOW, GREEN)


def recipe(x, y, w, L, row_cls=None) -> str:
    """The recipe card: each step in plain words, with the real PDF instruction in small grey type under it."""
    rows = []
    for i, (step, code, colour) in enumerate(zip(L["steps"], CODE, STEP_COLOURS, strict=True)):
        yy = y + 40 + i * 50
        rows.append(f'<g class="a {(row_cls or [""] * 4)[i]}"><rect x="{x + 14}" y="{yy - 18}" width="5" height="40" rx="2" fill="{colour}"/>'
                    f'{label(x + 30, yy, f"{i + 1}. {step}", 18, weight=600)}{label(x + 30, yy + 19, code, 12.5, GREY, family=MONO)}</g>')
    return (f'<rect x="{x}" y="{y}" width="{w}" height="222" rx="10" fill="{PANEL}" stroke="{INK}" stroke-opacity=".3" stroke-width="2"/>'
            + "".join(rows))


def ch2(L) -> str:  # read: the recipe
    s, e = CH[2], CH[3]
    show("k2", s, e)
    cls = [show(f"k2r{i}", s + 1.2 + i * 1.8, e) for i in range(4)]
    boxes = [dashed(76, 106, 368, 211, MAGENTA, "k2r0"), dashed(278, 167, 146, 102, SKY, "k2r1"),
             dashed(376, 278, 60, 32, YELLOW, "k2r2"), dashed(98, 128, 186, 28, GREEN, "k2r3")]
    show("k2chip", s + 8.0, e)
    return f"""<g class="a k2">
  {slide(80, 110, 360, 203)}
  {"".join(boxes)}
  {recipe(470, 100, 450, L, cls)}
  {chip(480, 340, L["pikepdf"], BLUE, "k2chip")}
</g>"""


def ch3(L) -> str:  # measure
    s, e = CH[3], CH[4]
    show("k3", s, e)
    thumbs = []
    for i in range(6):
        x = 60 + i * 142
        thumbs.append(slide(x, 96, 120, 68))
        thumbs.append(dashed(x + 96, 150, 22, 13, YELLOW, show(f"k3t{i}", s + 0.8 + i * 0.4, e)))
    lines = []
    for i, colour in enumerate((YELLOW, MAGENTA, SKY, GREEN)):
        show(f"k3m{i}", s + 3.4 + i * 1.1, e)
        y = 204 + i * 34
        lines.append(f'<g class="a k3m{i}"><circle cx="78" cy="{y - 6}" r="7" fill="{colour}"/>{label(96, y, L["measure"][i], 18)}</g>')
    show("k3chip", s + 7.6, e)
    return f'<g class="a k3">{"".join(thumbs)}{"".join(lines)}{chip(480, 340, L["analysis"], BLUE, "k3chip")}</g>'


def ch4(L, lang) -> str:  # your choice beats the rules: keep the chart, shown slowly
    s, e = CH[4], CH[5]
    show("k4", s, e)
    ui = i18n(lang)
    t_mark, t_click, t_menu, t_pick = s + 1.0, s + 5.6, s + 6.0, s + 7.6
    anim("k4mark", [(t_mark, "opacity: 0"), (t_mark + 0.4, "opacity: 1"), (t_pick, "opacity: 1"), (t_pick + 0.3, "opacity: 0")], "opacity: 0;")
    show("k4logomark", t_mark, t_pick + 1.4)
    gone("k4logo", t_pick + 1.4)
    # the chart pulses while the caption says it matters
    anim("k4pulse", [(s + 2.4, "stroke-opacity: 0"), (s + 3.0, "stroke-opacity: 1"), (s + 3.6, "stroke-opacity: .2"),
                     (s + 4.2, "stroke-opacity: 1"), (s + 4.8, "stroke-opacity: 0")], "stroke-opacity: 0;")
    anim("k4cur", [(s + 4.6, "transform: translate(700px, 360px); opacity: 0"), (s + 4.9, "opacity: 1"),
                   (t_click - 0.2, "transform: translate(370px, 220px)"), (t_click, "transform: translate(368px, 223px)"),
                   (t_click + 0.3, "transform: translate(370px, 220px)"), (t_menu + 0.6, "transform: translate(370px, 220px)"),
                   (t_pick - 0.2, "transform: translate(470px, 244px)"), (t_pick, "transform: translate(468px, 247px)"),
                   (t_pick + 0.3, "transform: translate(470px, 244px); opacity: 1"), (e - 0.5, "opacity: 1"), (e, "opacity: 0")],
         "opacity: 0;")
    show("k4menu", t_menu, t_pick + 0.3, d=0.2)
    anim("k4hover", [(t_menu + 1.0, "fill-opacity: 0"), (t_pick - 0.3, "fill-opacity: .35")], "fill-opacity: 0;")
    show("k4kept", t_pick + 0.3, e)
    menu_rows = [ui["menu.keep_page"], ui["menu.keep_all"].replace("{n}", "6"), ui["menu.remove_page"]]
    menu = "".join(label(392, 252 + i * 34, t, 15, DARK) for i, t in enumerate(menu_rows))
    level = ui["tier.2.name"]
    return f"""<g class="a k4">
  {slide(80, 104, 440, 248, {"logo": "k4logo"}, chart=True)}
  <rect class="a k4pulse" x="324" y="168" width="184" height="128" rx="6" fill="none" stroke="{YELLOW}" stroke-width="5"/>
  <g class="a k4mark">{dashed(324, 168, 184, 128, MAGENTA)}{label(416, 158, L["removed"], 15, MAGENTA, anchor="middle", weight=700)}</g>
  <g class="a k4logomark">{dashed(442, 314, 66, 34, MAGENTA)}</g>
  <g transform="translate(600,130)"><rect width="250" height="46" rx="23" fill="{BLUE}" fill-opacity=".35" stroke="{BLUE}" stroke-width="2"/>
    {label(125, 30, level, 18, anchor="middle", weight=700)}</g>
  <g class="a k4kept">{dashed(324, 168, 184, 128, GREEN, width=4)}
    <rect x="346" y="138" width="140" height="26" rx="13" fill="{GREEN}"/>{label(416, 156, ui["el.keep"], 14, BG, anchor="middle", weight=700)}</g>
  <g class="a k4menu"><rect x="376" y="226" width="300" height="112" rx="10" fill="{INK}" stroke="{GREY}"/>
    <rect class="a k4hover" x="380" y="232" width="292" height="30" rx="6" fill="{GREEN}"/>{menu}</g>
  {cursor("k4cur")}
</g>"""


def ch5(L) -> str:  # rewrite
    s, e = CH[5], CH[6]
    show("k5", s, e)
    t_strike = s + 1.5
    strikes = []
    for i in (0, 2):  # background and logo steps go
        anim(f"k5s{i}", [(t_strike, "stroke-dashoffset: 1"), (t_strike + 0.8, "stroke-dashoffset: 0")], "stroke-dashoffset: 1;")
        gone(f"k5l{i}", t_strike + 2.4)
        y = 100 + 40 + i * 50 - 6
        strikes.append(f'<path class="a draw k5s{i} k5l{i}" pathLength="1" d="M86,{y} H{100 + len(L["steps"][i]) * 10.5:.0f}"'
                       f' stroke="{MAGENTA}" stroke-width="3"/>')
    show("k5black", s + 4.4, e)
    show("k5lens", s + 5.6, e)
    lens = L["lens"]
    return f"""<g class="a k5">
  {recipe(56, 100, 450, L, ["k5l0", "", "k5l2", ""])}
  {"".join(strikes)}
  <g class="a k5black"><path d="M96,322 V340" stroke="{GREEN}" stroke-width="2"/>
    {label(70, 362, L["black"], 16, GREEN, weight=600)}</g>
  <g class="a k5lens">
    <circle cx="730" cy="196" r="92" fill="{INK}" stroke="{INK}" stroke-width="6"/>
    <path d="M796,262 L846,312" stroke="{INK}" stroke-width="14" stroke-linecap="round"/>
    <text x="730" y="232" font-size="104" font-weight="700" fill="{DARK}" text-anchor="middle" font-family="Georgia, serif">Ag</text>
    {label(730, 326, lens[0], 16, anchor="middle", weight=600)}{label(730, 348, lens[1], 15, anchor="middle")}{label(730, 368, lens[2], 15, anchor="middle")}
  </g>
</g>"""


def pixels(x, y, cols, rows, size, dark: bool) -> str:
    """The page as the small picture pypdfium2 draws: a coarse grid of dark and light squares."""
    out = []
    for r_ in range(rows):
        for c_ in range(cols):
            text_row = r_ in (1, 3, 4) and 1 <= c_ <= 5
            fill = (INK if text_row else DARK) if dark else (DARK if text_row else INK)
            out.append(f'<rect x="{x + c_ * size}" y="{y + r_ * size}" width="{size - 2}" height="{size - 2}" fill="{fill}"/>')
    return "".join(out)


def ch6(L) -> str:  # check: draw pages, measure ink, no percentage
    s, e = CH[6], CH[7]
    show("k6", s, e)
    show("k6pix", s + 1.6, e)
    anim("k6bo", [(s + 3.2, "transform: scaleY(0)"), (s + 4.2, "transform: scaleY(1)")], "transform: scaleY(0); transform-origin: bottom;")
    anim("k6ba", [(s + 4.2, "transform: scaleY(0)"), (s + 5.2, "transform: scaleY(1)")], "transform: scaleY(0); transform-origin: bottom;")
    show("k6note", s + 5.8, e)
    CSS.append(".k6x { opacity: 0; }\n")
    clean = {"bg": "k6x", "logo": "k6x", "photo": "k6x", "wordfill": DARK}
    return f"""<g class="a k6">
  {slide(70, 98, 200, 113)}{label(170, 232, L["before"], 15, anchor="middle")}
  {slide(70, 248, 200, 113, clean)}
  <g class="a k6pix">
    <path d="M286,154 H330 M286,304 H330" stroke="{BLUE}" stroke-width="3" stroke-linecap="round"/>
    {pixels(344, 112, 10, 6, 15, True)}{pixels(344, 262, 10, 6, 15, False)}</g>
  <rect x="640" y="130" width="70" height="190" fill="none" stroke="{INK}" stroke-opacity=".3"/>
  <rect x="740" y="130" width="70" height="190" fill="none" stroke="{INK}" stroke-opacity=".3"/>
  <rect class="a k6bo" x="640" y="160" width="70" height="160" fill="{MAGENTA}"/>
  <rect class="a k6ba" x="740" y="290" width="70" height="30" fill="{GREEN}"/>
  {label(675, 344, L["before"], 15, anchor="middle")}{label(775, 344, L["after"], 15, anchor="middle")}
  {chip(726, 84, L["pdfium"], BLUE, "", 14)}
  <g class="a k6note">{label(480, 384, L["note"], 16, GREEN, anchor="middle", weight=600)}</g>
</g>"""


def ch7(L) -> str:  # the window
    s, e = CH[7], CH[8]
    show("k7", s, e)
    show("k7a", s + 1.6, e)
    show("k7b", s + 3.4, e)
    return f"""<g class="a k7">
  <rect x="250" y="80" width="460" height="214" rx="40" fill="none" stroke="{GREEN}" stroke-width="3" stroke-dasharray="10 8"/>
  {label(480, 104, L["computer"], 16, GREEN, anchor="middle", weight=600)}
  {laptop(380, 124, 200, 120)}
  <rect x="396" y="138" width="168" height="92" rx="6" fill="{INK}"/>
  <rect x="396" y="138" width="168" height="16" rx="6" fill="{GREY}"/>
  {slide(410, 166, 64, 36)}<rect x="484" y="166" width="64" height="36" fill="{INK}" stroke="{GREY}"/>
  <g class="a k7a">{chip(480, 306, L["fastapi"], BLUE, "", 15)}</g>
  <g class="a k7b">{chip(480, 346, L["webview"], BLUE, "", 15)}</g>
</g>"""


def ch8(L) -> str:  # budget and nature
    s, e = CH[8], CH[9]
    show("k8", s, e)
    for i in range(3):
        anim(f"k8i{i}", [(s + 1.0 + i * 1.6, "opacity: 0; transform: translateY(14px)"), (s + 1.6 + i * 1.6, "opacity: 1; transform: translateY(0)"),
                         (e - 0.4, "opacity: 1"), (e, "opacity: 0")], "opacity: 0;")
    coins = "".join(f'<ellipse cx="0" cy="{20 - i * 14}" rx="40" ry="12" fill="{PANEL}" stroke="{YELLOW}" stroke-width="4"/>' for i in range(4))
    cart = (f'<rect x="-34" y="-50" width="68" height="104" rx="10" fill="none" stroke="{INK}" stroke-width="4"/>'
            f'<rect x="-24" y="-20" width="48" height="64" rx="4" fill="{MAGENTA}"/>'
            f'<path d="M0,-86 C6,-76 10,-70 10,-64 A10,10 0 0 1 -10,-64 C-10,-70 -6,-76 0,-86 Z" fill="{MAGENTA}"/>')
    leaf = (f'<path d="M-46,30 C-46,-30 0,-70 52,-72 C50,-16 16,34 -40,34 Z" fill="{LEAF}"/>'
            f'<path d="M-40,30 C-10,0 14,-26 40,-58" fill="none" stroke="{BG}" stroke-width="4" stroke-linecap="round"/>'
            f'<path d="M-30,46 C-40,58 -48,64 -60,66" fill="none" stroke="{LEAF}" stroke-width="5" stroke-linecap="round"/>')
    items = [(220, coins, L["money"]), (480, cart, L["cart"]), (740, leaf, L["nature"])]
    return '<g class="a k8">' + "".join(
        f'<g class="a k8i{i}"><g transform="translate({x},200)">{art}</g>{label(x, 318, text, 18, anchor="middle", weight=600)}</g>'
        for i, (x, art, text) in enumerate(items)) + "</g>"


def end_card(lang) -> str:
    s = CH[9]
    anim("kend", [(s, "opacity: 0; transform: translateY(10px)"), (s + 0.6, "opacity: 1; transform: translateY(0)"),
                  (T - 0.4, "opacity: 1"), (T, "opacity: 0")], "opacity: 1;")
    logo = (ROOT / "app" / "static" / "logo.svg").read_text("utf-8")
    logo = re.sub(r"<\?xml[^>]*\?>\s*", "", logo)
    logo = re.sub(r"@media \(prefers-color-scheme: dark\) \{.*?\}\s*\}", "", logo, flags=re.S)
    logo = re.sub(r"<svg [^>]*>", '<svg x="432" y="96" width="96" height="96" viewBox="0 0 1024 1024">', logo, count=1)
    return (f'<g class="a kend">{logo}{label(480, 236, "PDF Distiller", 40, anchor="middle", weight=700)}'
            f'{label(480, 272, i18n(lang)["start.title"], 20, anchor="middle")}</g>')


def svg(lang: str) -> str:
    CSS.clear()
    L = TEXT[lang]
    body = [ch0(L), ch1(L), ch2(L), ch3(L), ch4(L, lang), ch5(L), ch6(L), ch7(L), ch8(L), end_card(lang)]
    caps = []
    for i, (a, b, c) in enumerate(L["cap"]):
        anim(f"c{i}", [(a, "opacity: 0; transform: translateY(8px)"), (a + 0.5, "opacity: 1; transform: translateY(0)"),
                       (b - 0.4, "opacity: 1"), (b, "opacity: 0")], "opacity: 0;")
        caps.append(label(480, 46, c, 18, anchor="middle", weight=600, cls=f"c{i}"))
    head = f"""
svg {{ font-family: Inter, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
.a {{ animation-duration: {T:g}s; animation-iteration-count: infinite; animation-fill-mode: both;
      animation-timing-function: cubic-bezier(.45,0,.25,1); transform-box: fill-box; }}
.draw {{ stroke-dasharray: 1; }}
"""
    still = "@media (prefers-reduced-motion: reduce) { .a { animation: none; } .kend { opacity: 1; } }\n"
    aria = " ".join(c for _, _, c in L["cap"]) + f" PDF Distiller. {i18n(lang)['start.title']}."
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 400" width="960" height="400" role="img" aria-label="{esc(aria)}">
<style>{head}{"".join(CSS)}{still}</style>
<rect width="960" height="400" rx="16" fill="{BG}"/>
{"".join(body)}
{"".join(caps)}
</svg>
"""


if __name__ == "__main__":
    for lang in TEXT:
        (HERE / f"inside.{lang}.svg").write_text(svg(lang), "utf-8")
    print("docs/inside.{en,de,tr}.svg written")
