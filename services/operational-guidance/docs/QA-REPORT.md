# QA-jelentés

Dátum: 2026-07-23
Verzió: 0.5.0

## Automatikus ellenőrzések

- Python bytecode-fordítás: sikeres az `app`, `scripts`, `tests` és `wordpress-fleet` kódon.
- Pytest: **37 teszt sikeres**.
- Függőségek letöltése nélküli Python wheel build: sikeres.
- JSON-fájlok betöltése: sikeres.
- 11 generált Docker Compose YAML betöltése: sikeres.
- Shell setup scriptek szintaktikai ellenőrzése: sikeres.
- A plugin-template és minden generált PHP-fájl `php -l` ellenőrzése: sikeres.
- Python–PHP HMAC kompatibilitási teszt: sikeres UTF-8 és tizedes tartalommal.
- Brand Registry validáció: 11 márka, 22 publikációs cél és 11 WordPress-blog.

## Tesztelt elkülönítési szabályok

- minden márka saját WordPress-stacket kap;
- minden stack saját MariaDB-volume-ot használ;
- minden stack saját WordPress- és médiavolume-ot használ;
- minden stack saját Docker Compose projectet és networköt használ;
- nincs WordPress Multisite;
- a 11 author login egyedi;
- a 11 megjelenített szerzőnév egyedi;
- a 11 author email egyedi;
- minden blog saját `website_key` értékkel rendelkezik;
- a Hub a Directus `brand_key` és a céloldal márkája közti eltérést blokkolja;
- a WordPress plugin fejléc-, payload- és tartalomszinten is ellenőrzi a márkát;
- a plugin nem fogad el bejövő szerzőfelülírást;
- másik márka domainje vagy neve esetén a publikálás elutasítható;
- a featured image csak márkánként engedélyezett médiahostról tölthető le;
- az admin státusz API nem adja vissza a publikációs titkokat vagy a szerzői emailt.

## Tesztelt publikációs funkciók

- webhook HMAC-aláírás létrehozása és ellenőrzése;
- manipulált és lejárt kérés elutasítása;
- nyers JSON-törzs azonos aláírása Python és PHP környezetben;
- Directus státusz- és márkaellenőrzés;
- WordPress-cikk létrehozás és idempotens frissítés kódútvonala;
- automatikus szerző-hozzárendelés;
- kategória- és címkekezelés;
- SEO-leírás tárolása és megjelenítése;
- automatikus unpublish `draft` állapotba;
- külön WordPress runtime targetek felvétele a központi céljegyzékbe.

## Biztonságos alapállapot

A `config/website-targets.json` minden weboldalt és blogot `enabled: false` állapotban tart. Publikáció csak a tényleges URL, az adott blog saját HMAC-kulcsa és a staging teszt lezárása után engedélyezhető.

A `wordpress-fleet/provision_secrets.py` márkánként külön véletlen adatbázis-, admin- és publikációs titkot hoz létre. A létrejövő `.env` fájlok nem kerülnek a csomagba és nem verziókezelhetők.

## Ebben a futtatási környezetben nem végrehajtható

- a 11 Docker Compose stack tényleges indítása, mert Docker nincs telepítve;
- éles DNS-, TLS- és WordPress-domain konfiguráció;
- éles vagy teszt Google-, ingatlan.com- és weboldali API-hívás, mert hozzáférési adatok nem állnak rendelkezésre;
- teljes Ruff-futtatás, mert a környezet csomagforrásában a Ruff nem volt elérhető.

A WordPress runtime- és böngészős vizsgálatot stagingben a `docs/WORDPRESS-FLEET.md`, `docs/ACCESS-CHECKLIST.md` és `docs/DEPLOYMENT.md` szerint kell lezárni.

## Operational Guidance Engine kiegészítő QA

- 99/99 ProcessID és checklist-sablon egyértelmű összerendelése;
- 19 folyamatcsalád teljes lefedettsége;
- csak az öt valós munkakör használata;
- Process Card és checklist közös record sink;
- blocking NEM → HOLD, felelős és határidő;
- evidence-, submit-, approval- és CLOSED kapu;
- checklist-változás által kiváltott Process Card-verzióváltás;
- 99 Process Card és 99 checklist teljes PDF/PNG-generálása;
- 396 artefaktum gépi ellenőrzése, 0 hiba.

A production Directus–Gmail–Drive end-to-end UAT hitelesítő adatok nélkül továbbra sem végrehajtott; ez nem része a helyi PASS állításnak.
