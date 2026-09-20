# V01 — Yeni tanıtım parçaları ve Mach–Zehnder sahnesi

17 Eylül 2026. Kullanıcının tanıtım önceliğiyle ana planın 02 ve 03 adımları arasına alındı.
Bu teslim görsel prototiptir; gerçek parça montajı veya üretim CAD doğrulaması değildir.

## Teslim

`tools/build_promo_mach_zehnder.py` Blender içinde çalışır. Çıktı dizinini `-- OUTPUT` ile alır.
Yeni mesh üreticisi `optical_alignment_sim/promo_hardware.py`; eski BENCH meshleri kopyalanmaz.

- `01_setup.png`: 13 optikli genişletilmiş Mach–Zehnder genel görünüşü.
- `02_mount_detail.png`: yeni ayna istasyonunun yakın çekimi.
- `promo-mach-zehnder.blend`: düzenlenebilir sahne; simülasyon viewportunda basit gövdeler, renderda ayrıntılı parçalar.
- `new-mirror-assembly.blend`: bir aynanın mount/post/holder/base grubu, Collection asset.
- `part-TableBase.blend`, `part-PH50M.blend`, `part-TR50M.blend`, `part-EO15866.blend`: ayrı Collection assetleri. Destek parçalarında datum nominal gövde merkezi, mount'ta optik merkezidir; geometri mm cinsindedir. Otomatik birim dönüşümü uygulanmaz.
- `report.json`: nominal gövde ölçüleri, optik iz değişmezliği ve sahne tanılaması.

Düzende kaynak, iki lensli genişletici, yarım dalga plakası, polarizör, iki beamsplitter,
iki katlama aynası, örnek/referans pencereleri ve iki çıkış dedektörü vardır.
Renderdaki yeşil çizgiler ışın yolu gösterimidir; havada görünür lazer saçılması modeli değildir.
Çizgi kalınlığı yalnızca görüntü için 0.35 ile ölçeklenir; fiziksel demet parametresi değiştirilmez.
Tüm düzeneğin fiziği bağımsız olarak doğrulanmış değildir. Mevcut tracer kullanılır.

## Kaynak ve doğruluk sınırı

| Parça hedefi | Kullanılan nominal bilgi | Henüz doğrulanmayan ayrıntı |
| --- | --- | --- |
| BA2/M | 50 × 75 × 10 mm zarf, çift slotlu taban | Slot koordinatları, karşı delikler, rölyef ve vida boyları |
| PH50/M | Ø25 × 50 mm gövde, Ø12.8 delik, 43.2 mm delik derinliği | Kilit temas şekli, iç diş profili ve toleranslar |
| TR50/M | Ø12.7 × 50 mm post, M4 üst / M6 alt hedefi | Enine deliğin konumu, iç diş ve vida oturması |
| Edmund 15-866 | 25–25.4 mm optik, 23 mm açıklık, 25.4 mm eksen yüksekliği, 43.5 mm plaka zarfı, ±3.5° ayar, M6 × 0.25 adjuster | Plaka kalınlığı, yaylar, pivot, vida yerleri ve bağlantı yüzeyleri |

