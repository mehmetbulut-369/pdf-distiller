"""Writes docs/story.{en,de,tr}.svg: the README's one-line animation (La Linea *technique*, original drawing).

    python docs/make_story.py

One white line on a flat background tells the problem and the fix in five scenes, 18 s, looping.
Pure SVG + CSS, so GitHub plays it from an <img>. With reduced motion it shows the last scene still.
"""
from __future__ import annotations

import random
from pathlib import Path

T = 18  # seconds per loop
BG, INK = "#0F2C4C", "#F5F7FA"
CAPTIONS = {
    "en": ["A lecture slide. Mostly background.",
           "Printed as it is, most of the ink goes into the background.",
           "So first the app asks: what is this page made of?",
           "Background, repeated logos, big photos: lifted off.",
           "Only what you need gets printed. Every dot counts."],
    "de": ["Eine Vorlesungsfolie. Vor allem Hintergrund.",
           "So gedruckt, landet die meiste Tinte im Hintergrund.",
           "Deshalb fragt die App zuerst: Woraus besteht diese Seite?",
           "Hintergrund, wiederholte Logos, große Fotos: weg damit.",
           "Gedruckt wird nur, was Sie brauchen. Jeder Punkt zählt."],
    "tr": ["Bir ders slaytı. Çoğu arka plan.",
           "Olduğu gibi basılınca mürekkebin çoğu arka plana gider.",
           "Bu yüzden uygulama önce sorar: Bu sayfa nelerden oluşuyor?",
           "Arka plan, tekrar eden logolar, büyük fotoğraflar: ayıklanır.",
           "Yalnız ihtiyacınız olan basılır. Her nokta önemli."],
}
# caption windows in % of the loop
WINDOWS = [(9, 19), (21, 38), (40, 57), (59, 77), (79, 97)]


def css() -> str:
    rnd = random.Random(7)
    out = [f"""
svg {{ font-family: Inter, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
.a {{ animation-duration: {T}s; animation-iteration-count: infinite; animation-fill-mode: both;
      animation-timing-function: ease-in-out; transform-box: fill-box; }}
.draw {{ stroke-dasharray: 1; stroke-dashoffset: 0; }}
@keyframes draw {{ 0%, 2% {{ stroke-dashoffset: 1; }} 9%, 97% {{ stroke-dashoffset: 0; }} 100% {{ stroke-dashoffset: 1; }} }}
.page, .figure {{ animation-name: draw; }}
@keyframes block {{ 0%, 8% {{ opacity: 0; }} 11%, 60% {{ opacity: 1; }} 66%, 100% {{ opacity: 0; }} }}
.block {{ animation-name: block; opacity: 0; }}
@keyframes text {{ 0%, 8% {{ fill: {INK}; opacity: 0; }} 11% {{ fill: {BG}; opacity: 1; }}
  62% {{ fill: {BG}; }} 70%, 97% {{ fill: {INK}; opacity: 1; }} 100% {{ opacity: 0; }} }}
.text {{ animation-name: text; fill: {INK}; }}
@keyframes puddle {{ 0%, 22% {{ transform: scaleX(0); }} 38%, 58% {{ transform: scaleX(1); }} 70%, 100% {{ transform: scaleX(0); }} }}
.puddle {{ animation-name: puddle; transform-origin: center; transform: scaleX(0); }}
@keyframes small {{ 0%, 84% {{ transform: scaleX(0); }} 88%, 96% {{ transform: scaleX(1); }} 100% {{ transform: scaleX(0); }} }}
.small {{ animation-name: small; transform-origin: center; }}
@keyframes lens {{ 0%, 39% {{ opacity: 0; transform: translate(0, 0); }} 41% {{ opacity: 1; transform: translate(0, 0); }}
  47% {{ transform: translate(230px, -105px); }} 52% {{ transform: translate(345px, -60px); }}
  56% {{ opacity: 1; transform: translate(260px, -25px); }} 58%, 100% {{ opacity: 0; transform: translate(260px, -25px); }} }}
.lens {{ animation-name: lens; opacity: 0; }}
@keyframes lastdrop {{ 0%, 80% {{ opacity: 0; transform: translateY(0); }} 81% {{ opacity: 1; }}
  86% {{ opacity: 1; transform: translateY(80px); }} 87%, 100% {{ opacity: 0; transform: translateY(80px); }} }}
.lastdrop {{ animation-name: lastdrop; opacity: 0; }}
"""]
    for i, (a, b) in enumerate(WINDOWS):
        out.append(f"@keyframes c{i} {{ 0%, {a - 1}% {{ opacity: 0; }} {a}%, {b}% {{ opacity: 1; }} {b + 1}%, 100% {{ opacity: 0; }} }}\n"
                   f".c{i} {{ animation-name: c{i}; opacity: {1 if i == 4 else 0}; }}\n")
    for i, (start, colour) in enumerate(((43, "#F0679E"), (46, "#F2C230"), (49, "#6BBEEC"), (52, "#4CC38A"))):
        out.append(f"@keyframes b{i} {{ 0%, {start - 1}% {{ opacity: 0; }} {start}%, 58% {{ opacity: 1; }} 60%, 100% {{ opacity: 0; }} }}\n"
                   f".b{i} {{ animation-name: b{i}; opacity: 0; stroke: {colour}; }}\n")
    for i in range(10):  # ink drops, scene 2
        s = 21 + i * 1.4
        out.append(f"@keyframes d{i} {{ 0%, {s:.1f}% {{ opacity: 0; transform: translateY(0); }} {s + 0.3:.1f}% {{ opacity: 1; }}"
                   f" {s + 4:.1f}% {{ opacity: 1; transform: translateY(80px); }} {s + 4.3:.1f}%, 100% {{ opacity: 0; transform: translateY(80px); }} }}\n"
                   f".d{i} {{ animation-name: d{i}; opacity: 0; }}\n")
    for i in range(48):  # the removed background rises as dots, scene 4
        s = 60 + rnd.random() * 4
        dx, dy = rnd.uniform(-40, 40), rnd.uniform(-150, -70)
        out.append(f"@keyframes v{i} {{ 0%, {s:.1f}% {{ opacity: 0; transform: translate(0, 0); }} {s + 0.5:.1f}% {{ opacity: .9; }}"
                   f" {s + 9:.1f}%, 100% {{ opacity: 0; transform: translate({dx:.0f}px, {dy:.0f}px); }} }}\n"
                   f".v{i} {{ animation-name: v{i}; opacity: 0; }}\n")
    out.append("@media (prefers-reduced-motion: reduce) { .a { animation: none; } }\n")
    return "".join(out)


