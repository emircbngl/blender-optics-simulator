# Gerçek parçalarla optomekanik montaj pratiği — yürütme planı

Durum: 01, 02, 03 ve 04 (04a + 04b) TAMAMLANDI. V01 ilk görsel prototip teslimi hazır; nihai mekanik doğrulama açık. Ana sırada sonraki adım 05.
Kullanıcı talimatı: önce Astra ile liste; sonraki oturumlarda sırayla uygula. Bir adım doğrulanmadan diğerine geçme; geçiş için tekrar onay isteme. Paralel uygulama yok. Bu dosya devam oturumlarının başlangıç noktasıdır.

## Hedef ve mevcut durum

Araştırmacı gerçek laboratuvar parçalarını seçebilmeli, uyumluluğunu denetlemeli, montaj/söküm sırasını uygulamalı ve aynı düzenekte optik simülasyon yapabilmeli. Basit simülasyon görünümü ile ayrıntılı render aynı mekanik veriyi kullanmalı. Basit görünüm gerekli bağlantıları veya çarpışma kontrollerini ortadan kaldırmaz.

Başlangıç commit: 298aa78c08b0bb6b8aa0f9c4595fba0e30429d4e. Mevcut 33 preset yaklaşık görsel modellerdir. `hardware_catalog.py` ürün ailesi/çap bilgisi; `hardware_shapes.py`, `optomech.py` prosedürel donanım; `mounts.py` ayar hareketleri; `hardware_render.py` görsel ayrıntılar üretir. MCP `optics_api.py` → `bridge.py` → `mcp/optics_mcp_server.py` zincirini kullanır. `capabilities()`, `get_state()`, `set_mount()` ve `mcp/AGENT_GUIDE.md` vardır. Bunlar henüz doğrulanmış parça bağlantılarıyla montaj eğitimi sunulduğunun kanıtı değildir.

## Değişmez kurallar

- Her ürün: üretici + tam parça numarası + metrik/inç varyantı + belge revizyonu. Aile adı ürün kimliği sayılmaz.
- Her kritik ölçü: kaynak URL/belge/sayfa/çizim, tarih, birim, varsa tolerans. 01 ölçü başına ölçüm yöntemini ve model hata eşiğini belirler; eşik kaynağın çözünürlüğü ve kullanım ihtiyacına dayanır, mesh sonucuna bakarak gevşetilmez. Model sayısal hatası ile üretim toleransı ayrı alanlardır. Diş sınıfı/üretim toleransı bilinmiyorsa nominal standart eşleşmesi raporlanabilir fakat gerçek geçme garantisi verilmez; ilgili hassas geçme sonucu unknown kalır. Dış görünüşten iç mekanizma, tolerans, tork, yay sabiti veya yük kapasitesi uydurma.
- Ayrı kanıt seviyeleri: görsel yaklaşık / nominal ölçüler doğrulanmış / bağlantı doğrulanmış / montaj pratiği doğrulanmış. Son seviye fiziksel eşleştirme veya açıkça belirtilen bağımsız montaj kanıtı ister. Kaynak çizime uygunluk, fiziksel ürünün mikrometrik kopyası demek değildir.
- Her mevcut preset envanterde sonuca bağlanır: doğrulanmış ürünle değiştirildi veya açıkça yaklaşık kaldı. Yaklaşık kalanlar katı montaj eğitimi kataloğuna girmez; sessizce silinmez.
- Optik portlarla mekanik bağlantı noktaları ayrı kimliklere sahiptir. Taşıyıcı parçalar ışın izleyicide optik yüzeye dönüşmez; mekanik engelleme ayrı kontrol edilir.
- Uyumluluk: `compatible`, `incompatible`, `unknown`, `adapter_required`. Bilinmeyen veri otomatik olarak uygun sayılmaz. Uyumlu arayüz, bütün düzeneğin monte edilebilir olduğunu tek başına kanıtlamaz.
- Kaynak/model sürümü sahneye ve assete kaydedilir. Eski sahneler açık göç işlemiyle taşınır; yeniden açıldığında boyutları sessizce değişmez.
- Yük/deformasyon/sürtünme/tork hissi ancak doğrulanmış veri ve model varsa hesaplanır. İlk hedef geometrik ve kinematik montaj pratiğidir; fiziksel dokunma deneyimi iddiası yok.

