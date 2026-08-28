# Imperial Intelligence Platform v4.4 / Control Center 1.1

A meglévő Imperial Intelligence Control Center additív továbbfejlesztése. A platform a már kanonizált folyamatok (köztük a HouseBuild, PlotCheck és PlanCheck) üzleti motorját maga futtatja, a külön forrásmodulokhoz pedig közös ProjectID-, esemény-, adatbefogadási, audit- és webes megjelenítési réteget ad.

## Ebben a kiadásban elkészült

### Enterprise Import Center

- Gmail-, Google Drive-, Google Sheets-, CSV-, JSON-, XLSX- és szöveges adatcsomagok fogadási modellje;
- pénzügyi, projekt-, partner-, ügyfél-, beszerzési, szerződéses, termék- és dokumentumadatok tartalmi osztályozása;
- normalizálás, forrásbizonyíték, biztonsági pontszám, validáció és pontos üzleti kulcs alapú deduplikáció;
- staging zóna, emberi jóváhagyás, célmodul- és ProjectID-hozzárendelés;
- auditált commit-csomag és visszagörgetés;
- ProjectRegistry és ProjectFact integráció;
- connector push API a későbbi élő Gmail/Drive/Sheets adapterekhez;
- kézi fájlfeltöltés mobilbarát adminfelületen.

### Imperial TenderMail

- külön küldési domain és feladói identitás regiszter;
- SPF-, DKIM-, DMARC-, tracking-domain- és warm-up kapuk;
- kampány, személyre szabott címzettlista és órás küldési plafon;
- globális bounce-, panasz- és leiratkozási tiltólista;
- kötelező tenderportál-link és egyedi értesítési beállítási URL;
- provider webhook események és idempotens eseményazonosító;
- éles szolgáltatói adapter nélkül csak biztonságos küldésszimuláció.

### Webes ügyfél- és belső élményréteg

- újépítési kalkulátor a jóváhagyott 2026-07 márkaárak és készültségi/csomagtényezők alapján;
- elkülönített publikus és belső számítás: a publikus API nem ad vissza önköltséget, fedezetet vagy kapacitási adatot;
- felújítási kalkulátor a meglévő 398 munkadíj- és 283 anyagtételes Ártükör alapján;
- HouseMatch a meglévő 45 aktív rekorddal és az eredeti négy pontozási profillal;
- BuildConfig teljes munkatér megváltoztathatatlan konfigurációverzióval, tételes BOM-mal, opciókompatibilitással, ár-/fedezet-/cashflow-/kapacitáskapukkal és kettős szakmai jóváhagyással;
- közös reszponzív, white-labelre előkészített vizuális felület.

## Megőrzött kötelező üzleti szabályok

1. A típusház és előre definiált opciók ügyféloldali árforrása a meglévő konfigurátorlogika marad.
2. Forráselsőbbség: technológia–készültség ármodell → márka/webes árpozíció → tételes Ártükör-kontroll.
3. Az Ártükör tételei nem adhatók automatikusan hozzá az újépítési all-in önköltséghez.
4. Belső ajánlat csak műszaki, pénzügyi, minimum 35%-os cash-margin, cashflow- és kapacitáskapu után válhat küldhetővé.
5. A forrásmodul zárja le a saját üzleti tranzakcióját; az Import/Control Center nem írhatja felül annak jóváhagyott döntését.

## Gyors indítás

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Fejlesztői belépés:

- `owner@imperial.local`
- a belépési értéket a login oldal írja ki nem-production módban; a
  `CONTROL_CENTER_DEMO_LOGIN` környezeti változóval rögzíthető, enélkül
  futásonként egyedi, biztonságosan generált érték érvényes (a forrásban
  nincs fix demo jelszó);
- a demo-belépési értéket és a partneri demókódot a folyamatok közös, nem
  követett futásidejű állapotfájlja tartja konzisztensen
  (`services/platform-core/runtime/demo-credentials-state.json`,
  git-ignored). Production adatbázisba a `demo_accounts_allowed()` kapu
  miatt szintetikus demo fiók vagy partneri hozzáférés nem kerülhet.

Élesítés előtt a demo-felhasználót és minden titkot cserélni kell.

## Fő UI útvonalak

