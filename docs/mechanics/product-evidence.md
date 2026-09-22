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

Bunlar üreticinin CAD çizimlerinde. Aşama 01 hiçbir CAD dosyası almadı ve yeniden dağıtım hakkı
belirsiz. Bu yüzden bağımlı iş **başlatılmadı**: `support_blockers.dependent_work_not_started = true`.
Sıradaki hamle sahibin kararı — TR50/M, PH50/M ve BA2/M çizimlerini açmak ve breadboard ürününü seçmek.