## Oturum protokolü ve bütçe

Yalnızca ilk tamamlanmamış adım üzerinde çalış. Her devamda bu planı, git durumunu ve ilgili adımın belgelerini oku. Başkasının değişikliklerini koru. Her adım tek inceleme birimi olarak hazırlanır; maliyet büyürse aynı adımı 06a/06b gibi böl, sonraki aileye atlama. Araştırmayı o adımın parça ailesiyle sınırla; toplu CAD/render üretimini sona bırak. Testi ancak değişiklik/failure gerektiriyorsa tekrarla.

Astra tasarım ve aşama kapanış değerlendirmesini yapar; ayrıca paralel model/ajan uygulaması başlatılmaz. Bir adımın tamamlanma koşulu sağlandığında durumu kaydet ve yetkili devam kapsamında sıradakine geç; onay sorusu ekleme. Oturum kapanması, kendiliğinden yeni görev veya zamanlanmış çalışma başlatmaz. Kullanıcı sonraki oturumda “devam” dediğinde aynı sıradan sürdür.

Veri eksiği politikası: 01 bir envanter adımı olduğu için açık eksiklerle tamamlanabilir; bu, ürünü doğrulanmış saymaz. Sonraki adımın ihtiyaç duyduğu kanıt eksikse o adım kapanmaz ve zincir ilerlemez. 05–09 için eğitim dışı etiketlemek yalnız geçici korumadır; zorunlu aileyi tamamlanmış sayma veya sessiz kapsam daraltma yolu değildir. Veri bulunamazsa aynı adımda kaynak edinme/ölçüm ihtiyacını kaydet; bağımlı işi başlatma.

GitHub'a yayın bu planın kapsamı değildir. Yerel değişiklik/diff ve test kanıtı hazırlanır. Plan hazırlanırken gh kimlik doğrulaması kullanılamadı; yerel uygulamayı engellemez. Push/release istenirse ilgili yayın becerisi uygulanır.

Bağımlılık zinciri: 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12.

## 01 — Ürün ve teknik belge envanteri

Bağlam: 33 presetin bir kısmı yalnızca genel aile. Gerçek ürün kimlikleri belirlenmeden ölçülü modeller üretilemez.
Dosyalar: `hardware_catalog.py`, `presets.py`, `docs/realistic-hardware.md`; yeni `docs/mechanics/product-evidence.md` ve makine okunur kanıt kataloğu.
İş: tüm 33 girdiyi eşleştir; post/holder/base/vida/retainer/adapter gibi alt parçaları BOM olarak çıkar. Her aile için ilk doğrulanacak gerçek ürün ve varyantları sabitle. Üretici çizim/CAD/kılavuz bağlantıları ve yeniden dağıtım şartlarını kaydet; CAD erişilemezse ölçülü çizimle özgün model üretme yolunu belirt. Kanıt yoksa engeli yaz.
Kontrol/çıkış: 33/33 envanter sonucu; hiçbir tam parça numarası tahmine dayanmıyor; her aile için belge veya açık veri eksiği. Ürün bazlı kritik ölçü kontrol listesi hazır.
Geri dönüş: yalnızca envanter dosyalarını geri al; sahneye dokunma.

## 02 — Parça, bağlantı ve kanıt veri modeli

Bağlam: 01 envanteri girdi. Mevcut preset/optik verileri korunacak; mekanik yapı ayrı temsil edilecek.
Dosyalar: yeni `mechanical_catalog.py`, `mechanical_interfaces.py`; `properties.py`, `optics_api.py`, `docs/mechanics/schema.md`.
İş: bağlantı yerel koordinat sistemi, yön/eksen, iç/dış diş, çap/adım/form/el yönü, kullanılabilir kavrama derinliği, delik deseni, oturma yüzeyi, optic kalınlık aralığı, kilit/alet erişimi, hareket ve kanıt alanlarını tanımla. Şema sürümü ve eski sahne göç kuralları yaz. Yeni MCP çağrılarının sözleşmesini taslak olarak tanımla; uygulanmayan çağrıları capabilities içinde kullanılabilir gösterme.
Kontrol/çıkış: şema geçerli/geçersiz örnekleri; bilinmeyen değer korunuyor; mm/inç normalizasyonu; kimlik ve kaynak revizyonu save/load boyunca aynı; eski presetler açılıyor.
Geri dönüş: yeni şemayı devre dışı bırak; eski veriyle açılma korunur.

