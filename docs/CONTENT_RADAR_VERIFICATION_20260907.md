# Content Factory és Kérdésradar – ellenőrzés, 2026. szeptember 7.

## Állapot

A javítások a külön fejlesztési ágban vannak. Ebben az ellenőrzésben nem történt szerverre telepítés, éles adatbázis-módosítás, levélküldés vagy publikálás. Új globális publikálási tiltás nem került be.

Az SSH-kapcsolat a `91.99.93.80` címen a kapcsolat felépülése után sem kapott szerverválaszt (`Connection timed out during banner exchange`). A böngészőben a Hetzner bejelentkezési oldala érhető el; bejelentkezett kezelőfelületet nem találtam. Emiatt a futó verzió, a mai ütemezés és a szerveroldali eredmény jelenleg nem igazolt.

**Telepített verzió:** ebben a munkában nem készült új szerveres telepítés. **Szerveroldali visszaellenőrzés:** nem volt elvégezhető; [hozzáférési ellenőrzés](evidence/source-coverage-20260907/server-access-check.json). A helyi tesztek sikeréből nem következik, hogy az új kód már éles.

## Mi változott?

- A Reddit legújabb bejegyzései, az Index építési témái és a Prohardver felújítási fóruma közvetlenül olvasható. A Gyakorikérdések eredeti kérdésdátuma külön ellenőrzést kapott.
- A beépített, közvetlen fórumlisták sikeres olvasás után 30 perc, hozzáférési hiba után legalább 60 perc múlva kerülnek sorra. Ez a meglévő munkafolyamatban történik; külön ütemező nem készült. Az automatikusan felvett további források a napi beolvasás részei.
- Az eredeti poszt dátuma számít. Az RSS frissítési időpontja, egy idézett hozzászólás dátuma vagy az újbóli megtalálás nem teszi frissebbé a bejegyzést.
- A kérdőjel nélküli szakemberkeresés is felismerhető. Egy meglévő válasz önmagában nem jelenti, hogy az érdeklődő igénye megszűnt.
- A hasznos kérdések tartalmi adatként megmaradnak, a régi vagy nem igazolható dátumú anyagok külön kutatási adatként tárolódnak. Nem keletkezik belőlük kitalált friss érdeklődő.
- Ha az eredeti dátum csak később igazolható, a rendszer ugyanazt a tárolt kérdést egészíti ki. Az ismert dátumot, a másik márkát, a meglévő választ és a kézi döntést nem írja át; egy másik folyamat időközbeni módosítását is megőrzi.
- A pontos posztazonosító megakadályozza az ismételt felvételt. A módosított Reddit-cím, az Index-paraméterek eltérő sorrendje és a záró perjel sem okoz új példányt.
- A felhasználás előtt a rendszer ismét lekéri az eredeti bejegyzést. Átmeneti hozzáférési hiba miatt nem foglal le végleg egy sikertelen válaszrekordot.
- A kereső címét a valódi fórumbejegyzés címére cseréli, az új forrás külön feldolgozási sorba kerül. A keresőkivonat önmagában nem eredeti posztbizonyíték.
- Két meglévő fórumkeresés DuckDuckGo Lite-ra váltott. A valódi keresésből a program hat forráscímet vett át az elkülönített próbaadatbázisba, köztük Hoxa- és Energiaklub-fórumot. Az ismételt feldolgozás sem készített új sorokat. Ez új források automatikus feltárásának bizonyítéka, nem hat új érdeklődőé.
- Az ismételt olvasások nem növelik hamisan a napi lefedettséget. A kikapcsolt források és a márkahozzárendelések megmaradnak.

## Content Factory

A Property360, a RED Property és a Venture Studio hat hivatkozott Drive-anyagát visszaolvastuk. Öt ténylegesen használható tényforrás került az új, `2026-09-07.v1` jegyzékbe. A források eredeti szöveglenyomata és a bizonyító szövegrész megmarad; a teljes dokumentumokat nem tettük a kód tárhelyére.

A tartalom vevői problémát, márkához tartozó tényt, értékesítési célt és vállalható következő lépést kap. Friss fórumanyag hiányában a márka dokumentált vevői problémája is használható; ezt a rendszer nem tünteti fel új fórumbejegyzésként. Valódi forráshiánynál egy pótlási feladat készül, ismétlődő modellhívás és általános pótcikk helyett. A később pótolt forrás újra feldolgozható.

A meglévő API-val jóváhagyott tények eltérő JSON-formátuma is használható marad. A rendszer a ténylegesen tárolt szöveg lenyomatát ellenőrzi; más típusú, például stílusrekordok nem szorítják ki a tényeket. A javított végső szövegben is szerepelnie kell az eredeti problémának és a jóváhagyott ténynek. A meglévő állítás-, képi, csatorna-, levélküldési és publikáció-visszaolvasási ellenőrzések megmaradnak.

Forrásbizonyíték: [márkaforrások visszaolvasása](evidence/source-coverage-20260907/brand-source-readback.md).