def svg(lang: str) -> str:
    rnd = random.Random(11)
    caps = "".join(f'<text class="a c{i}" x="480" y="62" text-anchor="middle" font-size="25" font-weight="600" fill="{INK}">{c}</text>'
                   for i, c in enumerate(CAPTIONS[lang]))
    drop = "M0,-9 C4,-3 6,1 6,4 A6,6 0 0 1 -6,4 C-6,1 -4,-3 0,-9 Z"
    # the CSS transform would replace a transform attribute: position with a parent <g>
    drops = "".join(f'<g transform="translate({398 + i * 18},282)"><path class="a d{i}" d="{drop}" fill="{INK}"/></g>' for i in range(10))
    dots = "".join(f'<circle class="a v{i}" cx="{rnd.uniform(395, 565):.0f}" cy="{rnd.uniform(130, 255):.0f}" r="{rnd.uniform(2.5, 5):.1f}" fill="{INK}"/>'
                   for i in range(48))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 400" width="960" height="400" role="img" aria-label="{' '.join(CAPTIONS[lang])}">
<style>{css()}</style>
<rect width="960" height="400" rx="16" fill="{BG}"/>
{caps}
<g fill="none" stroke="{INK}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
  <path d="M40,362 H920"/>
  <path class="a draw figure" pathLength="1" d="M190,362 V262 M190,262 a22,22 0 1 1 0.01,0 M190,290 L232,268"/>
  <path class="a draw page" pathLength="1" d="M300,362 C340,362 360,330 370,300 L380,120 H590 V280 H380"/>
</g>
<g class="a block">
  <rect x="388" y="128" width="194" height="144" rx="3" fill="{INK}"/>
  <circle cx="563" cy="146" r="9" fill="{BG}"/>
  <rect x="520" y="200" width="48" height="56" rx="3" fill="{BG}"/>
  <path d="M522,250 L536,228 L546,240 L554,230 L566,250 Z" fill="{INK}"/>
</g>
<g class="a text"><rect x="400" y="150" width="104" height="9" rx="4"/><rect x="400" y="174" width="96" height="9" rx="4"/>
  <rect x="400" y="198" width="80" height="9" rx="4"/><rect x="400" y="222" width="100" height="9" rx="4"/></g>
<g fill="none" stroke-width="3" stroke-dasharray="7 6">
  <rect class="a b0" x="384" y="124" width="202" height="152" rx="5"/>
  <rect class="a b1" x="549" y="132" width="28" height="28" rx="4"/>
  <rect class="a b2" x="514" y="194" width="60" height="68" rx="4"/>
  <rect class="a b3" x="394" y="144" width="116" height="94" rx="4"/>
</g>
<g class="a lens" fill="none" stroke="{INK}" stroke-width="4" stroke-linecap="round">
  <circle cx="250" cy="250" r="22"/><path d="M234,266 L218,282"/>
</g>
{drops}
{dots}
<ellipse class="a puddle" cx="485" cy="358" rx="120" ry="7" fill="{INK}"/>
<g transform="translate(485,282)"><path class="a lastdrop" d="{drop}" fill="{INK}"/></g>
<ellipse class="a small" cx="485" cy="359" rx="14" ry="5" fill="{INK}"/>
</svg>
"""


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for lang in CAPTIONS:
        (here / f"story.{lang}.svg").write_text(svg(lang), "utf-8")
    print("docs/story.{en,de,tr}.svg written")