## 03 — Uyumluluk motoru

Bağlam: 02 bağlantı verisi hazır. Görsel çakışma veya yalnızca çap eşitliği uyumluluk kanıtı değildir.
Dosyalar: yeni `mechanical_compatibility.py`, `tests/test_mechanical_compatibility.py`; `optics_api.py` ve MCP okuma araçları.
İş: metrik/inç vida ayrımı, SM aileleri, cage/rail bağlantıları, post-holder çapı, optic kalınlığı, vida derinliği/dibe vurma ve adaptör zincirlerini değerlendir. Sonuçta gerekçe, dayanak, eksik bilgi ve gereken gerçek adaptör kimliği dön. `inspect_part`, `list_interfaces`, `check_compatibility` aday adlarıdır; gerçek API adları bu adımda sabitlenir.
Kontrol/çıkış: kaynaklı olumlu/olumsuz/bilinmeyen/adaptörlü örnekler; yanlış standart reddediliyor; adaptör döngüleri engelleniyor; okuma araçları sahneyi değiştirmiyor; MCP/API paritesi geçiyor.
Geri dönüş: yeni katı uyum yolunu kapat; eski preset uygulaması korunur.

## 04 — Montaj grafiği ve montaj işlemleri

Bölme (22 Eylül 2026): bu adım tek inceleme birimi için büyük olduğundan bütçe kuralı uyarınca ikiye
ayrıldı. **04a — grafik, durumlar ve kapılar** (geometri yok): parça/bağlantı grafiği, durum makinesi,
dönüşüm sahipliği ormanı ile fiziksel grafiğin ayrılması, kilitli hareket reddi, söküm sırası, dry_run,
atomik yazma, save/reload ve Dress Bench ayrımı. **04b — montaj geometrisi**: bağlantı çerçevelerinden
yerleştirme, alt montaj dönüşüm aktarımı, kapalı çevrimde poz/kısıt tutarlılığı veya gerekçeli
çözümsüzlük, gerçek geometride Dress Bench/elle montaj sahipliği ve render/yeniden dress korunması.
Kapsam daraltma değildir: 04, 04b tamamlanmadan kapanmaz ve 05'e geçilmez.

Bağlam: 03 motoru kararı verir; mevcut BENCH sahipliği gerçek sabitlenmiş bağlantı anlamına gelmez.
Dosyalar: yeni `mechanical_assembly.py`, `tests/test_mechanical_assembly.py`; `mounts.py`, `optomech.py`, `optics_api.py`.
İş: parça/bağlantı grafiği; geçici hizalama, yerleştirme, vidalama, kilitleme, açma ve sökme durumları; sabitlemeden önce/sonra izinli hareketler. Dönüşüm sahipliği ağacını fiziksel bağlantı grafiğinden ayır: ilkinde döngü olamaz; ikincisi cage gibi çok noktalı bağlantı ve kapalı çevrimleri destekler. Bağlantı dönüşümlerinden tüm alt montajı taşı; kapalı çevrimlerde poz/kısıt tutarlılığını çöz veya gerekçeli çözümsüzlük döndür. `dry_run`, atomik hata geri alma, Undo ve tekrar çağrıda kopya üretmeme sağla. Otomatik Dress Bench ile elle montaj sahipliğini ayır; render/yeniden dress elle montajı silmesin.
Kontrol/çıkış: uyumsuz bağlama hiçbir kısmi değişiklik bırakmıyor; dönüşüm ağacında döngü/çoklu ebeveyn reddi, fiziksel grafikte geçerli kapalı çevrim ve çoklu bağlantı kabulü, çelişkili kısıtların reddi; kilitli hareket reddi; söküm sırası; save/reload ve Undo; render ve dress montajı koruyor.
Geri dönüş: manuel montaj modu feature flag; sahne yedeği/göç sürümüyle eski yol.

## 05 — Breadboard, taban, post, holder ve bağlantı elemanları

