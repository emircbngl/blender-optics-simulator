# Ürün ve teknik belge envanteri — aşama 01

33/33 mevcut preset kaydedildi. **Bu dosya gerçekçilik doğrulaması değildir.** 30 girdiye üretici kaynağında adı geçen hedef atanmıştır; POLARIS, CAMERA ve SOURCE için kimlik/kanıt açığı vardır. Hiçbir mevcut mesh henüz hedef ürünün doğrulanmış kopyası değildir.

Makine okunur kayıt: [product-evidence.json](product-evidence.json). Kaynakların bir bölümü arşiv veya arama indeksinden okunabildi; bazı canlı Thorlabs sayfaları boş HTML döndürüyor. Kaynak erişim durumu her kayıtta ayrı tutulur. Ürün sayfası CAD indirme seçeneği sunması, dosyanın indirildiği veya paylaşma izni olduğu anlamına gelmez.

## 33 preset eşleştirmesi

| Preset | Aile | Hedef ürün | Eşleştirme | Kaynak |
|---|---|---|---|---|
| KM100 | kinematic | KM100 | named_reference | [kinematic](https://www.thorlabs.de/newgrouppage9.cfm?objectgroup_id=1492&pn=KM100-E04) |
| KM100CPM | kinematic | KM100CP/M | named_reference | [cp](https://www.thorlabs.com/catalogpages/Obsolete/2019/ESK05.pdf) |
| KS1 | kinematic | KS1 | named_reference | [ks](https://www.thorlabs.de/newgrouppage9.cfm?objectgroup_id=3&pn=KS1T) |
| POLARIS | kinematic | Henüz doğrulanmadı | evidence_gap | [polaris](https://www.thorlabs.com/catalogpages/obsolete/2023/POLARIS-K1.pdf) |
| EO15866 | kinematic | 15-866 | named_reference | [eo](https://www.edmundoptics.com/p/25254mm-e-series-kinematic-mount/44292/) |
| GM100 | gimbal | GM100/M | replacement_target | [gimbal](https://www.thorlabs.com/thorproduct.cfm?partnumber=GM100%2FM) |
| RSP1 | rotation | RSP1 | named_reference | [rotation](https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=246) |
| TRF90_0 | flip | TRF90/M | replacement_target | [flip](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=4110) |
| TRF90_90 | flip | TRF90/M | same_product_other_pose | [flip](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=4110) |
| VC1 | vclamp | VC1/M | named_reference | [vclamp](https://www.thorlabs.com/catalogpages/obsolete/2016/VC3.pdf) |
| LMR | lens | LMR1/M | replacement_target | [lens](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1433&pn=LMRA10) |
| CAMERA | camera | Henüz doğrulanmadı | identity_gap | Belirsiz |
| SOURCE | source | Henüz doğrulanmadı | identity_gap | Belirsiz |
| XSTAGE | translation | PT1/M | replacement_target | [stage](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=706&pn=PT1%2FM) |
| CAGE30 | cage30 | CP33 | assembly_target | [cage30](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=2273&pn=CP33) |
| RAIL_RLA | rail | RLA300/M | assembly_target | [rail_rla](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=30&pn=RLA300%2FM) |
| RAIL_X95 | rail | XT95-250 | assembly_target | [rail_xt95](https://www.thorlabs.com/NewGroupPage9_PF.cfm?Category_ID=27&Guide=10&ObjectGroup_ID=244) |
| KINEMATIC_05 | kinematic | KM05/M | replacement_target | [km_archive](https://www.thorlabs.com/images/Catalog/V19_02_Optomech.pdf) |
| KINEMATIC_2 | kinematic | KM200 | replacement_target | [km_archive](https://www.thorlabs.com/images/Catalog/V19_02_Optomech.pdf) |
| ROTATION_05 | rotation | RSP05/M | replacement_target | [rotation](https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=246) |
| ROTATION_2 | rotation | RSP2/M | replacement_target | [rotation](https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=246) |
| LENS_CELL_05 | lens | LMR05/M | replacement_target | [lens](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1433&pn=LMRA10) |
| LENS_CELL_1 | lens | LMR1/M | replacement_target | [lens](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1433&pn=LMRA10) |
| LENS_CELL_2 | lens | LMR2/M | replacement_target | [lens](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1433&pn=LMRA10) |
| XY_1 | translation | LM1XY/M | replacement_target | [xy](https://www.thorlabs.com/catalogpages/Obsolete/2025/LA4130-633.pdf) |
| XYZ_1 | translation | CXYZ1A/M | replacement_target | [xyz](https://www.thorlabs.de/newgrouppage9.cfm?objectgroup_id=7492&pn=CXYZ1) |
| PRISM_PLATFORM | prism | PCMP/M | assembly_target | [vclamp](https://www.thorlabs.com/catalogpages/obsolete/2016/VC3.pdf) |
| IRIS_1 | iris | ID25/M | replacement_target | [iris](https://www.thorlabs.de/newgrouppage9.cfm?objectgroup_id=206&pn=ID8%2FM) |
| CAGE16 | cage16 | SP02 | assembly_target | [cage16](https://www.thorlabs.com/catalogpages/V21/169.PDF) |
| CAGE60 | cage60 | LCP01/M | assembly_target | [cage60](https://www.thorlabs.com/catalogpages/Obsolete/2023/LCP01T.pdf) |
| TUBE_SM05 | tube | SM05L10 | assembly_target | [tubes](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=3383) |
| TUBE_SM1 | tube | SM1L10 | assembly_target | [tubes](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=3383) |
| TUBE_SM2 | tube | SM2L10 | assembly_target | [tubes](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=3383) |

TRF90_0 ve TRF90_90 iki ürün değil, aynı ürünün iki pozudur. LMR ve LENS_CELL_1 aynı hedefle birleştirilebilir fakat eski kimlikleri korunur. X95 etiketi seçilen Thorlabs XT95-250 ürününe eşit değildir; geçiş açık yapılacak. Metrik hedef seçilmesi mevcut inç varyantının otomatik değiştirilmesi anlamına gelmez.

## Montaj alt parçaları ve BOM sınırı

Her presetin JSON kaydında alt parça rolleri vardır. Sayısı/parça numarası belgelenmeyen vida, yay, mafsal ve kilitler null bırakıldı. Bunlar sipariş verilebilir veya montajı onaylanmış BOM değildir. Post zinciri: tabla → tabla vidası → taban → holder bağlantısı → holder → post → mount bağlantısı. İlk araştırılacak taşıyıcılar BA2/M, PH50/M, TR50/M; tabla ve uygun uzunlukta metrik vidalar henüz sabitlenmedi.

| Alt parça | Rol | Varyant | Kaynak |
|---|---|---|---|
| TR50/M | post | metric | [support](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=6930) |
| PH50/M | holder | metric | [support](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=6930) |
| BA2/M | base | metric | [support](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=6930) |
| SH8S025 | example_screw_not_metric_chain | imperial | [support](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=6930) |
| PCM/M | post_clamp | metric | [vclamp](https://www.thorlabs.com/catalogpages/obsolete/2016/VC3.pdf) |
| PCMP/M | prism_base | metric | [vclamp](https://www.thorlabs.com/catalogpages/obsolete/2016/VC3.pdf) |
| RC1 | rail_carrier | counterbore | [rail_rla](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=30&pn=RLA300%2FM) |
| XT95RC1 | rail_carrier | metric | [rail_xt95](https://www.thorlabs.com/NewGroupPage9_PF.cfm?Category_ID=27&Guide=10&ObjectGroup_ID=244) |
| SM1A1 | tube_adapter_identity_only | SM_thread | [tubes](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=3383) |
| SM1A2 | tube_adapter_identity_only | SM_thread | [tubes](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=3383) |

## Uygulama öncesi çözülmesi gereken farklar

- **eo_travel**: tip_tilt_limit_deg = 3.5. presets.py EO-15866 currently +/-4 deg Kaynak: [eo](https://www.edmundoptics.com/p/25254mm-e-series-kinematic-mount/44292/); yer: Fine Tilt Angle / Fine Tip Angle. Uygulama aşaması 6.
- **km_adjuster**: adjuster_thread = 1/4-80. presets.py KM100 adjuster_thread is 8-32; do not confuse post fastener with adjuster Kaynak: [km_archive](https://www.thorlabs.com/images/Catalog/V19_02_Optomech.pdf); yer: page 140 KM100/KM200. Uygulama aşaması 6.
- **gm_travel**: angular_limit_deg = 2.5. presets.py GM100 +/-4 deg estimate Kaynak: [gimbal_spec](https://www.thorlabs.com/catalogpages/Obsolete/2022/KC45D.pdf); yer: GM100/GM200 section. Uygulama aşaması 7.
- **flip_penetration**: post_screw_max_penetration_mm = 5. No corresponding assembly depth rule currently enforced Kaynak: [flip](https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=4110); yer: Filter Mount with 90 degree Flip caution. Uygulama aşaması 7.
- **cage16_rods**: rod_diameter_mm = 4. Do not generalize ER rods to all cage sizes Kaynak: [cage16](https://www.thorlabs.com/catalogpages/V21/169.PDF); yer: page 169 SR rods. Uygulama aşaması 8.
- **cage60_rods**: rod_diameter_mm = 6. Bağımsız kaynak girdisi. Kaynak: [cage60](https://www.thorlabs.com/catalogpages/Obsolete/2023/LCP01T.pdf); yer: 60 mm cage plate through holes. Uygulama aşaması 8.
- **flip_manual**: assembly_evidence = Retainer removal, filter direction, re-seating, ER1 rod installation and locking sequence. Bağımsız kaynak girdisi. Kaynak: [flip_manual](https://www.thorlabs.com/images/tabimages/MTN015225_B-D02.pdf); yer: section 5.2.5 / printed p28. Uygulama aşaması 12.

VC1 belgeleri nesiller arasında farklı clamp arm ve çap aralığı gösteriyor. Aynı isimli eski ve yeni parçaların ölçülerini bir araya getirmeyeceğiz. CXYZ1 URL’sinde CXYZ1A açıklaması bulunuyor; revizyon kontrolü gerekli.

## Ölçüm ve doğrulama protokolü

Her ürünün critical_measurements listesi: arayüz koordinatları, çap/kalınlık, diş ve kavrama derinliği, oturma yüzeyi, hareket sınırları ve erişim için ürün bazlı kontrol listesi verir. Ölçüm gerçek mesh üzerinde yerel datumlara göre, kaynak çizimden bağımsız kontrol koduyla yapılacak. Fotoğraf oranından hassas ölçü çıkarılmayacak.

Ölçülü çizim/CAD ve ilgili datum okunmadan sayısal model hata eşiği atanmadı. Eşikler uygulama başlamadan sabitlenecek; üretim toleransından ayrı tutulacak. Kaynak eksikken eşik null ve boyutsal doğrulama kapısı kapalıdır. Bu, aşama 01 envanterinin kapanmasına izin verir; ölçü doğrulamasının kapandığı anlamına gelmez.

## CAD, belge revizyonu ve MCP aktarımı

GM100/M sayfasında PDF/DXF/STEP/Solidworks seçenekleri görüldü; gerçek CAD dosyası indirilmedi. Diğer kaynaklar ürün/aile belgesi girişleridir. Hiçbir üretici dosyası pakete eklenmedi. CAD yeniden dağıtım izni doğrulanmadı; sonraki adımlar bağlantı, revizyon ve dosya hashini kaydetmeli, belirsizliği izin varsaymamalı. Ölçülü belgeden özgün prosedürel modelleme bir alternatif; yayımlama şartı ayrıca değerlendirilir.

Bu JSON henüz MCP runtime aracı değildir. İlerideki ajan yalnız `primary_published_nominal_not_mesh_verified` verisini okuyarak `compatible` veya “birebir” sonucu veremez. Parça kimliği, varyant, kaynak revizyonu, bağlantı verisi, montaj durumu ve eksik kanıt birlikte denetlenmeli. Şimdiki optik API’ye yeni araç eklenmedi.

## Kapanış

Aşama 01 envanter kapsamı tamam: 33 girdinin her biri hedef veya açık eksikle sonuçlandırıldı. Aşama 02 için şema gereksinimleri hazır; ürün modelleme adımlarına geçmeden kaynak/datum, tolerans ve kimlik boşlukları çözülmeli.

## Aşama 05 kaynak edinimi (22 Eylül 2026) — kısmi, ve aşama açık

Aşama 05 (breadboard, taban, post, holder, bağlantı elemanları) taşıyıcı zincirin ölçülerini ister.
Üreticinin canlı ürün sayfalarından yayımlanmış **nominal** veriler `support_facts` altına alındı; ikisi
de mesh doğrulanmış değildir ve tolerans içermez:

| Parça | Yayımlanan | Kaynak |
|---|---|---|
| TR50/M | Ø12.7 mm taşlanmış gövde; üstte M4 diş + çıkarılabilir çift uçlu M4 setskur (SS4M12D); tabanda M6 diş; yanda Ø3.2 mm delik; 303 paslanmaz; L = 50 mm | post ailesi sayfası |
| PH50/M | Ø12.7 mm post holder; yaylı, altıgen kilitli başparmak vidası; L = 50 mm | ürün sayfası |

İmperial TR serisi üstte 8-32, tabanda 1/4"-20'dir. **Bir varyantın dişini diğerine taşıma.**

### Aşama 05'i hâlâ kapatmayan eksikler

Sayfalar boyut, diş ve malzeme yayımlıyor; aşama 05'in denetlemesi gereken ölçüleri yayımlamıyor:

1. TR/M üst M4 ve taban M6 için diş derinliği / kullanılabilir kavrama
2. PH50/M delik çapı, Ø12.7 mm posta göre boşluğu ve giriş aralığı
3. PH50/M taban dişi ve derinliği
4. BA2/M yuva geometrisi, havşa ve bağlantı vidası boyu
5. **Breadboard ürün kimliği yok** — 33 presetlik envanterde hiçbir tabla yok
6. Her arayüz çerçevesi için datum konumu ve yönü — aşama 04b yerleştirmeyi çerçevelerden yapar ve
   kaynaklı tek bir çerçeve yok

Bunlar üreticinin CAD çizimlerindeydi. **Sahip çizimlerin açılmasını onayladı** (22 Eylül 2026) ve
üç çizim yalnız ölçü okumak için açıldı. Dosyalar depoya konmadı ve yeniden dağıtılmadı; kaydedilen şey
ölçü + çizim numarası + revizyon + URL + tarihtir.

### Birincil çizimlerden okunanlar

| Parça | Çizim | Rev |
|---|---|---|
| TR50/M | 0331 | J (28/MAR/13) |
| PH50/M | 23132 | B (20/DEC/11) |
| BA2/M | 19227 | A (08/SEP/14) |

**TR50/M** — Ø12.7 mm gövde, 50.0 mm boy; tabanda **M6 × 1.0, 8.6 mm derin** montaj deliği; yanda
Ø3.2 mm delik, eksen çizgisi setskur ucundaki gövde yüzeyinden **10.2 mm**; üstte **SS4M12D**, M4 × 0.7
çift uçlu setskur, 12 mm boy, 2.0 mm altıgen; setskurun gövdeden dışarı kalan boyu **4.6 mm MIN – 5.2 mm
MAX**; paslanmaz çelik. 50.0 mm boy, 10.2 mm ve 4.6–5.2 mm aynı yüzeyden ölçülür.

**PH50/M** — Ø25.0 mm gövde, 50.0 mm boy; **Ø12.8 mm delik, 43.2 mm derin** ("FOR USE WITH TR-SERIES
POSTS"); tabanda **M6 × 1.0 boydan boya diş**; Ø14.5 mm yaylı başparmak vidası, 5 mm altıgen, ekseni
delik tarafındaki üst yüzeyden 12.7 mm; topuz gövde yüzeyinden **10.0 mm** dışarı çıkar. Duvar kapalıdır,
boydan boya yarık yoktur; post yarık tüple değil başparmak vidasının ucuyla sıkılır. Aile sayfasından
**maksimum tork 28 in·lbs (3.2 N·m)**.

**BA2/M** — 75.0 × 50.0 × 10.0 mm; M6 [1/4-20] başlı vida için **3 havşa** (12.5 mm TYP, 37.5 mm
kolonda); M6 için **2 boşluk yuvası** (9.1 mm genişlik, uç merkezleri arası 31.8 mm, yuvalar arası
50.0 mm); eloksallı alüminyum.

**Türetilmiş tek sayı, etiketlenmiş olarak:** Ø12.8 delik − Ø12.7 post = **0.1 mm nominal çap boşluğu**.
Yayımlanmış değil, iki nominalin farkıdır; geçme sınıfı ya da ölçülmüş boşluk değildir
(`verification: derived_from_published_nominals`).

> **Düzeltme (23 Eylül 2026).** 22 Eylül kaydında PH50/M için "10.0 mm ayak yüksekliği" yazılmıştı.
> Çizim 3300 px'te yeniden okundu: ölçü gövde duvarından başparmak vidası topuzunun uç yüzeyine gidiyor.
> PH50/M'nin ayağı yoktur; ayrı bir tabana oturan düz Ø25 mm silindirdir. Olgu
> `ph50m_dwg_thumbscrew_protrusion` olarak düzeltildi. TR50/M'nin 10.2 mm okuması aynı yöntemle doğrulandı.
>
> Ayrıca: bu bölüm 22 Eylül'de #78 ile birlikte yazılmak istendi ama o komut bir kanca tarafından
> engellendiği için dosyaya hiç ulaşmadı; #78'de olgular JSON'a girdi, bu metin girmedi.

### Başparmak vidası: TS6H/M (çizim 23136 rev B, 23 Eylül 2026)

PH50/M'nin başparmak vidası aile sayfasında TS6H/M olarak adlandırılıyor; çizimi aynı onay kapsamında
açıldı. **M6 × 1.0** dış diş; topuz **Ø14.5 × 7.9 mm** (PH50/M çizimindeki Ø14.5 ile aynı); topuz
yüzünden diş ucuna **16.1 mm**, bilye ucuna **17.1 mm** — yani uçta 1.0 mm dışarı çıkan **yaylı bilyeli
piston**; 5 mm altıgen, 3.8 mm derin; maksimum tork 28 in·lb (aile sayfasıyla aynı).

İki çizimin birbirini doğrulaması: topuz yüzü eksenden 12.5 + 10.0 = 22.5 mm'de; 16.1 mm geri gelince
diş ucu **6.4 mm'ye — tam delik duvarına** düşüyor. Bilye 1.0 mm daha içeri, 6.35 mm'deki post yüzeyinin
ötesine uzanıyor: post takılıyken yay önceden yüklü. Okumalar tutarlı.

**Türetilmiş ikinci sayı:** bilye postu vida ekseninde, noktasal olarak sıkar; eksen üst yüzeyden 12.7 mm
aşağıda. Post o eksene ulaşmazsa bilye hiçbir şeye değmez, bu yüzden **en az giriş 12.7 mm** — kesin bir
geometrik alt sınır, önerilen giriş değil (postun ölçülendirilmemiş uç pahı biraz ekler). Olgu
`ph50m_min_insertion_lower_bound`, `derived_from_published_nominals`. Bu sayı olmadan aşama 03'ün
delik/mil kuralı gerçek TR50/M ↔ PH50/M çiftine `unknown` diyor ve aşama 04 birleştirmeyi reddediyordu.

### Ø12 mm post da uyuyor — üreticinin kendi beyanı (23 Eylül 2026)

Post ailesi sayfası: *"These Ø12 mm posts are directly compatible with our standard Ø1/2" Post
Holders"* (TR50/M-JP, Ø12 mm, M4 setskur, M6 diş, L 50 mm). Yani PH50/M'nin deliği boyutla değil,
bilyeli başparmak vidasıyla tutar: Ø12.8 delik en az **0.8 mm** çap boşluğunu kabul eder
(`ph_series_allowed_gap_lower_bound`, türetilmiş). 0.1 mm'lik `post_holder_diametral_gap` bir TR50/M'nin
bıraktığı boşluktur, **izin verilen boşluk değildir**; onu delik boşluğu diye kullansaydım motor
üreticinin desteklediği bir eşleşmeyi reddedecekti. Daha geniş bir boşluk iddia edilmiyor: 0.8 mm'yi
aşan ince bir post reddedilir, tahmin edilmez.

Gerçekten yanlış post: **RS2P/M**, Ø25.0 mm pedestal pillar post (ürün başlığından) — Ø12.8 deliğe girmez.

### Kaynaklı kayıtlar (aşama 05a-2)

`optical_alignment_sim/mechanical_library.py` bu olgulardan şema v1 kayıtları kurar: TR50/M, TR50/M-JP,
RS2P/M, PH50/M. Eklenti dokümanlarla gelmediği için değerler kopyadır; `PROVENANCE` her değeri kaynağı olan
olguya bağlar ve `tests/test_support_assembly.py` biri kayarsa düşer. Çizim kaynakları okunan dosyanın
SHA-256'sını taşır. Üç değer türetilmiştir ve öyle etiketlidir: en az giriş 12.7 mm, izin verilen boşluk
0.8 mm, taban kalınlığı 6.8 mm. `evidence_level` her kayıtta `unverified`.

Motorun sonucu üreticiyle aynı: TR50/M uyar, TR50/M-JP uyar, RS2P/M girmez. Oturtulan post, Dress
Bench'in kendi postuyla aynı yükseklikte, holder tabanının 6.8 mm üstünde durur — kayıtlar ile üretilen
geometri aynı arayüzde buluşuyor.

### Taban, vidalar ve tabla (aşama 05b kaynak edinimi, 23 Eylül 2026)

**Birleşme tipi** (Slotted Bases aile sayfası): post holder'lar tabana, tabanın altındaki havşadan geçen
1/4"-20 (M6) başlı vidayla bağlanır. Aynı sayfa zincirdeki **ilk yayımlanmış toleransı** veriyor: tabanlar
0.002" (**0.05 mm**) içinde paralel ve dik işlenir.

**Vidalar — üreticinin kendi montaj prosedüründen.** Aşama 01 bu zinciri (TR50/M, PH50/M, BA2/M)
EDU-SPEB2/M eğitim kitinin malzeme listesinden almıştı; kitin kılavuzu (MTN021357-D02 Rev A, 22 Temmuz
2020; sahip onayıyla indirildi, depoda değil) montajı adım adım veriyor:

- taban ↔ post holder: **M6 × 10 mm başlı vida** (§6.1.4: BA1/M + PH50/M; §6.1.5: BA2/M + PH75/M — iki
  taban da 10 mm kalın, aynı M6 havşa);
- taban ↔ tabla: **M6 × 16 mm başlı vida + M6 pul** (§6.2).

Kit parça numarası vermiyor, yalnız boyut; vida kaydı bu yüzden "kit vidası" olarak tutuluyor.

**Türetilmiş:** PH50/M'nin M6 dişi 6.8 mm'lik tabanını boydan boya geçiyor. Üreticinin 10 mm vidası
deliğe girmesin diye başın altında en az **3.2 mm** malzeme kalmalı (`ba2m_counterbore_floor_min`). Havşa
derinliği çizimde yok; bu yalnız prosedürün ima ettiği alt sınır.

**Tabla: MB4560/M** — kitin kendi breadboard'u; **sahip 23 Eylül 2026'da onayladı** ve çizim 6282 rev B
(16/JAN/18) okundu: **600.0 × 450.0 × 12.7 mm** alüminyum, köşeler R3.0; **432 adet M6 × 1.0 diş**, **25.0 mm**
adımla, her kenardan **12.5 mm** içeride başlıyor (24 × 18 = 432, tutarlı); tablanın kendisini sabitlemek
için 5 havşalı M6 deliği. 12.7 mm eklentinin mevcut `BOARD_THICKNESS`, 25 mm eklentinin metrik ızgarasıyla
aynı.

**Çizimin söylemedikleri:** diş derinliği yok ve "THRU" da yazmıyor — M6 × 16 mm tabla vidasının kavraması
bilinmiyor. **Diş yönü hiçbir çizimde yok**: "M6X1.0" yazıyor, "LH" yok ama "RH" de yok. Aşama 03 diş
yönü iki tarafta da belirtilmemişse `unknown` döner; yani bugün bu zincirdeki **her** vida bağlantısı
`unknown`. İşaretsiz metrik dişin nasıl okunacağı kaynaklı bir kural gerektiriyor.

**Şema sınırı:** taban bağlantısı üç parçalı bir yığın — baş tabanın havşasında, gövde havşa tabanından
geçer, diş holder'da. Şema v1 bunu ifade edemiyor, bu yüzden taban bağlantısının kavraması kuralla
denetlenemiyor. Bu bir şema değişikliği ve ayrıca karar gerektirir.

### Hâlâ kapanmayanlar

1. **Tabla seçildi (MB4560/M), ama diş derinliği ve diş yönü çizimde yok** — vida kavraması denetlenemiyor.
2. **Üretim toleransı yok** — her çizim "FOR INFORMATION ONLY / NOT FOR MANUFACTURING PURPOSES"
   damgalı ve tolerans vermiyor; ondalık basamaktan tolerans çıkarılmaz.
3. **Datumlar henüz yazılmadı** — arayüz çerçeveleri bu çizimlerden üretilecek ve bağımsız mesh
   ölçümüyle karşılaştırılacak.
4. **BA2/M ↔ PH50/M bağlantı vidası** — çizim yalnız "M6 başlı vida" diyor; parça numarası ve boyu yok.

Holder ↔ post çifti (TR50/M, PH50/M) ise artık birincil çizimden tam kaynaklı; aşama 05a onu önce
yapıyor. Taban ve tabla (05b) bu dört eksik kapanana kadar başlamaz.
