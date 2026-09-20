# Mekanik veri modeli — sürüm 1

Aşama 02: parça/bağlantı metadatası uygulanmıştır. Uyumluluk, fiziksel bağlantı veya montaj motoru henüz yoktur. Aşama 01 envanteri bu runtime şemasına otomatik çevrilmez: adı belirlenmiş hedefin doğrulanmış ölçüleri olduğu varsayılamaz.

## Kayıt ve saklama

`Object.mechanics.record_json` bir JSON snapshot saklar. `Object.optics` ve optik portlar ayrıdır. Verinin JSON olarak saklanması bilinmeyen ölçüleri `null` olarak korur; Blender sayısal özellik varsayılanlarıyla sıfıra çevrilmez. Tek kayıtta:

| Alan | Anlam |
|---|---|
| schema_version | Tam sayı 1; bilinmeyen sürüm okunmaz veya otomatik düşürülmez |
| instance_id | Sahnedeki örneğin kimliği; new_record UUID oluşturur |
| definition_id | Kataloğun sabit ürün tanımı kimliği; nesne adından türetilmez |
| identity | manufacturer, part_number, variant, revision; bilinmeyen alanlar null |
| geometry_revision | Modele ait revizyon; üretici belge revizyonundan ayrı |
| sources | Kimlik → URL, locator, revision, checked_on, sha256 |
| interfaces | Mekanik bağlantılar ve yerel datumlar |
| motions | Bağlantı çerçevesine göre hareket türü ve alt/üst sınırlar |
| evidence_level | Şimdilik yalnız unverified veya visual_approximation |
| validation_evidence | Kaynak referansları; tek başına doğrulama seviyesi yükseltmez |

Kaynakların HTTPS adresi, belge içindeki yeri ve kontrol tarihi gerekir. Revizyon/hash bilinmiyorsa null kalır. Kaydın yapısal geçerliliği URL'nin doğru, okunmuş veya güvenilir olduğunu kanıtlamaz. Sonraki doğrulama aşamaları kaynak içeriğini ve ürün revizyonunu ayrıca sınar. `instance_id` kopyalanan Blender nesnelerinde de kopyalanabilir; montaj grafiği aşaması mükerrer kimliği denetlemeden örneği bağlamamalı.

## Arayüzler ve datumlar

Arayüz kimliği yalnız kendi parça tanımı içinde benzersizdir; ileride tam adres `(instance_id, interface_id)` olacaktır. Optik port kimliğiyle birbirinin yerine kullanılamaz.

Türler: thread, smooth_bore, shaft, plane, hole_pattern, dovetail, clamp, optic_seat.

`frame`: null veya `{origin: [x,y,z], unit: mm|in, quaternion_wxyz: [w,x,y,z], evidence: [...]}`. Poz parça yerel koordinat sistemindedir; quaternion birim uzunlukta olmalıdır. Yerel +Z bağlantı ekseni/yüzey normalidir, +X saatleme referansıdır; sağ elli çerçeve kullanılır. `mating_direction` +Z, -Z, either veya null olabilir. Null datum, sıfır konumu veya kimlik dönüşümü anlamına gelmez.

Thread alanları: standard, gender (internal/external), hand (right/left), form, fit_class, major_diameter, pitch, evidence. Standart adı tek başına diş ölçülerini doldurmaz. Pitch bir turdaki eksenel uzunluk olarak mm veya in ile tutulur; TPI etiketi otomatik yorumlanmaz. Kaynakta TPI varsa ilgili standart dönüştürmesi ayrıca kanıtlanıp giriş değeri belgelenecek. Geçme sınıfı bilinmiyorsa nominal diş adı gerçek geçme garantisi vermez.

`dimensions`: diameter, depth, engagement_min/max, seat_depth, optic_thickness_min/max, rod_spacing, clearance, tool_clearance, insertion_min/max alanlarından gerekenler. Olmayan anahtar ölçülmemiş özelliktir; quantity.value=null ise özelliğin varlığı bilinir, değeri bilinmez. Her ikisi de sonraki uyumluluk motoru için eksik veri sayılabilir. Boş sözlük “sınırsız uyum” değildir.

`holes`: frame, diameter, depth kayıtları; delik yerleşimi tek bir cage etiketiyle varsayılmaz. `access`: tool ve approach_frame. `lock`: kind ve state (locked/unlocked/null). Bu sürümde lock yalnız saklanan metadata, gerçek bir kilit veya hareket engeli değildir.

`motions`: id, interface_id, kind (translation/rotation), minimum, maximum, evidence. Hareket ekseni ilgili interface frame'in +Z yönüdür; daha karmaşık mekanizmalar ayrı arayüzlere sahiptir. Sınırların artan sırada olduğu birimleri normalize edilerek kontrol edilir. Hareket aktarımı, sürtünme, yay, tork veya çarpışma bu sürümde hesaplanmaz.