Bağlam: 04 montaj motoru hazır. Bu aile diğer tüm montajların taşıyıcı temelidir.
Dosyalar: `optomech.py`, `hardware_shapes.py`, `hardware_render.py`, mekanik katalog; yeni aile testleri.
İş: 01'de seçilen gerçek tablalar, delik düzeni/diş derinliği, taban slotları, post-holder geçmesi, sıkma vidası ve gerçek bağlantı vidalarını üret. Vida ucu/kavrama ve post giriş aralığını doğrula. Masa→taban→holder→post alt montajını kur/sök.
Kontrol/çıkış: çizimdeki kritik ölçüler bağımsız mesh ölçümüyle karşılaştırıldı; yanlış vida ve yanlış post reddediliyor; alt montaj sabitlenmeden kilitli sayılmıyor; basit/render geometri aynı arayüzlerde buluşuyor.
Geri dönüş: aile bazında eski görsel jeneratör; mevcut sahneler yerinde kalır.

## 06 — Sabit optik hücreleri ve kinematik ayna mountları

Bağlam: 05 taşıyıcı zinciri doğrulanmış. Lens/mirror oturması yalnızca yüzey yakınlığı olamaz.
Dosyalar: `hardware_shapes.py`, `optomech.py`, `mounts.py`, aile katalog ve testleri.
İş: gerçek lens hücreleri, retaining ring/omuz/set screw; KM/KS/POLARIS benzeri mevcut ailelerin 01 eşleşmeleri. Ön/arka plaka, gerçek pivot/temas noktaları ve belgelenmiş ayar hareketi. Kalınlık/kenar tutma ve optiğin montaj yönü.
Kontrol/çıkış: takılabilen ve takılamayan optic örnekleri; kalınlık sınırları; ayar sırasında bağlantıların korunması; belgesiz yay/vida değerleri fiziksel gerçek diye kullanılmıyor; aile kapsama tablosu kapanmış.
Geri dönüş: yeni ürün kimliklerini devre dışı bırak; eski presetleri göç ettirmeden koru.

## 07 — Dönüş, flip, gimbal ve öteleme mekanizmaları

Bağlam: 06 statik tutucular tamam. Hareket sınırları ve kilitler gerçek ürün verisinden türemeli.
Dosyalar: `mounts.py`, `hardware_shapes.py`, `optomech.py`, aile testleri.
İş: rotation/flip/gimbal/XY/XYZ ürünlerini ayrı alt montajlar olarak modelle. Vida ilerlemesi/ayar aktarımı yalnızca belgeli olduğunda kullan; kilit, stop, mafsal ekseni ve alt montaj hareketi tanımla.
Kontrol/çıkış: uç konumlar ve ara hareketler; kilit açık/kapalı davranışı; belgeli hareket aralığı; optik portların doğru dönüşümü; zorunlu ailede kaynak yoksa adım açık kalır ve ürün geçici olarak eğitim dışı işaretlenir.
Geri dönüş: ürün bazlı sürüm ve eski ayar modeli korunur.

## 08 — Cage, lens tüpleri ve adaptörler

Bağlam: 07 hareketli yapılar hazır. Cage çubuk aralığı ile lens tüpü dişi farklı uyumluluk alanlarıdır.
Dosyalar: `optomech.py`, mekanik katalog/uyumluluk motoru ve aile testleri.
İş: seçilmiş 16/30/60 cage plakaları/çubukları/kilitleri; SM05/SM1/SM2 tüpler, halkalar ve gerçek geçiş adaptörleri. Çubuk giriş yönü, kapalı kafese sonradan parça takılabilirliği, lenslerin içerideki sırası ve erişimi.
Kontrol/çıkış: yanlış cage ve tüp birleşimleri reddediliyor; adaptörlü doğru birleşim geçiyor; içerideki halkaya alet erişimi ve söküm sırası; bütün varyantlar katalogda sonuçlandırılmış.
Geri dönüş: eski cage/tube sahnelerini korunmuş şemada aç.

## 09 — Raylar ve özel tutucular

Bağlam: 08 standart modüler aileler tamam. Mevcut ray/kamera/kaynak/iris/prizma aileleri yaklaşık bırakılarak gözden kaçmayacak.
Dosyalar: `optomech.py`, `hardware_catalog.py`, `hardware_shapes.py`, aile testleri.
İş: RLA/X95 eşleşmeleri, ray arabaları/stoperler, kaynak/V-clamp, kamera, iris ve prizma platformlarının gerçek SKU'ları. Sensör/optik eksen ofseti, bağlama alanı ve ray arayüzü. Belirsiz kameraya evrensel uyum varsayma.
Kontrol/çıkış: zorunlu ailelerin tamamı doğrulanmış; gerekçeli veri eksiği varsa adım kapanmaz; birbirine benzeyen farklı raylar uygun sayılmıyor; gerçek destek zinciri ve optik yükseklik ölçülüyor.
Geri dönüş: aile bazlı sürüm seçimi; yaklaşık ürünler açık etiketle korunur.