## Valódi radarminták

| Eredeti forrás | Eredeti dátum | Értelmezés a próbában |
|---|---|---|
| [Reddit: Munkadíjak?](https://www.reddit.com/r/lakokozosseg/comments/1w8rs4c/munkad%C3%ADjak/) | 2026.09.06. 09:45:34 UTC | Laminált padló és festés költségkérdése; használható tartalmi jelzés |
| [Reddit: Milyen garázst építenétek?](https://www.reddit.com/r/lakokozosseg/comments/1w80vox/milyen_gar%C3%A1zst_%C3%A9p%C3%ADten%C3%A9tek/) | 2026.09.05. 13:32:22 UTC | Építési megoldások és költségek összevetése; tartalmi jelzés |
| [Index: homlokzati hőszigetelés](https://forum.index.hu/Article/viewArticle?a=172270043&t=9004917) | 2026.09.06. 11:18:01, magyar idő | Konkrét döntési kérdés; tartalmi jelzés |
| [Index: burkoló keresése csőtörés után](https://forum.index.hu/Article/viewArticle?a=172254254&t=9004917) | 2026.09.01. 18:34:17, magyar idő | Valódi szakemberkeresés; ebben az életkorban és bizonyítottsággal nem sürgős, igazolt vevő |
| [Prohardver: konyhafelújítás](https://prohardver.hu/tema/lakasfelujito_szerelo_szakemberkereso_nagy_topic_viz_gaz_villany_futes_festes_burkolas_stb/hsz_171759-171759.html) | szeptember 4. 15:56:47, a szeptember 7-i olvasáskor | Saját szöveg és dátum; az idézett korábbi válasz nem számít saját bejegyzésnek |

Az anonimizált próbában mind a hét hasznos forrás megmaradt, az egy irreleváns kontroll kiesett. Két napi feldolgozás után is hét egyedi forrás volt. A 45 nappal későbbi próbában mind a hét kutatási adatként maradt meg. Ezekből nem jelentettünk bizonyított sürgős vásárlókat.

Részletes [próbajelentés](evidence/source-coverage-20260907/replay-report.json) és [eredeti források, reprodukálás](../services/platform-core/tests/fixtures/forum_real_sources/README.md).

Az [élő keresés és adatbázisos felvétel eredménye](evidence/source-coverage-20260907/ddg-live-discovery-report.json) külön tartalmazza a nyers forrásjelölteket. A Hoxa eredeti oldala visszaolvasható volt, de a talált felújítási példa 2013-as. Ez nem friss vevő. A keresés autófelújítási mellétalálatot is adott; a forrásfeltárás után továbbra is szükséges a poszt tartalmának és dátumának ellenőrzése.

## Tartalmi tesztkimenet

Property360-téma: **Telek, házterv és finanszírozás: együtt tervezd.** A cikk a telek, a terv és a finanszírozás összefüggéséből indul ki, majd az ajánlatban szereplő, külön becslésre váró és tervhiányos tételek szétválasztásában segít. Következő lépése a dokumentált telek–ház elővizsgálat.

A [teljes tesztkimenet](evidence/source-coverage-20260907/content-factory-replay.json) valódi márkaforrásokat használ, de a generátort és az ellenőrző modellt teszthelyettesítő adta. Ez a program összekötésének próbája; nem igazolt éles modellgenerálás, képi ellenőrzés vagy publikáció.

## Teszteredmények

| Végső ellenőrzés | Eredmény | Bizonyíték |
|---|---|---|
| Érintett rendszertesztek együtt, az összes javítás után | **427 sikeres, 0 hibás**, 332,95 másodperc | [végső tesztjegyzőkönyv](evidence/source-coverage-20260907/final-regression-results.xml) |
| Az eredeti fejlesztési csomag tesztjei a jelenlegi policy modullal | **40 sikeres, 0 hibás** | [csomagtesztek](evidence/source-coverage-20260907/package-results.xml) |
| Valódi, anonimizált fórumanyagok újrajátszása a végső kóddal | **7/7 hasznos bejegyzés megmarad**, 1 irreleváns kontroll kiesik, ismételt olvasás után is 7 egyedi forrás | [próbaeredmények](evidence/source-coverage-20260907/replay-report.json) |
| Új fórumok élő keresése és helyi felvétele | HTTP 200, 6 forráscím, kétszeri feldolgozás után is 6 sor | [keresési bizonyíték](evidence/source-coverage-20260907/ddg-live-discovery-report.json) |
| Szintaktika és új kódstílus-hibák | Szintaktikai ellenőrzés sikeres; új stílushiba nincs | [ellenőrzési részletek](evidence/source-coverage-20260907/static-check-results.json) |

A 427 tesztes kör tartalmazza a radar, a forrásjegyzék, a Content Factory, a meglévő kézbesítési és publikálási ellenőrzések, a levélküldési hatókör, a forráslefedettség és az érintett közös gyűjtő korábbi regressziós tesztjeit. A korábbi részfutások számait nem adtuk hozzá ehhez az összesítéshez.

A tesztfutás egy meglévő Starlette/httpx elavulási figyelmeztetést adott. A `seed.py` fájlban a kiinduló változatban is jelen lévő 77 kódstílus-jelzés változatlan; nincs új jelzés. Ezek nem teszthibák. A tesztek alatt a rögzített 27 program-, teszt- és mintafájl nem változott.

## Módosított fájlok

Működési kód és forrásjegyzék:

- `services/platform-core/app/growth_ops/catalog.py`
- `services/platform-core/app/growth_ops/processing.py`
- `services/platform-core/app/growth_ops/revenue_policy.py`
- `services/platform-core/app/growth_ops/forum_http.py` – új
- `services/platform-core/app/growth_ops/wide_service.py` – kizárólag a forráslefedettség összesítése
- `services/platform-core/app/content_factory_source_manifest.json`
- `services/platform-core/app/seed.py` – a megnevezett korábbi forrásváltozatok megőrzött leváltása

Új és módosított tesztek: a fórumhozzáférés, a dátumok, az ismételt begyűjtés, a márkaforrások, a tartalmi összekötés és a meglévő feldolgozás tesztjei a `services/platform-core/tests` könyvtárban; anonimizált forrásminták a `tests/fixtures/forum_real_sources` alatt. A `test_public_land_pipeline.py` fájlban kizárólag egy korábbi, a faliórától függő teszt dátumkezelése változott; a telekfeldolgozás kódja nem.

A [teljes, 27 fájlos kód-, teszt- és mintajegyzék](evidence/source-coverage-20260907/changed-code-files.md) külön elérhető. Az ellenőrzött fájlok [SHA256-lenyomatai](evidence/source-coverage-20260907/tested-files.sha256.json) a tesztfutáskor rögzített változatot azonosítják.

Az eredeti csomag 40 tesztje változtatás nélkül bekerült a `scripts/tests/test_content_intent_revenue_v1.py` fájlba, és a jelenlegi modullal is lefut. A reprodukálható forráspróba: `scripts/replay_forum_real_sources.py`.

## Mentés és visszaállítás

Kiinduló commit: `264ba6e6577cb25efdfd72ce0e2a3b8ab1456bfa`; külön ág: `agent/content-intent-revenue-20260906`. A munkakönyvtár a vizsgálat kezdetén tiszta volt. A main ágat nem módosítottam.

Helyi mentés: `C:\Users\user\Documents\GitHub\content-intent-revenue-pre-verification-264ba6e.tar`.

SHA256: `B7465C1418639E73533017F5E5062805A26856DC95DB5B2A2DAA3A63467EB05B`.

Helyi visszaállításhoz a kiinduló commitból új, külön munkakönyvtár készíthető; nem szükséges a jelenlegi munkát felülírni. Szerveroldalon a telepítés előtt friss kód-, beállítás- és adatbázis-mentés szükséges. A korábban megkezdett szervermentést ebben a vizsgálatban nem lehetett visszaellenőrizni, ezért nem tekinthető most igazolt mentésnek.

Szerveroldali visszaállítás: a tényleges telepítés előtt kiolvasott korábbi kiadás és szolgáltatásbeállítás célzott visszakapcsolása, majd adatbázis-, állapot- és verzióellenőrzés. Megosztott konfiguráció vagy más munkafolyamat fájljainak vak felülírása nem része az eljárásnak.

## Fennmaradó akadályok

1. A szerver jelenlegi verziója és ütemezése nem ellenőrizhető, a telepítés nem történt meg. A korábban azonosított szolgáltatások `imperial-staging-platform-core-1` és `imperial-staging-growth-ops-worker-1`; az utóbbi belépési pontja `python -m app.growth_worker`. Ez korábbi azonosítás, nem mai szerveroldali bizonyíték.
2. Az éles DeepSeek-generálás és az új kód szerveroldali próbája még nincs igazolva. A helyi környezetben nincs használható DeepSeek-hitelesítő és modellhívási beállítás. A valódi próba a szerver meglévő hozzáférésével, külön tesztadatbázison végezhető el. A helyi próbák nem hívták a levélküldő és a publikáló szolgáltatásokat.
3. A Bing HTML- és RSS-keresései a valódi próbákban értelmetlen találatokat adtak; a két általános fórumfeltáró kereséshez a bizonyított DuckDuckGo Lite-út került be. Új fórumok automatikus megtalálása és eltárolása igazolt. Minden új fórum saját dátumfelismerése, a teljes internetes vagy Facebook-csoportos lefedettség nem igazolt.
4. A beolvasás szándékosan korlátos: Redditen forrásonként a legújabb 25 bejegyzés, Indexen egy kategóriaolvasásból legfeljebb három megfigyelt témaszál. A félórás újraolvasás javítja a frissességet, de önmagában nem bizonyít hiánytalan lefedettséget.