- `/` – Vezetői cockpit
- `/imports` – Enterprise Import Center
- `/experience` – Új építés, felújítás és HouseMatch ügyfélélmény
- `/buildconfig` – kanonikus HousePlan-alapú BuildConfig, BOM, ár, cashflow, kapacitás és kiadás
- `/housebuild` – Kanonikus típusház-generálás, HousePlan-validáció és kiadás
- `/plotcheck` – Kanonikus telekalkalmassági döntési motor
- `/plancheck` – Kanonikus tervcsomag-ellenőrzés
- `/tendermail` – Tenderkampányok, domainkapuk, címzettek és suppression
- `/projects` – Közös ProjectID-regiszter
- `/modules` – Modulregiszter

## Új API-k

- `POST /api/imports/push` – connectorból érkező adatcsomag
- `POST /api/imports/jobs` / `.../items` / `.../process`
- `POST /api/imports/staged/{id}/review`
- `POST /api/imports/jobs/{id}/commit`
- `POST /api/imports/batches/{id}/rollback`
- `POST /api/tendermail/campaigns` / `.../recipients` / `.../approve` / `.../queue` / `.../dispatch`
- `POST /api/tendermail/events` – kézbesítési, bounce-, complaint- és unsubscribe-esemény
- `POST /api/calculators/new-build`
- `POST /api/internal/calculators/new-build`
- `GET /api/calculators/renovation/catalog`
- `POST /api/calculators/renovation`
- `GET /api/housematch/catalog`
- `POST /api/housematch/match`

## Valós integrációs határ

A csomag tartalmazza a forrásregisztert, connector push szerződést, fájlfeldolgozást és teljes adatbefogadási folyamatot. Nem tartalmaz éles Gmail/Google Drive/Google Sheets OAuth-titkokat vagy korlátlan postafiók-hozzáférést. Az élő adaptereket kijelölt mappákra, címkékre, keresésekre és dátumtartományokra kell korlátozni, majd azok a `/api/imports/push` végpontra küldik a kinyert adatcsomagot.

## Tesztállapot

- 29/29 automatizált teszt sikeres;
- korábbi Control Center regressziós tesztek sikeresek;
- Import Center projekt- és pénzügyi E2E folyamat sikeres;
- commit és rollback sikeres;
- kalkulátor- és HouseMatch-forrásbetöltés sikeres;
- TenderMail domainkapu, szimulált küldés, suppression és egykattintásos leiratkozás sikeres.

## Workspace v1.0

A kezdőoldal most az egységes napi munkatér. A korábbi vezetői cockpit a `/executive` útvonalon érhető el.

Új útvonalak:
- `/` – személyes Workspace;
- `/tasks` – Action Center;
- `/projects/{ProjectID}` – Projekt 360°;
- `/documents` – dokumentumtár;
- `/search` – központi kereső.

Részletes leírás: `docs/WORKSPACE_V1_AS_BUILT.md`.

## Commercial Integration v1.0 – Reuse first

A rendszer kötelező fejlesztési szabálya: **sem modult, képernyőt, munkafolyamatot, adatmodellt, számítási motort, agentet, sablont vagy integrációt nem szabad kétszer elkészíteni.**

Minden fejlesztés előtt kötelező:

1. Drive-, modulregiszter-, release-regiszter-, traceability- és forrásartifact-keresés;
2. a kanonikus `ModuleKey`, objektumgazda, verzió és – ahol elérhető – SHA-256 azonosítása;
3. `reuse`, `extend`, `integrate`, `repair` vagy tulajdonos által jóváhagyott `new_exception` döntés;
4. a ténylegesen hiányzó funkció pontos rögzítése;
5. jóváhagyott discovery rekord nélkül a kiadás blokkolása.

Új útvonalak:

- `/commercial` – Contract Generator és ChangeControl közös, csak projekciós/orchestration munkafelülete;
- `/commercial/contracts/new` – a kanonikus Contract Generator v0.4 adaptere;
- `/development-governance` – discovery és újrafelhasználási napló.

Új API-k:

- `GET /api/commercial/source-status`;
- `POST /api/commercial/contracts/validate`;
- `POST /api/commercial/contracts/generate`;
- `POST /api/commercial/contracts/{contract_number}/signed`;
- `POST /api/commercial/change-events`;
- `GET/POST /api/development-discoveries`;
- `POST /api/development-discoveries/{discovery_id}/review`.

A Contract Generator üzleti motorja és masterei a Drive-ról visszatöltött v0.4 kiadásból származnak. A Workspace nem tart fenn második szerződésmotort. A ChangeControl esetében csak esemény- és állapotadapter készült; a scope, ár, fedezet, jóváhagyás, ügyféldöntés és munkakezdési engedély hiteles forrása továbbra is a ChangeControl.
