# Kötelező magyar nyelvi és direct-response szakértői kapu v2

Ez a protokoll minden publikálható szöveges tartalomra vonatkozik, a
`SOURCE_PREVALIDATED` kereskedelmi gyorsított útvonalat is beleértve. A
forrásvalidáció csak az állítás jogosságát igazolja; nem helyettesíti a
közérthető magyar megfogalmazás és a professzionális marketing-szöveg
ellenőrzését.

## Megkerülhetetlenségi feltételek

Publikáció kizárólag akkor indulhat, ha az aktuális tartalomhashhez és
generálási futáshoz egyszerre létezik:

1. jóváhagyott `GATE_HU_LANGUAGE_EXPERT`;
2. jóváhagyott `GATE_MARKETING_COPY_EXPERT`;
3. jóváhagyott összesített Gate 1;
4. jóváhagyott releváns jogi, pénzügyi és műszaki kapu;
5. az útvonalhoz előírt emberi jóváhagyás;
6. sértetlen, HMAC-SHA-256-tal attesztált szakértői jegyzőkönyv.

A szakértői kulcs külön secretként kerül a review-szolgáltatáshoz. Nem kerülhet
a generátor promptjába, kliensoldali kódba, adatfájlba vagy repositoryba.

## Nyelvi minimum

Mind a négy dimenzió minimuma 9/10:

- idiomatikus, természetes magyar nyelv;
- helyesírás és nyelvtan;
- egyértelmű jelentés és logikai kapcsolat;
- a célcsoport számára érthető szakmai terminológia.

Egyetlen nyitott magyartalan, kétértelmű vagy javítandó fordulat mellett sem
adható `APPROVED` döntés. A reviewernek köznyelven le kell írnia, mit ért az
olvasó a teljes üzenetből, az ajánlatból és a CTA utáni következő lépésből.
Ha ezek bármelyike többféleképpen értelmezhető, a döntés kötelezően
`RETURN_FOR_REVISION`.

## Online marketing-szövegírói minimum

Mind a hat dimenzió minimuma 9/10:

- hook és relevancia;
- az ajánlat tartalma, választási helyzete és feltételei;
- konkrétság és bizonyíték;
- meggyőző erő túlzó ígéret nélkül;
- márkahang;
- egyértelmű konverziós út.

Az ellenőrzés nem jutalmazza a hangzatos, de jelentés nélküli fordulatokat. A
kampány belső munkaneve nem helyettesítheti a fogyasztói ajánlat kifejtését.
Ár, kedvezmény, ajándék, garancia vagy határidő csak a kanonikus forrás
scope-jával és feltételeivel együtt fogadható el.

## Kötelező protokollverzió

`expert-hungarian-direct-response-v2`

A generáló és az ellenőrző futás, valamint a generáló és az ellenőrző modell
nem lehet azonos. A jegyzőkönyv más assetre vagy később módosított tartalomra
nem használható újra.

## Kötelezően blokkolt minták

A determinisztikus réteg a szakértői döntéstől függetlenül blokkolja az ismert
hibás mintákat, köztük:

- „az otthona köré zárul”;
- a magyarázat nélkül használt „kész kertkapcsolat” és toldalékolt alakjai.

Az ilyen lista biztonsági háló, nem teljes nyelvi szótár. Az új hibákat a
strukturált szakértői review-nak kell felismernie.

## Kötelező kampánygyártási állapotgép

Publikálható kampányanyag kizárólag az alábbi sorrendben készülhet:

1. `STRATEGY_QA`: a verziózott CopyBrief stratégiai ellenőrzése;
2. `COPY_QA` és `FOUR_GATE_QA`: direct-response copy, magyar nyelvi, brand-,
   jogi, pénzügyi és műszaki ellenőrzés;
3. `VISUAL_PRODUCTION`: egy futásban pontosan egy, szöveg nélküli vizuális alap;
4. `CREATIVE_DIRECTOR_QA`: a producertől független kreatív igazgatói review;
5. `ASSEMBLY_QA`: jóváhagyott copy és vizuál platformexportokká komponálása;
6. `RELEASE_QA`: online marketing manager által végzett integrált recheck;
7. `RELEASE_APPROVED`: hashhez kötött, változtathatatlan PublicationBundle;
8. `LIVE_QA`: publikálás utáni háromszereplős double check;
9. `PUBLISHED` vagy hiba esetén `QUARANTINED`.

