"""Writes docs/story.{de,tr}.svg from docs/story.en.svg by swapping the visible texts.

python docs/make_story_i18n.py docs/story.en.svg docs/story.LANG.svg
"""

import sys

src = open(sys.argv[1], encoding="utf-8").read()
EN_ARIA = src.split('aria-label="', 1)[1].split('"', 1)[0]
T = {
    "de": {
        "aria": "Die Geschichte von PDF Distiller: Neue Vorlesungsfolien kommen an. Beim Durchblättern zeigt sich: Kopfzeilen, Logos und große Bilder, gemacht für die Leinwand im Hörsaal, nicht für Papier. Vor dem Drucken öffnen Sie PDF Distiller auf Ihrem eigenen Rechner und ziehen die Folien hinein. Mit einem Klick entfernen Sie das Bergfoto, dann die wiederkehrenden Banner auf allen Seiten; das Diagramm bleibt unberührt. Die gesparte Tinte zerfällt in Punkte und kehrt zu Patrone, Geldbeutel und Natur zurück. Übrig bleibt klares Papier für ruhiges Lernen. Folien drucken. Tinte sparen.",
        ">New lecture slides arrived. Let's open them.<": ">Neue Vorlesungsfolien sind da. Mal reinschauen.<",
        ">New lecture slides.pdf<": ">Neue Vorlesungsfolien.pdf<",
        ">Great slides—full of headers, logos, and large visuals.<": ">Schöne Folien – voller Kopfzeilen, Logos und großer Bilder.<",
        ">Designed for the lecture hall screen—not for paper.<": ">Gemacht für die Leinwand im Hörsaal – nicht für Papier.<",
        ">I focus better on paper—but why waste ink on notes I'll read once?<": ">Auf Papier lerne ich besser – aber so viel Tinte zum Wegwerfen?<",
        ">Print<": ">Drucken<",
        ">Open PDF Distiller locally. Drop the slides in.<": ">PDF Distiller auf dem eigenen Rechner öffnen, Folien hineinziehen.<",
        ">Stays on your computer<": ">Bleibt auf Ihrem Rechner<",
        ">Remove the photo and repeated banners. Leave the chart untouched.<": ">Foto und wiederkehrende Banner entfernen. Das Diagramm bleibt.<",
        ">× Remove<": ">× Entfernen<",
        ">Remove from all pages<": ">Auf allen Seiten entfernen<",
        ">Remove on this page<": ">Nur auf dieser Seite<",
        ">Crisp paper. Clear mind. Less waste.<": ">Klares Papier. Klarer Kopf. Weniger Abfall.<",
        ">Print the slides, not the ink.<": ">Folien drucken. Tinte sparen.<",
    },
    "tr": {
        "aria": "PDF Distiller'ın hikâyesi: Yeni ders slaytları gelir. Sayfalar kaydırıldıkça başlıklar, logolar ve büyük görseller görünür; hepsi kâğıt için değil, amfideki perde için hazırlanmış. Yazdırmadan önce PDF Distiller kendi bilgisayarınızda açılır, slaytlar içine bırakılır. Önce dağ fotoğrafı tek tıkla kaldırılır, sonra tekrar eden bantlar tüm sayfalardan; grafiğe dokunulmaz. Tasarruf edilen mürekkep noktalara ayrılıp kartuşa, cüzdana ve doğaya döner. Geriye sakin çalışmak için temiz kâğıt kalır. Slaytları yazdırın, mürekkebi değil.",
        ">New lecture slides arrived. Let's open them.<": ">Yeni ders slaytları geldi. Bir bakalım.<",
        ">New lecture slides.pdf<": ">Yeni ders slaytları.pdf<",
        ">Great slides—full of headers, logos, and large visuals.<": ">Güzel slaytlar: başlıklar, logolar, büyük görseller.<",
        ">Designed for the lecture hall screen—not for paper.<": ">Kâğıt için değil, amfideki perde için hazırlanmış.<",
        ">I focus better on paper—but why waste ink on notes I'll read once?<": ">Kâğıtta daha iyi çalışırım; ama tek seferlik nota bunca mürekkep mi?<",
        ">Print<": ">Yazdır<",
        ">Open PDF Distiller locally. Drop the slides in.<": ">PDF Distiller'ı kendi bilgisayarında aç, slaytları bırak.<",
        ">Stays on your computer<": ">Bilgisayarınızda kalır<",
        ">Remove the photo and repeated banners. Leave the chart untouched.<": ">Fotoğrafı ve tekrar eden bantları kaldır. Grafiğe dokunma.<",
        ">× Remove<": ">× Kaldır<",
        ">Remove from all pages<": ">Tüm sayfalardan kaldır<",
        ">Remove on this page<": ">Yalnız bu sayfadan<",
        ">Crisp paper. Clear mind. Less waste.<": ">Temiz kâğıt. Berrak zihin. Daha az israf.<",
        ">Print the slides, not the ink.<": ">Slaytları yazdırın, mürekkebi değil.<",
    },
}
for lang, m in T.items():
    out = src.replace(EN_ARIA, m["aria"])
    for k, v in m.items():
        if k == "aria":
            continue
        assert out.count(k) >= 1, (lang, k)
        out = out.replace(k, v)
    open(sys.argv[2].replace("LANG", lang), "w", encoding="utf-8").write(out)
print("ok")
