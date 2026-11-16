# Mimari

Bu belge projeye sonradan katkı verecek kişiler ve yapay zekâ modelleri içindir.
**Değişiklik yapmadan önce okuyun; değişiklikten sonra `python -m pytest -q` geçmelidir.**

## Katmanlar

```
distill_core/        Arayüzden bağımsız motor (saf Python kütüphanesi)
  model.py           Settings, kademeler (tier_settings), Overrides, PageOp, Element
  interpreter.py     İçerik akışı yorumlayıcısı: analiz + yeniden yazma (KRİTİK)
  classify.py        Öğe sınıfları ve silme kararları (hızlı, tekrar okumaz)
  images.py          Kalan görselleri gri / soluk yapma
  imgfeat.py         Görsel içerik analizi: yazı skoru, fotoğraf bölgeleri (döşeme sezgisi, OCR yok)
  pageops.py         Sayfa silme/sıralama/döndürme, N-up
  engine.py          DistillDocument: dış dünyaya açılan tek API
app/
  server.py          FastAPI, sadece 127.0.0.1. İş mantığı içermez.
  static/            index.html + style.css + app.js (derleme adımı yok)
run.py               Sunucuyu başlatır; --window ile pywebview penceresi
tests/               make_samples.py (sentetik slaytlar), test_core.py
profiles/            Hazır profiller (JSON). Kullanıcı profilleri: ~/.pdf-distiller/profiles
```

Yeni arayüz (masaüstü uygulaması, web servisi, toplu işlem) eklemek = `DistillDocument`'i çağırmak.
Motoru arayüze bağımlı hale getirmeyin.

## Akış

1. `analyze()` her sayfanın içerik akışını **render etmeden** dolaşır ve her görsel öğeyi
   (`image`, `fill`, `stroke`, `shading`) kutu, alan oranı, parlaklık ve **imza** ile kaydeder.
   ≥120 sayfada çok işlemcili çalışır.
2. `decide(settings, overrides)` sınıflandırır: `white`, `background`, `repeated`, `large`, `other`
   ve her sayfa için silinecek öğe kimliklerini (`"<sayfa>-<sıra>"`) üretir. Sonuç önbelleğe alınır.
3. `distill_pages()` aynı yorumlayıcıyı yeniden yazma modunda çalıştırır ve kimliği listede olan
   öğeleri çıkarır.

## Kritik kurallar

- **Kimlik tutarlılığı:** Analiz ve yeniden yazma aynı `PageWalker._walk` kodunu kullanır. Öğe sayacı
  her iki geçişte aynı sırayla artmalıdır. Bir öğe türünü sayarken diğerinde atlarsanız yanlış öğe
  silinir. `test_ids_are_stable_between_passes` bunu yakalar.
- **Yol silme = boyamayı `n` ile değiştirmek.** Yol inşa komutları ve kırpma (`W`) korunur; aksi halde
  kırpma bozulur ve gizli içerik görünür hale gelebilir.
- **Beyaz dolgular (parlaklık > 0.95) asla silinmez.** Mürekkep harcamazlar; silmek altlarını açar.
- **Form XObject'ler paylaşımlıdır.** Değişen bir form yerinde değiştirilmez; yeni kopya oluşturulur
  ve içerik özetine göre önbelleklenir (aynı tema 500 sayfada tek kopya). Orijinal forma dokunmayın.
- **Metin rengi:** metin komutlarındaki renk değiştirilmez. Her gösterim komutundan (`Tj/TJ/'/"`) önce
  gerekirse `0 g` eklenir, sonra orijinal renk geri kurulur (`Color.restore`). Arkasında korunmuş
  koyu bir zemin varsa (backdrops) açık renkli metin olduğu gibi kalır.
- **Gri tonlama:** `rg/k/sc/scn` sayısal renkleri `g`'ye çevrilir; `Color.dirty` bayrağı renk uzayı
  orijinalden saptığında sonraki `sc/scn` öncesi `cs` komutunun yeniden yazılmasını sağlar.
- **Metin kutuları:** her `Tj/TJ/'/"` yazı tipi genişlikleriyle (`FontInfo`) ölçülür; aynı taban
  çizgisinde yan yana duran ardışık parçalar tek kutu olur (`_text_piece`). Kimlik `"<sayfa>-t<sıra>"`,
  grafik sayacından ayrıdır. İmza = içerik özeti (yazı tipi + boyut + ham baytlar) + başlangıç konumu.
- **Metin silme = görünmez yapma** (`3 Tr` … orijinal `Tr`). Metni komut akışından çıkarmak aynı
  satırdaki sonraki parçaları kaydırırdı; görünmez metin ilerlemeyi korur.
- **Kademeler metni asla silmez.** Metin sadece seçimle (`elements`, `signatures`, `regions`) veya
  `remove_repeated_text` ayarıyla silinir. Alan kuralları (`regions`) görüntü koordinatlarındadır ve
  sadece metin kutularına uygulanır.
- **Kırpma = PDF kırpma yolu.** Görselin `Do` komutu `q <yol> W n … Do Q` ile sarılır; görsel yeniden
  kodlanmaz. Çokgenler görselin birim karesinde tutulur (`decide_full` → `clips`), böylece "tüm sayfalarda"
  aynı görselin farklı konumlu kopyalarına da doğru uygulanır. *keep* çokgenleri aynı yöne çevrilip
  birleştirilir (nonzero); her *erase* çokgeni ayrı bir even-odd kırpmadır (kesişimleri = birleşimin
  tümleyeni). Kullanıcı kırpmaları görüntü koordinatında gelir, `view_to_user` + ters CTM ile çevrilir.
- **Yazılı görsel koruması:** `imgfeat` sayfa alanının %2'sinden büyük görselleri analizde bir kez
  (imzaya göre) inceler; metin skoru ≥ 0.6 olanlar `text_image` sınıfı alır ve kademelerde silinmez.
- **Arayüzde seçim** DOM sırasına değil, tıklanan noktadaki en küçük öğeye göre yapılır (`hitsAt`).
- **Kelime sayacı** metni pdfium'dan alır (yazı tipi kodlamalarını o çözer); kaldırılan kutuların metni
  sayımdan düşülür.
- **pdfium iş parçacığı güvenli değildir:** her render `PDFIUM_LOCK` altında.

## Lisans notu

PyMuPDF bilerek kullanılmadı (AGPL; ticari/web ürününde kaynak açma veya ticari lisans gerektirir).
Kullanılanlar: pikepdf (MPL-2.0), pypdfium2 (Apache-2.0/BSD-3), Pillow, numpy, FastAPI. Yeni bağımlılık
eklerken lisansı kontrol edin.

## Küçük modellerle çalışırken

- Arayüz değişikliği → sadece `app/static/*`. Motor dosyalarına dokunmayın.
- Yeni ayar → `Settings` alanı + `classify.py` kuralı + `index.html` kontrolü (`data-s="<alan>"`
  ile otomatik bağlanır) + test.
- `interpreter.py` değişiklikleri en güçlü modelle yapılmalı ve yeni test eklenmeli.

## Yol haritası

- Aşama 2: kırpma için ön izlemede tutamaçlarla düzenleme, alan seçimini görsellere de genişletme, sürükle-bırak sayfa sıralama, sayfa kırpma, PDF birleştirme/bölme, gerçek PDF'lerle
  sınıflandırma ayarı, öğeleri gruplayarak seçme (alan seçimi).
- Aşama 3: toplu işlem (klasör + profil), pywebview/Tauri ile paketlenmiş uygulama (.app / .exe),
  web sürümü (aynı API, dosya boyutu ve oturum sınırlarıyla).
