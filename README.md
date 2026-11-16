# PDF Distiller

Ders slaytlarını yazdırmadan önce sadeleştiren lokal araç. Zeminleri, tekrar eden
tema öğelerini (logo, bant, filigran) ve büyük görselleri ayıklar; metni okunur
bırakır. Dosyalar bilgisayarınızdan çıkmaz.

## Kurulum ve çalıştırma

Gerekli: Python 3.10 veya üstü.

**macOS:** `start_mac.command` dosyasına çift tıklayın. İlk seferde macOS "tanımlanmamış
geliştirici" uyarısı verirse: sağ tık > Aç. Alternatif olarak Terminal'de:

```bash
cd pdf-distiller
chmod +x start_mac.command && ./start_mac.command
```

**Windows:** `start_windows.bat` dosyasına çift tıklayın.

**Elle:**

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py              # tarayıcıda açar: http://127.0.0.1:8765
python run.py --window     # ayrı pencerede (önce: pip install pywebview)
```

## Kullanım

1. **PDF aç** ile veya sürükle-bırak ile slaytı yükleyin.
2. Soldan bir **kademe** seçin:
   | Kademe | Ne kaldırılır |
   |---|---|
   | Orijinal | hiçbir şey |
   | Hafif | zeminler + tekrar eden tema öğeleri; açık renkli metin siyaha döner |
   | Orta | Hafif + eşik üstü büyük görseller ve şekiller |
   | Maksimum | metin dışındaki her şey, tüm metin siyah |
3. İnce ayar: eşik kaydırıcıları, metin rengi, gri tonlama, görsel soldurma, kâğıt başına sayfa (N-up).
4. Sol önizlemede renkli kutular bulunan öğelerdir. Tıkladığınız noktadaki **en küçük** öğe seçilir;
   arkadaki öğeler menünün altında listelenir. *bu sayfada kaldır/koru* veya *tüm sayfalarda kaldır/koru*.
   Mavi nokta manuel kararı gösterir. **Yazı içeren görseller** (tablo, formül, ekran görüntüsü) otomatik
   tanınır (yeşil kutu) ve kademelerde silinmez; soldaki kutucukla kapatılabilir.
5. **Metin seç** aracı (üstte, kısayol `T`): metin kutusuna tıklayın veya sürükleyerek alan seçin.
   - *Tüm sayfalarda kaldır:* sadece **aynı yerde, birebir aynı** metin kaldırılır. Gövdede geçen aynı
     kelimeler etkilenmez (ör. sol üstteki "Informatik 1" gider, "Vorlesung Informatik 1" kalır).
   - *Bu konumdaki metni her sayfada kaldır:* içerik farklı olsa da o alandaki metin kalkar
     (sayfa numaralı alt bilgi gibi). Alan kuralları kesikli kutu olarak görünür; tıklayıp silebilirsiniz.
   - Soldaki "Tekrarlayan metinler (üst/alt bilgi)" kutusu, birebir aynı tekrarları tek tıkla kaldırır.
6. **Kırp** aracı (kısayol `K`, veya görsel menüsünde *Kırp…*): görsele tıklayın, sonra üzerinde sürükleyin.
   - Şekil: *Dörtgen* veya *Serbest* (kement). Mod: *İçini bırak* (sadece çizilen alan basılır) veya *İçini sil*.
   - *Otomatik: fotoğrafları sil* görseldeki fotoğraf/logo bölgelerini bulur ve siler, yazı kalır.
   - *Aynı görsele tüm sayfalarda uygula* aynı görselin her kopyasını kırpar.
   - Soldaki *Görsellerdeki fotoğrafları otomatik kırp* bunu yazı da içeren tüm görsellere uygular.
   - Kırpma kayıpsızdır (görsel yeniden sıkıştırılmaz, PDF kırpma yolu kullanılır); kırpılan görsel kademelerde korunur.
7. **Kelimeler** sekmesi (sağ şerit): tüm slaytlardaki kelimeler ve adetleri. Sıralama düğmesi
   *en çok → en az*, *en az → en çok* ve *A → Z* arasında geçer. Kelimeye tıklamak geçtiği bir sonraki
   sayfaya götürür. Yaygın kelimeler, sayılar ve kaldırılan metinler isteğe bağlı gizlenir; CSV indirilebilir.
8. Sağ şeritte sayfaları silin, döndürün, sıralayın. **Geri al:** Ctrl/Cmd+Z.
9. **Profiller:** ayarları ad vererek kaydedin (`~/.pdf-distiller/profiles/`).
10. **Baskı PDF'ini indir.**

**Güncelleme sonrası:** uygulamayı kapatıp (terminalde Ctrl+C) yeniden başlatın.

Sol üstteki gösterge, örnek sayfaları render edip önce/sonra mürekkep kaplamasını
karşılaştırır; tahminidir.

## Testler ve hız ölçümü

```bash
pip install pytest
python -m pytest -q                 # çekirdek motor testleri
python tests/make_samples.py        # samples/ altına örnek slaytlar
python bench.py                     # 500 sayfalık sentetik deste ile hız testi
python bench.py dosyam.pdf          # kendi dosyanla
```

Referans ölçüm (2 çekirdekli bulut makinesi, 500 sayfa, ~150 bin vektör öğe):
analiz 4,1 sn (görsel içerik analizi dahil), dışa aktarma ~4 sn, tek sayfa önizleme ~25 ms.

## Bilinen sınırlar (prototip)

- Taranmış PDF'lerde (her sayfa tek resim) öğe ayrımı yapılamaz; sadece tüm görsel silinir/soldurulur.
- Gri tonlama gradyanlara (shading) uygulanmaz; gradyanlar kademelerle kaldırılabilir.
- Metin düzenleme yok; silinen metin görünmez yapılır (PDF'te aranabilir kalır, basılmaz). Sayfa sırası değişince yer imleri (outline) çıktıda korunmaz.
- Yazı/fotoğraf ayrımı OCR'sız bir sezgidir: renkli diyagramlar "fotoğraf", çok soluk ekran görüntüleri "yazı" sayılabilir. Emin olmadığınızda elle kırpın veya koruyun.
- Metin rengi kararı satır başlangıç noktasına göre verilir; çok uzun satırlarda nadiren yanılabilir.

Mimari ve geliştirme kuralları için: [ARCHITECTURE.md](ARCHITECTURE.md)
