"""Writes docs/inside.{de,tr}.svg from docs/inside.en.svg by swapping the visible texts.

    python docs/make_inside_i18n.py

docs/inside.en.svg is the source. Menu entries and the tagline come from the app's own translations
(app/static/i18n), so the film says exactly what the app says. Fails if a text is missing from the film.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
I18N = HERE.parent / "app" / "static" / "i18n"

TEXTS = {  # English text in the film -> (German, Turkish)
    "LOCAL DESKTOP · NO CLOUD": ("AUF IHREM RECHNER · OHNE INTERNET", "BİLGİSAYARINIZDA · İNTERNETE GİTMEZ"),
    "Stays on device": ("Bleibt auf dem Gerät", "Cihazda kalır"),
    "No cloud": ("Kein Internet", "İnternete gitmez"),
    "Your file never leaves your computer — everything runs locally.":
        ("Ihre Datei verlässt nie Ihren Rechner. Alles läuft hier.", "Dosyanız bilgisayarınızdan hiç çıkmaz; her şey burada çalışır."),
    "NO AI INSIDE · 4 CLEAR RULES": ("KEINE KI · 4 KLARE REGELN", "YAPAY ZEKÂ YOK · 4 AÇIK KURAL"),
    "PDF Drawing Recipe": ("Zeichenrezept des PDFs", "PDF çizim tarifi"),
    "Dark background": ("Dunkler Hintergrund", "Koyu arka plan"),
    "Repeated logo": ("Wiederholtes Logo", "Tekrar eden logo"),
    "Data chart": ("Diagramm", "Grafik"),
    "Vector text": ("Vektortext", "Vektör metin"),
    "No AI inside. pikepdf reads the PDF like a drawing recipe.":
        ("Keine KI. pikepdf liest das PDF wie ein Zeichenrezept.", "Yapay zekâ yok. pikepdf PDF'i bir çizim tarifi gibi okur."),
    "Remove": ("Entfernen", "Kaldır"),
    "Keep": ("Behalten", "Koru"),
    "Darkness &amp; Ink": ("Dunkelheit &amp; Tinte", "Koyuluk &amp; mürekkep"),
    "Detects heavy dark fills": ("Erkennt große dunkle Flächen", "Büyük koyu alanları bulur"),
    "Repetition Across Pages": ("Wiederholung über Seiten", "Sayfalar arası tekrar"),
    "Finds headers &amp; logos": ("Findet Kopfzeilen &amp; Logos", "Başlıkları ve logoları bulur"),
    "Size &amp; Coverage": ("Größe &amp; Fläche", "Boyut &amp; kaplama"),
    "Flags large raster images": ("Markiert große Bilder", "Büyük görselleri işaretler"),
    "Clear rules measure darkness, size, and repetition across pages.":
        ("Klare Regeln messen Dunkelheit, Größe und Wiederholung.", "Açık kurallar koyuluğu, boyutu ve tekrarı ölçer."),
    "YOU STAY IN CONTROL": ("SIE BEHALTEN DIE KONTROLLE", "KONTROL SİZDE"),
    "Lecture 04 — Signal Analysis": ("Vorlesung 04 — Signalanalyse", "Ders 04 — Sinyal Analizi"),
    "Measured Response": ("Gemessene Antwort", "Ölçülen tepki"),
    "× Remove": ("× Entfernen", "× Kaldır"),
    "✓ Kept": ("✓ Behalten", "✓ Korunuyor"),
    "Need a chart? Keep any element on a page with one click.":
        ("Diagramm gebraucht? Mit einem Klick auf der Seite behalten.", "Grafiğe mi ihtiyacınız var? Tek tıkla o sayfada koruyun."),
    "PIKEPDF + PYPDFIUM2 · VECTOR OUTPUT": ("PIKEPDF + PYPDFIUM2 · VEKTORAUSGABE", "PIKEPDF + PYPDFIUM2 · VEKTÖR ÇIKTI"),
    "Sharp vector text": ("Scharfer Vektortext", "Keskin vektör metin"),
    "Ink Estimate": ("Tintenschätzung", "Mürekkep tahmini"),
    "Distilled": ("Bereinigt", "Sadeleşmiş"),
    "Original": ("Original", "Orijinal"),
    "Budget": ("Budget", "Bütçe"),
    "Nature": ("Natur", "Doğa"),
    "Wasted ink dissolves into dots. Text stays sharp, resources spared.":
        ("Verschwendete Tinte zerfällt in Punkte. Text bleibt scharf.", "Boşa giden mürekkep noktalara ayrılır. Metin keskin kalır."),
    "OPEN &amp; TRANSPARENT": ("OFFEN &amp; TRANSPARENT", "AÇIK &amp; ŞEFFAF"),
    "Local desktop app · Less waste for your budget and nature":
        ("Lokale Desktop-App · Weniger Verschwendung für Budget und Natur", "Yerel masaüstü uygulaması · Bütçeniz ve doğa için daha az israf"),
}
ARIA = {
    "de": "So arbeitet PDF Distiller lokal und ohne KI: Ihre Datei bleibt auf Ihrem Rechner, pikepdf liest ihr Zeichenrezept, "
          "klare Regeln messen Dunkelheit und Wiederholung, ein wichtiges Diagramm behalten Sie mit einem Klick, "
          "verschwendete Tinte zerfällt in Punkte, und Vektortext bleibt scharf.",
    "tr": "PDF Distiller yapay zekâ olmadan, bilgisayarınızda nasıl çalışır: dosyanız bilgisayarınızda kalır, pikepdf çizim "
          "tarifini okur, açık kurallar koyuluğu ve tekrarı ölçer, önemli bir grafiği tek tıkla korursunuz, boşa giden "
          "mürekkep noktalara ayrılır ve vektör metin keskin kalır.",
}


def menu(lang: str) -> dict[str, str]:
    t = json.loads((I18N / f"{lang}.json").read_text("utf-8"))
    strip = lambda s: re.sub(r"\s*\(\{n\}\)", "", s)  # noqa: E731
    return {"Remove on all pages": strip(t["menu.remove_all"]), "Keep on this page": t["menu.keep_page"],
            "Keep on all pages": strip(t["menu.keep_all"]), "Print the slides, not the ink.": t["start.title"]}


def main() -> None:
    en = (HERE / "inside.en.svg").read_text("utf-8")
    for i, lang in enumerate(("de", "tr")):
        s = en
        pairs = {k: v[i] for k, v in TEXTS.items()} | menu(lang)
        for old, new in pairs.items():
            tag = f">{old}<"
            assert tag in s, f"not in the film: {old}"
            s = s.replace(tag, f">{new}<")
        s = re.sub(r'aria-label="[^"]*"', f'aria-label="{ARIA[lang]}"', s, count=1)
        (HERE / f"inside.{lang}.svg").write_text(s, "utf-8")
    print("docs/inside.{de,tr}.svg written")


if __name__ == "__main__":
    main()
