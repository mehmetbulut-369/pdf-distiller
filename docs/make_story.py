"""Writes docs/story.{en,de,tr}.svg: the README's one-line animation, seen through the student's eyes.

    python docs/make_story.py

First person: the viewer sits at the desk. A laptop, two hands coming in from the bottom edge, a
printed page, a pen. One white line on a flat background (La Linea *technique*; the drawing is
original). Pure SVG + CSS so GitHub plays it from an <img>; with reduced motion the end card shows.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
T = 22  # seconds per loop
BG, INK = "#0F2C4C", "#F5F7FA"
DARK, GREY, NAVY = "#1E2733", "#5C6B7E", "#0C447C"  # printed ink, photo, the logo's nib
MAGENTA, YELLOW, SKY, GREEN = "#F0679E", "#F2C230", "#6BBEEC", "#4CC38A"  # the app's element colours

CAPTIONS = {
    "en": ["Exam week. I print my slides, like always.",
           "Most of the ink goes into backgrounds I never read.",
           "So now I ask first: what is this page made of?",
           "Backgrounds, repeated logos, big photos: gone.",
           "Only what I need, and room for my own thoughts."],
    "de": ["Prüfungsphase. Ich drucke meine Folien, wie immer.",
           "Die meiste Tinte landet in Hintergründen, die ich nie lese.",
           "Also frage ich jetzt zuerst: Woraus besteht diese Seite?",
           "Hintergründe, wiederholte Logos, große Fotos: weg.",
           "Nur, was ich brauche, und Platz für meine Gedanken."],
    "tr": ["Sınav haftası. Slaytlarımı her zamanki gibi basıyorum.",
           "Mürekkebin çoğu hiç okumadığım arka planlara gidiyor.",
           "Artık önce soruyorum: Bu sayfa nelerden oluşuyor?",
           "Arka planlar, tekrar eden logolar, büyük fotoğraflar: gitti.",
           "Yalnız ihtiyacım olan, bir de kendi düşüncelerime yer."],
}
CAPTION_AT = [(5, 19), (25, 40), (44, 54), (56, 64), (69, 84)]  # % of the loop


def tagline(lang: str) -> str:
    return json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text("utf-8"))["start.title"]


def fade(name: str, windows: list[tuple[float, float]], f: float = 1.5, base: float = 0) -> str:
    """Opacity 0 → 1 → 0 for each (start, end) window, in % of the loop."""
    stops = ["0% { opacity: 0; }"]
    for a, b in windows:
        stops += [f"{a}% {{ opacity: 0; }}", f"{a + f}%, {b - f}% {{ opacity: 1; }}", f"{b}% {{ opacity: 0; }}"]
    stops.append("100% { opacity: 0; }")
    return f"@keyframes {name} {{ {' '.join(stops)} }}\n.{name} {{ animation-name: {name}; opacity: {base}; }}\n"


def css() -> str:
    rnd = random.Random(7)
    out = [f"""