## 10 — Takma yolu, çarpışma ve montaj pratiği denetimi

Bağlam: 05–09 parça modelleri var. Nihai pozun boş olması parçanın oraya sokulabildiğini kanıtlamaz.
Dosyalar: yeni `mechanical_validation.py`, montaj motoru, doğrulama testleri.
İş: yerleştirme/sökme boyunca süpürülen hacim kontrolü; alet ve parmak erişim zarfı (yaklaşık olanı belirt); temas izni olan yüzeyler; desteksiz alt montaj, sıkılmamış vida ve kapatılmış erişim. Diş geometrisinde ağır gerçek zamanlı temas yerine doğrulanmış bağlantı kuralları ve hafif çarpışma temsili kullan. Desteklenen doğrusal/dönel yerleştirme hareketlerini, azami yol hatasını ve tespit edilebilir en küçük engel/boşluk sınırını test öncesi tanımla. Sürekli çarpışma denetimi veya muhafazakâr süpürme sınırları kullan; yalnız sabit aralıklı örneklerle geçer kararı verme. Sınırın altında kalan veya desteklenmeyen hareketlerde unknown döndür.
Kontrol/çıkış: son konum uygun fakat giriş yolu kapalı örnek reddediliyor; tanımlanmış çözünürlük içindeki ince engeller öteleme ve dönmede iki örnek arasına konulduğunda da yakalanıyor; çözünürlük dışı örnek unknown; izinli temas çarpışma sayılmıyor; hata gerçek parçayı/işlemi gösteriyor; performans aynı test sahnesinde öncesi/sonrası ölçülüyor.
Geri dönüş: yeni doğrulama katmanı kapatılabilir; eğitim doğrulaması yokken geçer sonucu üretme.

## 11 — İnsan arayüzü ve MCP montaj rehberi

Bağlam: 10 montaj kararları güvenilir. İnsan ve yapay zekâ aynı motoru kullanmalı; görselden uyumluluk tahmin etmemeli.
Dosyalar: `ui.py`, `optics_api.py`, `bridge.py`, `mcp/optics_mcp_server.py`, `mcp/agent_patterns.py`, `mcp/AGENT_GUIDE.md`, `docs/CAPABILITIES.md`.
İş: parça seç → bağlantı seç → uygun parça/adaptör → yerleştir → sabitle → doğrula akışı. Otomatik kurulum ve elle pratik modlarını belirgin ayır. MCP'de katalog/kanıt/bağlantı/uyumluluk okumaları, montaj planı, dry-run, adım uygulama, kilitle/sök ve doğrulama araçlarını sun. Rehber: capabilities → mevcut durum → kanıtlı parça → uyum → sıra/erişim → dry-run → uygula → tekrar oku → mekanik doğrula → optik izleme. Geometriyi serbestçe taşıyarak katı mod kurallarını aşan işlemleri geçersiz durum olarak işaretle. Eksik bilgi, değişen sahne sürümü ve kısmi başarısızlık örneklerini anlat.
Kontrol/çıkış: UI tıklama yolu ile MCP aynı montaj sonucunu üretiyor; bilinmeyen uyumda ajan işlem yapmıyor; API/bridge whitelist/MCP/rehber paritesi; yeni bağlanan ajan yalnız yayımlanan araçlarla örnek kurulumu tamamlayabiliyor.
Geri dönüş: yeni panel/tool grubu capability sürümüyle devre dışı; eski optik API korunur.

## 12 — Laboratuvar senaryoları, tüm ürün denetimi ve teslim