Kaynaklar: [Edmund ürün sayfası](https://www.edmundoptics.com/p/25254mm-e-series-kinematic-mount/44292/),
[Thorlabs taban ailesi](https://www.thorlabs.us/newgrouppage9.cfm?objectgroup_id=47),
[Thorlabs post ailesi](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1266),
[distribütörde Thorlabs PH50/M çizimi](https://seltokphotonics.com/upload/iblock/030/030d3c73a9c0ebb353c9d210fdc50875.pdf).
Son çizimin indekslenmiş metni erişilebilirken canlı PDF isteği 404 verdi; görsel çizim kontrolü tamamlanmadı.
Bu nedenle kaynaklı nominal ölçüler bile üretim toleransı doğrulaması anlamına gelmez.

Yeni mount/post/base parçaları iki ayna istasyonunda kullanılır. Holder revizyonu ise 13 istasyonun tamamına uygulanır; diğer istasyonların mount/post/base parçaları önceki katalog geometrisidir.
Güncel özel tabanların 26 masa vidası ızgaraya hizalanır; temas datumları kontrol edilir. Tüm mekanik temasların ve vida yüklerinin doğrulaması henüz yapılmadı.
Diş sarmalları kozmetiktir. Parçaları gerçek montaj eğitimi için onaylayan uyumluluk motoru yoktur.

## MCP üzerinden çalışan ajan için

1. `capabilities` içindeki `mechanical_assembly.available` şu anda false; bağlantı veya uyumluluk API'si varmış gibi çağrı üretme.
2. Varlıkları Blender Collection olarak içe aktar; mm birimini ve datumunu kontrol et. Görsel parça grubunu gerçek bir constraint olarak yorumlama.
3. Yeni render parçalarında `optics.is_optical` false kalmalı. Yalnız asıl ayna ışın izlemeye katılır.
4. `NEW_` parçaları görsel detaydır. `dress` veya render hazırlığını tekrar çalıştırmak bu özel gizleme düzenini sıfırlayabilir; bu durumda sahneyi üretici scriptle yeniden kur.
5. Ayar düğmesini oynatmakla gerçek vida/pivot/yay hareketinin hesaplandığını iddia etme. Bu hareketler sonraki plan adımlarında ele alınacak.
6. `report.json` içindeki `assembly_training_verified: false` durumunu koru. Görsel gerçekçilik veya hata vermeyen tracer mekanik uyumluluk kanıtı değildir.

## Doğrulama

Üretici script iki istasyondaki altı nominal gövde zarfını 0.01 mm eşiğiyle ölçer,
yeni donanımdan önce/sonra ışın izinin aynı olduğunu ve tanılamada BAD bulunmadığını denetler.
Kaydetme ve ayrı varlık dosyalarını yeniden yükleme kontrolü `tools/verify_promo_assets.py` ile yapılır.
Bu kontrol üretilebilirlik, çakışmasız montaj veya mekanik hareket doğrulaması değildir.

Son çalıştırmalar: `promo-new-parts-v2` PASS; `promo-asset-reload` PASS (sahne ve beş asset dosyası yeniden açıldı).

## Post holder revizyonu r2

PH50/M görsel gövdesine tahmini giriş pahı eklendi. Sıkma ucu post yüzeyinde
sonlanır; eski vida-post iç içe geçmesi giderildi. Düğme omzu ve daha kısa dış
gövde eklendi. 5 mm alyan yuvası artık çevrel çapa göre değil karşılıklı düz
yüzlere göre modellenir. Etiket bağımsız holder assetine de dahil edilir.
İlk r2 teslimi iki yeni ayna istasyonu ve `part-PH50M.blend` kapsamındaydı; aşağıdaki r3 bunu tüm sahneye genişletir.

[Üretici katalog kaydı](https://www.thorlabs.com/catalogpages/V21/374.pdf)
yaylı sıkma vidasını ve metrik 5 mm alyan yuvasını belirtir.
İç yay, basınç ucu ve pah ölçüleri üretici CAD'i ile doğrulanmamıştır.

## Tüm istasyonlara uygulama r3

Sahnedeki 13/13 holder artık ortak `post_holder` üreticisini kullanır. Kalan 11
istasyonun tabanları, postları ve optik konumları korunur. Mevcut post tabanını
içeri alabilmek için bu istasyonlarda delik derinliği 46 mm olan özel görsel
varyant kullanılır; üzerinde PH50/M yerine POST HOLDER yazar. Bu varyant bir
üretici SKU'su değildir. İki yeni ayna istasyonu 43.2 mm nominal delik derinliğini korur.
Eski render holder/vida/düğme kopyaları kapatılır; basit simülasyon geometrisi korunur.
Doğrulama 13 holder sayısını, eski render kopyalarının kapalı olmasını, postun
delik tabanına girmemesini, vida-post ayrımını ve her alyan yuvasının 5 mm ölçüsünü denetler.

## Masa bağlantıları r4

13 istasyonun tamamında eski taban/taban kulağı/vida renderları kaldırılıp ortak
`table_base` üreticisi kullanıldı. Her holder'ın alt yüksekliği korunur; özel
slotlu taban yerleşimin iki yanındaki gerçek M6 masa deliklerine ulaşır.
26 ayrı masa vidası, delikli pullar, 5 mm alyan yuvaları ve tabanın altından
holder'a giren merkez vidası modellenir. Alt yüzey rölyefi çevresel temas
yüzeyleri bırakır. Bu parça üretici BA2/M kopyası değildir; CUSTOM etiketlidir.

[Thorlabs montaj tabanı açıklaması](https://www.thorlabs.us/newgrouppage9.cfm?objectgroup_id=47)
M6 bağlantı ve slot yaklaşımı için referanstır; bu sahneye özgü ölçüler üretici
ürününün ölçüleri olarak sunulmaz. Vida uzunluğu, diş toleransı ve yük kapasitesi
mühendislik doğrulaması yapılmadı. `assembly_training_verified` false kalır.

Aktif asset `part-TableBase.blend` dosyasıdır. Önceki `part-BA2M.blend` teslimi
eski bir görsel prototiptir; güncel sahnede kullanılmaz. Yeniden üretim çıktıları
ve MCP yönlendirmelerinde yeni TableBase varlığı kullanılmalıdır.

R4 doğrulama: `promo-table-bases-v1` PASS; `table-bases-verify` PASS (13 taban, 26 ızgaraya hizalı vida, slotlar açık, tabanlar birbirine girmiyor, temas datumları, beş asset yeniden açıldı); `table-bases-units` 32/32 PASS.

## Kısa kenar kanalları r5

Kullanıcı düzeltmesi: uzunlamasına kısa slotlar yerine iki kısa kenarın yanında,
kısa kenarlara paralel geniş kanallar kullanılır. Gövde 48 mm genişliğinde,
ikili slot 36 × 6.6 mm; üstte 42 × 13 mm ve 4 mm derinliğinde karşı kanal
vardır. Pul bu kanalın tabanına oturur. Boy mevcut masa deliklerine göre
70 veya 95 mm olur. Bunlar özel görsel tasarım ölçüleridir. Tüm 13 istasyona
uygulanır. Mesh ışın kontrolleri kanalların enine iki yönde açık olduğunu denetler.

## Kalan istasyonlar r6

`promo_stations.py` eski meshleri kopyalamadan kalan 11 istasyonun render
donanımını yeniden üretir: 1 kaynak gövdesi, 2 lens yuvası, 2 pencere yuvası,
2 döner mount, 2 beamsplitter gövdesi ve 2 dedektör gövdesi. Asıl optik meshler,
portlar ve fizik parametreleri korunur. Bunlar özel görsel modellerdir;
üretici SKU/CAD eşleşmesi veya mekanik uyumluluk garantisi verilmez.

- Lens/pencere: açık yuva, iki sıkma halkası, anahtar çentikleri ve post bağlantısı.
- Döner mount: tırtıllı halka, 5 derece aralıklı çizgiler ve kilit düğmesi. Ölçek geometriktir;
  gerçek rulman veya kilit hareketi modellenmez, animasyonlu mekanik çözüm yoktur.
- Beamsplitter: iç boşluk, dört açık port, çıkarılabilir kapak ve dört vida.
- Kaynak: dış kovan, ön açıklık, arka kapak, iki kelepçe, bağlantı ayağı ve soket.
- Dedektör: sensörün etrafında açık ön gövde, arka kanal detayları, soketler ve ayak.
- Bu 11 istasyonun postları yeni gövdenin altına göre yeniden üretilir; holder/taban
  ve optik koordinatları korunur. Bu postlar katalogdaki belirli uzunluk SKU'ları değildir.

Tasarım referansları: [sıkma halkalı sabit lens yuvaları](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1433&pn=LMRA10),
[ölçekli döner mount](https://www.thorlabs.com/catalogpages/174.pdf),
[dört portlu cube yapısı](https://www.thorlabs.com/catalogpages/Obsolete/2016/CM1-4ER.pdf).
Bu kaynaklar yapısal fikirleri destekler; özgün tasarım ölçülerini doğrulamaz.
SM1 veya başka bir diş standardının fiziksel uyumu modellenmediği için portlara
sırf görünüşleri nedeniyle standarda uyumlu damgası vurulmamalıdır.

Yeni assetler: `part-LaserHead.blend`, `part-LensCell.blend`,
`part-RotationMount.blend`, `part-CubeHousing.blend`, `part-WindowCell.blend`,
`part-DetectorHousing.blend`. Bunlar optik davranış içermeyen render parçalarıdır;
ışın simülasyonu için ana sahnedeki optik nesneler gerekir.
`03_new_stations.png` giriş kolunun ayrıntı görünüşüdür.

MCP ajanı: geometri revizyonu render içindir. Eski BENCH parçaları simülasyonda
kalır; yeni parçalar renderda kullanılır. Sadece optik parametre ayarlamak yeni
mekanik ölçek/düğmelerin fiziksel olarak hareket ettiği anlamına gelmez.

R6 doğrulama: `promo-all-stations-v1` PASS; `new-stations-verify` PASS
(11 istasyon, eski render donanımı kapalı, merkez ışın açıklıkları açık,
11 asset dosyası yeniden yüklendi); `new-stations-units` 32/32 PASS.
Merkez ışın kontrolü demetin tüm kesitinin mekanik apertürlerden kırpılmadan
geçtiğini veya tam mekanik çakışmasızlığı kanıtlamaz.
