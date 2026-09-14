# HD-001 — Induló baseline

Dátum: 2026-08-10  
Állapot: RECORDED

## Repozitórium

- ág: `agent/houseplan-ui-v1`
- commit: `cd83840008f42d20e14772fda7645989249129ba`
- Alembic head: `20260809_0049`
- regisztrált modul: 47
- `house-designer`: nincs
- ügyfél oldali szabad alaprajzszerkesztő: nincs
- telekspecifikus, bizonyítékalapú országos + helyi compliance engine: nincs
- ügyfél promptos látványterv-revízió: nincs

## Meglévő alapok

- HousePlan deterministic generation és review;
- BuildConfig teljes belső konfigurációs workflow;
- HouseVision geometry-lock és QA-alapok;
- booking, intent, reservation és CRM handoff;
- MyImperial esemény- és projektvetület;
- audit/outbox és adatbázis-migrációs keret.

## Minőségi baseline

- `python -m alembic -c alembic.ini heads`: PASS, `20260809_0049`.
- `python -m compileall -q app`: a feature előtti állapoton futtatva; az új/módosított Python fájlok külön `py_compile` ellenőrzése PASS.
- globális `python -m ruff check app tests`: FAIL nagy mennyiségű, már a feature előtt meglévő legacy eltéréssel; ez külön technikai adósság, az új fájlok lintkapuja zéró eltérés.
- a többmodulos célzott regressziós csomag 120 másodperc után timeoutot ért el a helyi környezetben, ezért nem jelölhető PASS-nak.
- új House Designer fájlok `ruff check` és `ruff format --check`: PASS.
- geometriai smoke: PASS; overlap/out-of-footprint és több szint/core ellenőrizve.
- adatbázis service transaction: create → revision → idempotent replay PASS.
- friss SQLite migráció `0001 → 0050`: PASS, 204 tábla; az izolált adatbázis ellenőrzés után törölve.
- modul-katalógus: 49 egyedi ID, mindkét új modulkulcs jelen van, PASS.
- Jinja template syntax: PASS.

## 2026-08-10 végrehajtási bizonyíték

- `20260810_0050` friss SQLite migráció továbbra is PASS; a közös `0001 → 0051` futásban is hibamentes.
- HousePlan → House Designer adapter: jóváhagyott/katalógus/publikált tervből milliméterpontos, szerkeszthető geometria; unsupported geometry fail-closed; izolált smoke PASS.
- sandbox BuildConfig/kapacitás adapter: immutable, idempotensen visszaolvasott ár- és ütemsnapshot; `non_production=true`; adatbázis-tranzakció PASS.
- sandbox HouseVision: geometriához hash-kötött, prompt-revíziós, jogosultságvédett, vízjeles SVG; adatbázis-tranzakció és render-integritás PASS.
- hitelesített House Designer route korábbi smoke PASS; új Python fájlok célzott Ruff és `py_compile` PASS.
- éles pricing/capacity/render és order submission továbbra is fail-closed; sandbox eredményből megrendelés nem készülhet.
- a session/detail/command/check/estimate/render `/api/v1/house-designer` szelet elkészült; session-cookie write csak `application/json` + Origin + CSRF mellett, write idempotency és command If-Match kapuval működik.
- hitelesített JSON API create + render idempotens replay + eltérő payload collision smoke PASS; hiányzó CSRF/Idempotency-Key/If-Match regressziós tesztben rögzítve.
- a szerkesztő minden 1–3 szint alaprajzát megjeleníti; képernyőről elérhető a kontúr, helyiség létrehozás/mozgatás/méretezés/törlés, szint hozzáadás/törlés, tető és északi tájolás. A destruktív gombok megerősítést kérnek, a szerver minden műveletet atomi geometriai kapun ellenőriz.
- elkészült a Háztervező szabályozási adminisztráció: megváltoztathatatlan forrássnapshot, külön szerző/reviewer, négy-szem elv, végrehajtott tesztvektor, verziózott szabálykészlet és bizonyítékhoz kötött telekazonosítás.
- a telekigazolás új immutable tervrevíziót hoz létre; az ismételt parancs idempotens, az azonos kulcs eltérő bizonyítékkal fail-closed `409` ütközés.
- szabályozási service teszt: forrás → jóváhagyás → értelmezés → review → szabálykészlet → telekigazolás → compliance `PASS`; saját rekord jóváhagyása és hibás tesztvektor negatív ágon ellenőrizve.
- bejelentkezett felületi szerepkörteszt: `platform-admin` csak olvas, `technical-prep` szerző, `legal` szerző + reviewer; jogosulatlan műveleti űrlap nem renderelődik.
- friss SQLite migráció `0001 → 0052`: PASS, 218 tábla; a külön additív szabályozási és telekigazolási migráció mezőszinten ellenőrizve.
- meglévő `0051` séma → `0052` upgrade: PASS; a korábbi, jóváhagyási bizonyíték nélküli forrás automatikusan `captured/pending_review` karanténba került, az üzleti rekord megmaradt.
- az ügyfél az aktuális PASS megfelelőséget, ár- és ütemsnapshotot, valamint kiválasztott látványt egy manifest-hashhez kötött, megváltoztathatatlan tervcsomagként hagyhatja jóvá; más felhasználó ezt nem teheti meg.
- a jóváhagyott tervből a központi Booking motor publikált idősávjára konzultáció foglalható; a foglalás Smart Calendar rekordot és CRM/lead-intelligence irányú eseményt hoz létre, idempotens visszajátszással.
- az éles megrendelési kapu sandbox ár, ütem vagy látvány esetén zárva marad; kizárólag hatályos entitlement és mindhárom produkciós adapter bizonyítéka mellett nyílhat ki.
- Háztervező approval/consultation teszt: jóváhagyás → idempotens replay → foglalás → Calendar/CRM handoff PASS; sandbox order, idegen tulajdonos és hiányzó compliance negatív kapu PASS.

## Baseline-korlátok

Az élő adatbázis és a szerver változatlan marad, amíg a specifikáció és terv nulla P0/P1 blokkolóval nem fagyasztható. A migráció additív; meglévő üzleti rekordot nem írhat át és downgrade nem dobhat el új üzleti adatot.