Bağlam: 11 insan/ajan akışları var. Bağımsız ölçüm ve montaj kanıtı olmadan yalnız kod testleri “birebir” iddiasını doğrulamaz.
Dosyalar: yeni montaj senaryoları/testleri; `tools/build_hardware_assets.py`, katalog sayfası, docs ve teslim raporu.
İş: post üzerinde ayna, cage/tüp lens treni, raylı düzenek ve kilitli hareket mekanizması için BOM, sıra, kasıtlı uyumsuz parçalar ve söküm görevleri. Çizimden bağımsız alınmış referans ölçülerle geometri kıyasla; üretici montaj yönergesi/video veya gerçek düzenekle bağımsız montaj kanıtını kaydet. Bu kanıt olmadan senaryo montaj pratiği doğrulanmış seviyesine çıkamaz; geometrik/kinematik doğrulama olarak kalır ve doğrulanmış eğitim teslimi kapanmaz. 33 eski preset + yeni gerçek alt parçaları yeniden üret; eski dosyaları sessizce değiştirmeyen migration testi. Basit/detaylı görüntüler aynı montajın görünümü olsun.
Kontrol/çıkış: tüm ürünler kapsama/kanıt tablosunda; eğitim kataloğundakilerin kritik ölçüleri belirlenmiş hata eşikleri içinde, bağlantıları ve bağımsız montaj senaryoları doğrulanmış; çözülemeyen veri eksikleri görünür. Tam optik regresyon, units, mesh, render izolasyonu, montaj/UI/MCP testleri, asset reload, ZIP doğrulaması ve release consistency geçiyor. Son rapor hangi doğruluğun kanıtlandığını açıkça söyler; eksik fiziksel doğrulama gizlenmez.
Geri dönüş: önceki asset/eklenti paketi korunur; sürümlü yeni teslim.

## Ortak doğrulama komutları

Blender testleri `python3 tools/job.py run <benzersiz-ad> -- /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python-exit-code 1 --python <test>` ile çalışır. `python3 tools/job.py wait <ad> --timeout 50` sonucunu bekle; çalışan işi tamamlandı sayma. Adı önerilen yeni testler önce ilgili adımda oluşturulacak; mevcutmuş gibi çalıştırma.

Mevcut regresyonlar: `tests/test_optics.py`, `tests/test_units.py`, `tests/test_hardware_catalog.py`, `tests/test_hardware_render.py`, `tests/test_mesh_health.py`. Her adımın etkilediği testleri çalıştır; tamamında tam suite tekrarlama. Teslimde `python3 tools/check_release_consistency.py` ve `git diff --check` zorunlu.

## Kaynak başlangıç noktaları

Bu bağlantılar araştırma girişidir; ürün bazlı ölçü onayı henüz verilmedi (16 Eylül 2026).
- Post/holder aileleri: https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1266
- Cage plakaları: https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=2273&pn=CP33
- Sabit lens tutucuları ve diş tabloları: https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1433&pn=LMRA10
- Dönüş mekanizmaları: https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=246
- Mevcut kaynak/sınırlar: `docs/realistic-hardware.md`.

## Devam kaydı