## Ölçü ve kanıt

Her quantity: `{value, unit, evidence, tolerance, model_error_limit}`.

- Birimler: uzunlukta mm/in, açıda deg/rad. NaN, sonsuz, boolean ve boyutu yanlış birim reddedilir.
- Bilinen değer için mevcut bir kaynak referansı gerekir. Kaynak referansı kaynak doğrulamasının yerine geçmez.
- `tolerance`: null veya `{minus, plus, evidence}`; kaynak biriminde pozitif/ sıfır sapma büyüklükleri. Üretim toleransıdır.
- `model_error_limit`: null veya negatif olmayan, aynı birimde model doğrulama eşiği. Üretim toleransıyla birleştirilmez.
- Pozitif olması gereken diş çapı/adımı ve delik çapı/derinliği için sıfır reddedilir; bilinmeyen null korunur.

`normalized(record)` mm/deg cinsinden ayrı bir hesaplama kopyası üretir. Frame konumları, sınırlar, diş ölçüleri, tolerans ve model hata eşiği birlikte çevrilir. Saklanan kaynak kaydı ve birimleri değişmez.

## Eski sahne, göç ve hata davranışı

`read_object(obj)` boş kayıtta `{status: legacy_unmapped, record: null}` döner. Açılışta preset adı yorumlanmaz, kaynak atanmaz ve geometri değiştirilmez. Geçerli metadata için status=metadata_only; bozuk JSON veya yeni/uyumsuz sürüm için status=unreadable, record=null ve error döner. Ham kayıt yerinde kalır.

`attach_object(obj, record)` önce tüm kaydı doğrular, sonra tek StringProperty yazımı yapar. Mevcut kayıt ancak açık `replace=True` ile değiştirilebilir. Geçersiz giriş mevcut kaydı değiştirmez. Bunlar dahili Python yardımcılarıdır, MCP mutasyon aracı değildir. Yeni sürüm göçleri ileride açık, yedeklenebilir işlemler olacak; v1 hiçbir eski veriyi sessizce dönüştürmez. Bilinmeyen alan veya çift JSON anahtarı reddedilir.

## MCP için sonraki aşama sözleşmesi (taslak; henüz çağrılamaz)

`capabilities().mechanical_assembly` şu an `available: false`, `metadata_schema_version: 1` bildirir. Yeni araç adları tool listesine veya bridge izin listesine eklenmedi.

| Gelecek araç | Girdi | Çıktı / kural |
|---|---|---|
| inspect_part | instance_id veya kesin definition_id | Kimlik, kaynak revizyonu, kanıt seviyesi, eksik alanlar; salt okuma |
| list_interfaces | instance_id | Tam interface adresleri ve datumlar; optik portlardan ayrı |
| check_compatibility | iki interface adresi | compatible/incompatible/unknown/adapter_required; neden, kaynaklar, eksikler |
| plan_assembly | parça örnekleri ve hedef bağlantılar | sıralı adımlar ve önkoşullar; sahneyi değiştirmez |
| apply_assembly_step | plan/adım kimliği, beklenen sahne revizyonu, dry_run | stale state kontrolü, atomik değişiklik ve yapılan değişikliklerin özeti |
| validate_assembly | montaj kimliği | bağlantı, kilit, erişim, eksik veri ve kanıt kapsamı |

Yapay zekâ `metadata_only` sonucunu “parça uyar” olarak yorumlamamalı. Araç kullanılabilirliğini capabilities'ten okumalı; taslaktaki adları çağırmamalı. İleride standart bilgisi eksikse unknown, veri eksikken otomatik bağlama yok. Mevcut API hata biçimi korunacak; testler MCP/API/bridge eşitliğini denetleyecek.

## Doğrulama

`tests/test_mechanical_schema.py`: 16 hatalı veri örneği, in/mm ve rad/deg dönüşümü, null/tolerans koruma, tekrarlı kimlik/kaynak referansı kontrolleri, atomik yazma, kayıt değiştirme koruması, gerçek .blend save/reload, eski metadata yokluğu, kaynak/ürün revizyonlarının korunması, gelecekteki sürümün ham kaydının korunması, optik yol ve pose yalıtımı, kayıt/unregister/register yaşam döngüsü.

Kaydet/aç sonrasında ışın sayıları mevcut optik regresyonun 1e-9 bağıl/mutlak ölçekli toleransıyla karşılaştırılır; metadata yazımı öncesi/sonrası aynı oturumda iz birebir aynı kalır. Tam mekanik uyumluluk veya gerçek ürün doğrulaması testi değildir.