svg {{ font-family: Inter, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
.a {{ animation-duration: {T}s; animation-iteration-count: infinite; animation-fill-mode: both;
      animation-timing-function: cubic-bezier(.45,0,.25,1); transform-box: fill-box; }}
.draw {{ stroke-dasharray: 1; }}
@keyframes drawlap {{ 0% {{ stroke-dashoffset: 1; }} 5%, 100% {{ stroke-dashoffset: 0; }} }}
.drawlap {{ animation-name: drawlap; }}
@keyframes slide {{ 0%, 3% {{ opacity: 0; }} 7%, 100% {{ opacity: 1; }} }}
.slide {{ animation-name: slide; }}
@keyframes block {{ 0%, 58% {{ opacity: 1; }} 61%, 100% {{ opacity: 0; }} }}
.block {{ animation-name: block; }}
@keyframes words {{ 0%, 59% {{ fill: {INK}; }} 62%, 100% {{ fill: {DARK}; }} }}
.words {{ animation-name: words; fill: {INK}; }}
/* the finger taps print (14 %) and later the app (51 %, 55 %) */
@keyframes tap {{ 0%, 9% {{ transform: translateY(150px); }} 12% {{ transform: translateY(0); }}
  13.5% {{ transform: translateY(6px); }} 15%, 17% {{ transform: translateY(0); }} 20%, 46% {{ transform: translateY(150px); }}
  49% {{ transform: translateY(0); }} 50.5% {{ transform: translateY(6px); }} 52% {{ transform: translateY(0); }}
  54% {{ transform: translateY(6px); }} 55.5%, 57% {{ transform: translateY(0); }} 60%, 100% {{ transform: translateY(150px); }} }}
.tap {{ animation-name: tap; transform: translateY(150px); }}
/* printed pages drop in from the printer above, with a small settle */
@keyframes inkpage {{ 0%, 22% {{ transform: translateY(-330px); }} 27% {{ transform: translateY(8px); }}
  28.5%, 40% {{ transform: translateY(0); }} 43%, 100% {{ transform: translateY(-330px); }} }}
.inkpage {{ animation-name: inkpage; transform: translateY(-330px); }}
@keyframes cleanpage {{ 0%, 66% {{ transform: translateY(-330px); }} 71% {{ transform: translateY(8px); }}
  72.5%, 84% {{ transform: translateY(0); }} 87%, 100% {{ transform: translateY(-330px); }} }}
.cleanpage {{ animation-name: cleanpage; transform: translateY(-330px); }}
@keyframes hands {{ 0%, 26% {{ transform: translateY(160px); }} 30%, 40% {{ transform: translateY(0); }}
  43%, 70% {{ transform: translateY(160px); }} 74%, 84% {{ transform: translateY(0); }} 87%, 100% {{ transform: translateY(160px); }} }}
.hands {{ animation-name: hands; transform: translateY(160px); }}
@keyframes holdright {{ 0%, 26% {{ transform: translateY(160px); }} 30%, 40% {{ transform: translateY(0); }} 43%, 100% {{ transform: translateY(160px); }} }}
.holdright {{ animation-name: holdright; transform: translateY(160px); }}
@keyframes pen {{ 0%, 70% {{ opacity: 0; transform: translate(60px, 200px); }} 71% {{ opacity: 1; }} 74%, 75% {{ transform: translate(0, 0); }}
  79% {{ transform: translate(170px, 0); }} 80.5% {{ transform: translate(240px, -52px); }} 83% {{ transform: translate(300px, -52px); }}
  84% {{ transform: translate(300px, -52px); }} 86% {{ opacity: 1; }} 87%, 100% {{ opacity: 0; transform: translate(360px, 200px); }} }}
.pen {{ animation-name: pen; opacity: 0; }}
@keyframes underline {{ 0%, 75% {{ stroke-dashoffset: 1; opacity: 1; }} 79%, 84% {{ stroke-dashoffset: 0; opacity: 1; }} 86%, 100% {{ stroke-dashoffset: 0; opacity: 0; }} }}
.underline {{ animation-name: underline; }}
@keyframes note {{ 0%, 80.5% {{ stroke-dashoffset: 1; opacity: 1; }} 83%, 84% {{ stroke-dashoffset: 0; opacity: 1; }} 86%, 100% {{ stroke-dashoffset: 0; opacity: 0; }} }}
.note {{ animation-name: note; }}
/* ink cartridge drains while the dark page prints */
@keyframes level {{ 0%, 23% {{ transform: scaleY(1); }} 33%, 100% {{ transform: scaleY(.18); }} }}
.level {{ animation-name: level; transform-origin: bottom; }}
@keyframes endcard {{ 0%, 87% {{ opacity: 0; transform: translateY(10px); }} 90%, 98% {{ opacity: 1; transform: translateY(0); }} 100% {{ opacity: 0; }} }}
.endcard {{ animation-name: endcard; opacity: 1; }}
"""]
    out.append(fade("laptop", [(0, 21), (42, 66)], base=0))
    out.append(fade("cart", [(22, 41)]))
    out += [f"@keyframes c{i} {{ 0%, {a}% {{ opacity: 0; transform: translateY(8px); }} {a + 1.5}%, {b - 1.5}% {{ opacity: 1; transform: translateY(0); }}"
            f" {b}%, 100% {{ opacity: 0; transform: translateY(0); }} }}\n.c{i} {{ animation-name: c{i}; opacity: 0; }}\n"
            for i, (a, b) in enumerate(CAPTION_AT)]
    for i, start in enumerate((46, 47.5, 49, 50.5)):
        out.append(fade(f"b{i}", [(start, 57)], f=0.8))
    for i in range(56):  # the removed background rises as dots
        s = 57 + rnd.random() * 3
        dx, dy = rnd.uniform(-30, 30), rnd.uniform(-120, -60)
        out.append(f"@keyframes v{i} {{ 0%, {s:.1f}% {{ opacity: 0; transform: translate(0, 0); }} {s + 0.4:.1f}% {{ opacity: .95; }}"
                   f" {s + 6:.1f}%, 100% {{ opacity: 0; transform: translate({dx:.0f}px, {dy:.0f}px); }} }}\n.v{i} {{ animation-name: v{i}; opacity: 0; }}\n")
    out.append("@media (prefers-reduced-motion: reduce) { .a { animation: none; } }\n")
    return "".join(out)


def logo() -> str:
    s = (ROOT / "app" / "static" / "logo.svg").read_text("utf-8")
    s = re.sub(r"<\?xml[^>]*\?>\s*", "", s)
    s = re.sub(r"@media \(prefers-color-scheme: dark\) \{.*?\}\s*\}", "", s, flags=re.S)
    return re.sub(r"<svg [^>]*>", '<svg x="432" y="72" width="96" height="96" viewBox="0 0 1024 1024">', s, count=1)


# hand shapes, drawn once; fill BG so a hand covers what is behind it
POINT = ("M-7,4 Q0,-7 7,4 L15,58 Q40,60 56,80 Q70,100 72,150 L4,150 Q-4,120 -8,96 Q-18,80 -8,66 Z"
         " M15,58 Q4,64 -8,66")
HOLD = ("M0,0 Q12,-4 15,8 L19,34 Q44,44 50,74 L52,130 L-46,130 L-46,70 Q-42,38 -16,26 L-8,10 Q-8,0 0,0 Z")
PENHAND = "M44,76 Q66,62 82,80 Q98,100 98,150 L32,150 Q26,118 36,100 Q30,86 44,76 Z"


def slide_content() -> str:
    """The dark slide, used on the laptop screen and on the first printout (same coordinates)."""
    rnd = random.Random(11)
    dots = "".join(f'<circle class="a v{i}" cx="{rnd.uniform(326, 634):.0f}" cy="{rnd.uniform(86, 244):.0f}" r="{rnd.uniform(2.5, 5):.1f}" fill="{DARK}"/>'
                   for i in range(56))
    return dots


def svg(lang: str) -> str:
    caps = "".join(f'<text class="a c{i}" x="480" y="38" text-anchor="middle" font-size="22" font-weight="600" fill="{INK}">{c}</text>'
                   for i, c in enumerate(CAPTIONS[lang]))
    lines = ((340, 108, 150), (340, 134, 132), (340, 160, 110), (340, 186, 140))
    words = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="10" rx="5"/>' for x, y, w in lines)
    clean_words = "".join(f'<rect x="{x}" y="{y + 10}" width="{w}" height="10" rx="5" fill="{DARK}"/>' for x, y, w in lines)
    label = " ".join(CAPTIONS[lang]) + f" PDF Distiller. {tagline(lang)}."
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 400" width="960" height="400" role="img" aria-label="{label}">
<style>{css()}</style>
<rect width="960" height="400" rx="16" fill="{BG}"/>
<!-- 1 and 3: the laptop on my desk -->
<g class="a laptop" fill="none" stroke="{INK}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
  <path class="a draw drawlap" pathLength="1" d="M310,262 V74 Q310,62 322,62 H638 Q650,62 650,74 V262 M250,262 H710 M290,262 L210,400 M670,262 L750,400 M420,320 H540 L548,400 M420,320 L412,400"/>
  <g class="a slide" stroke="none">
    <rect x="322" y="82" width="316" height="166" rx="3" fill="{INK}"/>
    <g class="a block"><rect x="322" y="82" width="316" height="166" rx="3" fill="{DARK}"/>
      <circle cx="612" cy="104" r="11" fill="{GREY}"/><rect x="560" y="170" width="64" height="66" rx="3" fill="{GREY}"/>
      <path d="M563,232 L580,206 L592,220 L602,208 L621,232 Z" fill="{DARK}"/></g>
    <g class="a words">{words}</g>
    {slide_content()}
  </g>
  <g stroke-width="3" stroke-dasharray="7 6">
    <rect class="a b0" x="318" y="78" width="324" height="174" rx="5" stroke="{MAGENTA}"/>
    <rect class="a b1" x="597" y="89" width="30" height="30" rx="4" stroke="{YELLOW}"/>
    <rect class="a b2" x="554" y="164" width="76" height="78" rx="4" stroke="{SKY}"/>
    <rect class="a b3" x="332" y="100" width="166" height="104" rx="4" stroke="{GREEN}"/>
  </g>
</g>
<!-- my finger -->
<g transform="translate(486,352)"><path class="a tap" d="{POINT}" fill="{BG}" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/></g>
<!-- 2: the printout, soaked in ink -->
<g class="a inkpage">
  <rect x="300" y="60" width="360" height="250" rx="4" fill="{INK}" stroke="{INK}" stroke-width="4"/>
  <rect x="312" y="72" width="336" height="226" rx="2" fill="{DARK}"/>
  <circle cx="622" cy="98" r="12" fill="{GREY}"/><rect x="566" y="190" width="68" height="78" rx="3" fill="{GREY}"/>
  {"".join(f'<rect x="{x - 10}" y="{y + 4}" width="{w}" height="10" rx="5" fill="{INK}"/>' for x, y, w in lines)}
</g>
<!-- 4: the clean printout, and what I write on it -->
<g class="a cleanpage">
  <rect x="300" y="60" width="360" height="250" rx="4" fill="{INK}" stroke="{INK}" stroke-width="4"/>
  {clean_words}
  <path class="a draw underline" pathLength="1" d="M340,162 C380,158 440,164 512,160" fill="none" stroke="#2E8B57" stroke-width="4" stroke-linecap="round"/>
  <path class="a draw note" pathLength="1" d="M572,104 q8,-12 16,0 t16,0 t16,0 t16,0 M582,126 l8,8 l20,-22" fill="none" stroke="#2E8B57" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
</g>
<!-- my hands holding the page; the right one only for the ink page, later it holds the pen -->
<g fill="{BG}" stroke="{INK}" stroke-width="4" stroke-linejoin="round">
  <g transform="translate(318,302)"><path class="a hands" d="{HOLD}"/></g>
  <g transform="translate(642,302) scale(-1,1)"><path class="a holdright" d="{HOLD}"/></g>
  <g transform="translate(340,158)"><g class="a pen">
    <path d="M0,0 L54,84" stroke="{NAVY}" stroke-width="8" stroke-linecap="round"/><path d="M-1,-2 L-5,-14 L7,-7 Z" fill="{NAVY}" stroke="{NAVY}" stroke-width="2"/>
    <path d="{PENHAND}"/></g></g>
</g>
<!-- ink cartridge -->
<g class="a cart" transform="translate(824,72)">
  <rect width="44" height="72" rx="7" fill="none" stroke="{INK}" stroke-width="4"/>
  <rect class="a level" x="8" y="8" width="28" height="56" rx="3" fill="{MAGENTA}"/>
  <path d="M22,-26 C27,-18 30,-13 30,-9 A8,8 0 0 1 14,-9 C14,-13 17,-18 22,-26 Z" fill="{INK}"/>
</g>
{caps}
<!-- end card: the reduced-motion still -->
<g class="a endcard">
  {logo()}
  <text x="480" y="216" text-anchor="middle" font-size="40" font-weight="700" fill="{INK}">PDF Distiller</text>
  <text x="480" y="254" text-anchor="middle" font-size="21" fill="{INK}" opacity=".85">{tagline(lang)}</text>
</g>
</svg>
"""


if __name__ == "__main__":
    for lang in CAPTIONS:
        (HERE / f"story.{lang}.svg").write_text(svg(lang), "utf-8")
    print("docs/story.{en,de,tr}.svg written")