- Plan: hazır; Astra bağımsız incelemesindeki 5 bulgu işlendi (veri eksikliği kapısı, fiziksel grafik çevrimleri, bağımsız montaj kanıtı, sayısal ölçü eşikleri, hareket doğrulama sınırları). Kaynak kod/asset değişikliği yok.
- 01: tamamlandı (16 Eylül 2026). 33/33 preset, 30 kaynakta adlandırılmış hedef, 3 kimlik/kanıt açığı; 27 kaynak ve 10 destek parçası adayı. Ölçü/uyum/model doğrulaması henüz yapılmadı.
- 02: tamamlandı. mechanical_catalog.py / mechanical_interfaces.py, Object.mechanics snapshot, capabilities durum bildirimi ve docs/mechanics/schema.md eklendi. mechanical-schema-v2 PASS (16 geçersiz örnek, save/reload, null/birim, atomik yazma, optik yalıtım); mechanical-schema-units 32/32 PASS.
- 03: tamamlandı (21 Eylül 2026). `mechanical_compatibility.py` + `tests/test_mechanical_compatibility.py` (27/27) + `docs/mechanics/compatibility.md`. API adları sabitlendi: `inspect_part`, `list_interfaces`, `check_compatibility`; aynı üç araç MCP'de de var. Kararlar: uyumlu/uyumsuz/bilinmiyor/adaptör gerekli; eksik alan asla geçer sayılmaz ve `missing` içinde adlandırılır; kanıtsız kural olumlu sonuç veremez; beyan edilmemiş boşluk "bilinmiyor"dur; adaptör zinciri en kısa yoldan aranır, her parça bir kez kullanılır (döngü yok) ve kimliksiz adaptörün eksikliği bildirilir. Kaynaklı örnekler: 4 mm SR çubuğu 6 mm LCP01 deliğinde reddedildi, 1/4-80 adjuster ile 8-32 vidası ayrıldı, TRF90'ın 5 mm giriş sınırı dibe vurmayı yakaladı. Şema v1'de profil olmadığı için dovetail/clamp ve düzlem oturması bilinmiyor kalıyor; ölçü doğrulaması, tolerans yığını ve montaj sırası hâlâ açık.
- 04a: tamamlandı (22 Eylül 2026). `mechanical_assembly.py` (bpy'siz) + `tests/test_mechanical_assembly.py` (61/61) + `docs/mechanics/assembly.md` + `Scene.mechanics` (graph_json, manual_assembly) + CI adımı. API adları sabitlendi: `enable_manual_assembly`, `join_parts`, `set_joint_state`, `separate_parts`, `assembly_graph`, `disassembly_plan`, `permitted_motions`; MCP araçları eklenmedi (aşama 11). Kararlar: yalnız 03'ün `compatible` kararı bağlantıya dönüşür, diğer üç karar gerekçesiyle reddedilir ve hiçbir şey yazılmaz; bir arayüz tek bağlantı taşır; aynı çağrı ikinci kez kopya üretmez; dönüşüm sahipliği orman kalır (döngü/ikinci ebeveyn reddedilir), taşıyamayan bağlantı fiziksel bağlantı olarak kaydedilir ve kapalı çevrim böyle kabul edilir; durumlar aligned→seated→fastened→locked tek adım ilerler, atlama reddedilir; `locked` yalnız arayüzü kilit beyan ediyorsa mümkündür; fastened arayüzün hareketini tutar, locked reddeder; söküm ters sırada ve `release`/`full` olarak dönülür; grafik sahnede tek JSON dizesidir, tam doğrulama sonrası tek yazma yapılır; parçalar `instance_id` ile adreslenir, kopyalanmış kayıt reddedilir, silinen parça `dangling` görünür; `BENCH_` ad alanı Dress Bench'e aittir (strip o adı silmektedir, bu yüzden oraya bağlantı reddedilir). Geometri yok: bağlamak yerleştirmez, poz aktarılmaz, çevrim çözülmez; `available: false` sürüyor. Bulgu: arka planda `bpy.ops.ed.undo` poll edilemediği için undo ADIMI headless sınanamadı; sınanan şey bir işlemin tek datablock üzerinde tek özellik yazması.
- 04b: tamamlandı (22 Eylül 2026). `mechanical_assembly.py` içine yerleştirme matematiği (kuaternion→rotasyon, rijit dönüşüm çarpımı/tersi, `seating_pose`, `seating_residual`, `placement_limits`), `optics_api._seat`/`_unseat`, `set_joint_state`'e `clock_deg`/`insertion_mm`/`tolerance_mm`/`tolerance_deg`, `optomech.manually_mounted` + `dress` filtresi, `tests/test_mechanical_assembly_geometry.py` (44/44), CI adımı. Sabitlenen sözleşme: oturtma iki beyan edilmiş arayüz çerçevesini ÇAKIŞIK ve TERS YÖNLÜ yapar (+Z dışa bakan bağlantı ekseni/yüzey normali); datumun ötesindeki derinlik yalnız açık `insertion_mm`'dir ve beyan edilen insertion_min/max'a karşı denetlenir; saatleme açık açıdır çünkü şema v1'de +X dışında saatleme datumu yok; çerçevesi null olan arayüz yerleştirilemez ve alan adıyla reddedilir. Taşıyan bağlantı Blender parent'ı kurar, böylece alt montaj tek gövde gibi taşınır; `aligned`'a dönüş parçayı bulunduğu yerde serbest bırakır. Kapalı çevrimi kapatan bağlantı hiçbir şeyi taşımaz: beyan edilen geometrinin kapanıp kapanmadığını ÖLÇER (gap/eksen/saatleme artığı), tolerans kullanıcı tarafından adlandırılmalıdır (şema v1 çerçeve toleransı belirtmez) ve aşılırsa `unsolvable: true` ile reddedilir — hiçbir parça uydurulmuş poza itilmez. Dress Bench kayıtlı bir mounta oturmuş optiği artık atlıyor (yoksa gerçek postun altına uydurma ikinci post koyuyordu); strip/yeniden dress elle yerleştirmeyi ve parent'ı bozmuyor. Oturtma mm-only kapısına tabi. Açık: envanterde hiç kaynaklı arayüz çerçevesi yok, bu yüzden bugün gerçek bir parça kanıttan yerleştirilemiyor; çarpışma, alet erişimi, tork ve yük hâlâ 07/10.
- 04: 04a + 04b ile TAMAMLANDI. Sıradaki adım 05.
- 05–12: bekliyor (sıradaki 05 — breadboard, taban, post, holder ve bağlantı elemanları).
- V01 ilk teslim: sıfırdan BA2/M, PH50/M, TR50/M ve EO15-866 hedefli dört görsel parça; iki ayna istasyonu, 13 optikli genişletilmiş Mach–Zehnder, iki Cycles still ve beş asset kütüphanesi. Ayrıntılar `docs/mechanics/promo-parts.md`. `promo-asset-reload` PASS (sahne ve beş asset). `promo-new-parts-v2` PASS: altı nominal gövde zarfı, optik iz değişmezliği, BAD=0. İç geometri, toleranslar ve breadboard bağlantıları henüz doğrulanmadı; V01 nihai gerçekçilik kapısı açık. Tüm parçalar yenilenmiş değildir.
- Sonraki çalışma: ana sırada 05 breadboard/post/holder ailesi; V01 gerçek montaj doğrulaması 03–04 ve ilgili parça doğrulama adımlarına bağımlı. Görsel teslim bu adımları tamamlanmış saymaz.
- 01 dosyaları: `docs/mechanics/product-evidence.md`, `docs/mechanics/product-evidence.json`, `tools/check_mechanical_inventory.py`.
- 01 kontrolü: `python3 tools/check_mechanical_inventory.py` → INVENTORY PASS 33/33; 30 hedef, 3 açık. Bu kontrol kapsam ve kaynak referanslarının yapısını denetler, dış kaynak doğruluğunu veya mesh uyumunu kanıtlamaz. Runtime kodu değişmediği için Blender render/regresyonu tekrar çalıştırılmadı.
- Kanıt açıkları: POLARIS-K1 eski belge canlı erişimi; CAMERA/SOURCE gerçek SKU; tüm ailelerin CAD/çizim revizyonu, datum ve toleransları; metrik bağlantı vidalarının gerçek uzunlukları; VC1 ve CXYZ1 sürüm farkları. Bunlar ilgili modelleme aşamalarının kapanışını engeller.
- Kritik sonraki düzeltmeler: EO-15866 açı aralığı, KM100 adjuster dişi, GM100 açı aralığı, TRF90 vida giriş derinliği; kaynaklı ayrıntılar envanterde.
- Her kapanışta: tamamlanan adım, değişen dosyalar, test komutu/sonucu, kanıt boşluğu, kalan işler ve sıradaki adımı buraya yaz.
- Plan değişikliği: gerekçe ve bağımlılık etkisini kaydet; tamamlanma koşulunu kolaylaştırmak için zayıflatma. Dış veri yoksa eksik kısmı blocked olarak göster; veri uydurarak tamamlandı sayma.

- V01 ek teslim r4: 13 holder ve 13 özel masa tabanı; 26 masa vidası gerçek ızgara koordinatında. Tüm eski render tabanları kapalı. `table-bases-verify` PASS, birimler 32/32. Mekanik üretim/yük/tolerans doğrulaması açık; ana plan 03 sırası değişmedi.

- V01 r6: kalan 11 istasyonun kaynak/lens/pencere/döner mount/beamsplitter/dedektör
  donanımı `promo_stations.py` ile sıfırdan oluşturuldu. Altı yeni asset ailesi,
  toplam 11 asset dosyası ve üç render. `new-stations-verify` PASS, birimler 32/32.
  Kullanıcının onayladığı kısa kenar kanalları korundu. Üretici CAD doğrulaması,
  tolerans/diş uyumu, mekanik hareket ve tam demet açıklığı hâlâ açık; sıra 03.