Az online marketing manager, a kreatív igazgató és a direct-response copywriter
élő review-ját három külön reviewer identitásnak kell elvégeznie. Egyetlen
elutasítás `QUARANTINED` állapotot és `PAUSE_OR_UNPUBLISH` üzenetet hoz létre.
Automatikus újragenerálás és újrapublikálás nem engedélyezett.

Carousel vagy variánskészlet esetén minden vizuális alap külön
`generation_run_id`, `visual_direction_id`, output hash és kreatív igazgatói
döntés alatt készül. Ugyanazon assethez egyszerre csak egy aktív kreatív lehet
review alatt.

## Jelentés–ok–ajánlat–következő lépés ellenőrzés

A generálási trace-ben külön, köznyelvi mezőként kötelező rögzíteni:

1. mit ígérünk a fogyasztónak;
2. milyen ellenőrzött ok vagy mechanizmus teszi ezt hihetővé;
3. pontosan miből választhat és milyen feltételekkel;
4. mi történik a CTA-ra kattintás után.

Egy életérzés-szlogen nem helyettesíti ezeket. A „több idő élni” önmagában
blokkolandó: csak akkor lehet értelmes állítás része, ha ugyanabban a tartalomban
szerepel az igazolt ok, például a tervezéssel együtt vállalt idő vagy az üzemi
előregyártás.

## Típusház-kreatívok kötelező vizuális biztonsági kapuja

- Teljes házat bemutató kompozíciónál minden tető-, fal- és épületsaroknak
  látszania kell.
- Részletkivágás csak előre deklarált kompozíciós céllal engedélyezett.
- Véletlen crop, képhatáron túlfutó címke vagy felirat nem hagyható jóvá.
- Mintázat vagy képzaj nem kerülhet szöveg mögé.
- Céltalan dekoratív keret legfeljebb a kreatív 8%-a lehet.
- Típusház-fókuszú anyagnál a ház vizuális területe legalább 45%.
- A dátumtartomány önmagában nem üzenet: „Augusztusi akció” vagy „Érvényes”
  kontextus és belső margó szükséges.

Ezeket a kreatív igazgatói jegyzőkönyv strukturált mezői és a generálási trace
is kötelezően rögzítik; hibás érték mellett `APPROVED` döntés nem adható.

## Márkák közötti különbözőség és külön futás

Az azonos kampánycsaládba tartozó, de különböző márkájú asseteknél kötelező:

- eltérő `generation_run_id`;
- eltérő `copy_architecture_id`;
- eltérő `copy_structure_signature`;
- eltérő vizuális irány és kompozíciós aláírás.

A hasonlósági ellenőrzés nemcsak egy brief variánsait, hanem az azonos
`campaign_id` alatt létrejött valamennyi márkát összeveti. Azonos nyitás,
bekezdéssorrend, bizonyíték–ajánlat–CTA sorrend vagy azonos generálási futás
esetén az új asset blokkolódik.

## Belső szerkesztési nyelv nem kerülhet fogyasztói szövegbe

A generátor, a kritikus és a reviewer munkanyelve nem jelenhet meg a
hirdetésszövegben. Determinisztikusan blokkolandó többek között:

- „ködös életérzés”;
- „nem hangzatos ígéret”;
- „a vállalás ... kapcsolódik” típusú adminisztratív mondat;
- önmagában álló „AAA”, ha nincs kiírva a minősítés vagy igazolás jelentése;
- a nem hivatalos „Magyar Brands” írásmód.

A helyes megoldás közvetlen, fogyasztói nyelv: például „Fix ár, fix határidő,
tervezés az árban.”

## Logó- és bizalmi jelzés policy

A kontraszt önmagában nem elegendő. A kreatív igazgatói review külön,
kötelezően igazolja, hogy a logó lockupja márkanatív és arculatilag megfelelő.
Bizalmi logó mellett képaláírás elhagyható. Ha van képaláírás, annak a rövidítés
helyett a teljes fogyasztói jelentést kell közölnie; például:
„Kétszeres MagyarBrands-díjazott márka; AAA kategóriás panaszmentességi
igazolás.”
