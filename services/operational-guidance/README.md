# Imperial Intelligence Integration Hub

## v0.8.1 staging handoff hotfix

The remote staging deploy/rollback path was corrected so all internal-service checks run inside the Compose network, releases use one stable Compose project, and each release receives its own application image tag. See `docs/RELEASE-NOTES-v0.8.1.md`.


Működő induló kódbázis az Imperial Intelligence külső adatkapcsolataihoz és korlátlan számú márka, domain és egyedi weboldal központi, jóváhagyott tartalomfrissítéséhez.

## Elkészült modulok

### GA4 Data API

Három külön riportot szinkronizál, hogy a különböző scope-ú adatok ne keveredjenek:

- oldalviselkedés: megtekintések, aktív felhasználók, key eventek, engagement idő;
- akvizíciós csatornák: sessionök, felhasználók, engaged sessionök, key eventek;
- landing oldalak: sessionök, engagement és key eventek.

A nagy riportokat automatikusan lapozza, és a napi rekordokat idempotensen tárolja PostgreSQL-ben.

### Google Search Console

Dátum, keresőkifejezés, oldal, ország és eszköz szerint tárolja:

- kattintás;
- megjelenés;
- CTR;
- átlagos pozíció.

### Google Business Profile

- hozzáférhető accountok és irodák listázása;
- irodai cím, telefonszám, weboldal és nyitvatartás szinkronja;
- Search és Maps megjelenések;
- weboldal-, hívás- és útvonaltervezési műveletek;
- értékelések lekérése és helyi adatbázisba mentése;
- értékelésre válasz;
- helyi bejegyzés létrehozása.

### ingatlan.com Automata Betöltés

- JWT-bejelentkezés és automatikus tokenfrissítés;
- hirdetéslista, lekérés, létrehozás/módosítás és törlés;
- hirdetésazonosítók és státuszok helyi szinkronja;
- fotólista, feltöltés, törlés és sorrendezés;
- `ownId` és fotóazonosító validáció;
- saját/távoli azonosítók és utolsó payload naplózása.

### Directus Content Hub és weboldali publikálás

- fájlból vagy környezeti változóból bővíthető többmárkás Brand Registry;
- egy márkához több weboldal, domain vagy nyelvi változat kapcsolható;
- márkák, weboldalak és verziózható tartalmi elemek;
- ár-, SEO-, média-, jogi, jóváhagyási és időzítési mezők;
- `draft → review → approved → published → archived` folyamat;
- kizárólag Directusból visszaellenőrzött `approved` tartalom publikálható;
- több weboldalas batch csak teljes siker után lesz `published`;
- `valid_from` szerinti időzített publikálás;
- `valid_until` után 15 percen belüli automatikus unpublish;
- oldalanként külön HMAC-secret, nyers kérés-törzs aláírás és ötperces replay-védelem;
- célzott Next.js `revalidatePath` és `revalidateTag`;
- publikációs státusz, válasz és hiba naplózása.

### Önálló WordPress-blogok

- 11 különálló WordPress + MariaDB stack, WordPress Multisite nélkül;
- márkánként saját adatbázis, fájlrendszer, médiatár, hálózat és titkos kulcs;
- márkánként egyedi szerzői login, megjelenített név és e-mail;
- külön, márkázott blokk-téma és színpaletta;
- HMAC-hitelesített `/wp-json/imperial/v1/articles` publikációs végpont;
- Hub- és WordPress-oldali `brand_key` ellenőrzés;
- keresztmárkás domainhivatkozások automatikus tiltása;
- generátor és véletlen secret-provisioning a `wordpress-fleet` mappában.

### Operational Guidance Engine – Process Card + Checklist

- egyetlen kanonikus folyamatkatalógus 99 ProcessID-val és 99 checklist-sablonnal;
- kizárólag öt valós belső munkakör: Ügyvezető, Marketinges, Értékesítő, Pénzügyes, Projektmenedzser;
- emberi nyelvű, egyoldalas Process Card PDF/PNG/JSON;
- ugyanahhoz a folyamathoz kapcsolt, végrehajtható IGEN / NEM / N.A. checklist;
- blocking NEM válasznál automatikus HOLD, javítási felelős és határidő;
- evidence-, beküldési-, jóváhagyási- és CLOSED kapu;
- közös Directus-adatcsatorna, ügyvezetői approval, verziózott Drive-publikálás;
- folyamat- vagy checklist-szabály változásakor csak az érintett csomag újragenerálása;
- Directus webhook, 15 perces Celery safety-net és n8n referenciamunka.

### Production control plane v0.8.1

- pontosan öt emberi munkakörhöz külön Bearer-tokenes jogosultság;
- service-tokenes n8n/Directus integráció, emberi szerepkör létrehozása nélkül;
- ügyvezető-only Process Card- és checklist-jóváhagyás;
- munkakörhöz kötött checklist-végrehajtás;
- idempotens checklist-indítás és kulcsütközés-védelem;
- `X-Request-ID`, strukturált kérésnapló és PostgreSQL audit trail;
- tokennel védett Prometheus `/metrics`;
- trusted-host, CORS, request-size és production docs-kontroll;
- operációs státusz- és auditlekérdezés;
- backup, SHA-256 ellenőrzés és nem destruktív restore drill;
- production preflight, canary, verziózott deployment és application-image rollback.
- háromfolyamatos online staging UAT Drive-, Gmail-, Directus- és szerepkör-bizonyítékokkal;
- távoli, verziózott staging telepítő, amely csak teljes GO után aktiválja az új release-t.

### Infrastruktúra

- FastAPI vezérlő API;
- PostgreSQL;
- Redis és Celery worker/beat;
- Directus;
- n8n;
- MinIO/S3;
- Docker Compose.

## Indítás

```bash
cp .env.example .env
mkdir -p secrets
# secrets/google-service-account.json

docker compose up -d --build
```

Helyi felületek:

- API és Swagger: `http://localhost:8000/docs`
- Directus: `http://localhost:8055`
- n8n: `http://localhost:5678`
- MinIO: `http://localhost:9001`

Directus indulása után, a hoston telepített Python-függőségekkel vagy az API konténerben:

```bash
python scripts/bootstrap_directus.py
```

A script létrehozza a kollekciókat, majd a `config/brand-registry.json` teljes márka- és weboldaljegyzékét felviszi vagy frissíti. A Flow beállítása: `docs/DIRECTUS-FLOW.md`.

## Hozzáférések

### GA4 és Search Console

1. Engedélyezd a Google Analytics Data API-t és Search Console API-t.
2. A service account e-mail-címét add hozzá minden GA4 és Search Console propertyhez.
3. Másold a kulcsot `secrets/google-service-account.json` néven.
4. Töltsd ki a `GA4_PROPERTIES_JSON` és `SEARCH_CONSOLE_SITES_JSON` változókat.

### Google Business Profile

A GBP felhasználói OAuthot igényel. A kliensazonosító és titok megadása után a refresh token előállítható:

```bash
python scripts/google_business_oauth.py
```

Ezután töltsd ki a `GOOGLE_OAUTH_REFRESH_TOKEN` és `GBP_LOCATIONS_JSON` változókat. Az account- és location-ID-k az API discovery végpontjain lekérhetők.

### ingatlan.com

Elsőként az `https://apitest.ingatlan.com/v1` környezetet használd. Éles működéshez az ingatlan.com által biztosított Automata Betöltés hozzáférés, tesztfiók és lezárt mezőmapping szükséges.

## Fontos API-végpontok

Az elsődleges hitelesítés `Authorization: Bearer <token>`. Az emberi végrehajtás az öt munkakör egyikéhez kötött, a gépi integrációk külön service tokent használnak. Az `X-Imperial-Token` fejléc csak átmeneti kompatibilitási út. A pontos mátrix: `docs/AUTHORIZATION-MATRIX-v0.7.0.md`.

- `GET /api/v1/brands`
- `GET /api/v1/brands/{brand_key}`
- `POST /api/v1/sync/ga4`
- `POST /api/v1/sync/search-console`
- `POST /api/v1/sync/google-business`
- `POST /api/v1/sync/google-business/directory`
- `GET /api/v1/sync/google-business/accounts`
- `GET /api/v1/sync/google-business/{account}/{location}/reviews`
- `PUT /api/v1/sync/google-business/{account}/{location}/reviews/{review}/reply`
- `POST /api/v1/sync/google-business/{account}/{location}/posts`
- `GET/PUT/DELETE /api/v1/ingatlan/ads/...`
- `PUT/DELETE /api/v1/ingatlan/ads/{ownId}/photos/...`
- `POST /api/v1/publications`
- `POST /api/v1/publications/webhooks/directus`
- `POST /api/v1/process-cards/catalog/import`
- `POST /api/v1/process-cards/{process_key}/generate`
- `POST /api/v1/process-cards/{process_key}/versions/{version}/approve`
- `POST /api/v1/process-cards/{process_key}/checklists/start`
- `GET/POST/PUT /api/v1/checklists/...`
- `POST /api/v1/process-cards/webhooks/directus`

Példák az `examples` mappában találhatók.

## Regisztrált márkák

A csomag jelenleg az alábbi 11 márkát tartalmazza:

- Imperial Holding;
- Danish Fabrik;
- Bautica;
- Prefab;
- Timberhaus;
- Casa Moderna;
- Property 360;
- Everyday Homes;
- Family Homes;
- Budapesti Magasépítő Vállalat;
- RED Property.

A lista nem kódszintű korlát. Új márka vagy további domain a `config/brand-registry.json` és `config/website-targets.json` módosításával vehető fel. Az ismeretlen URL-lel rendelkező oldalak `pending_configuration` állapotban vannak, és addig nem publikálhatók, amíg a pontos domain, fogadóvégpont és egyedi HMAC-kulcs nincs beállítva.

## Weboldali beépítés

A `website-sdk/nextjs` mappa tartalmazza a fogadómodult és a kész route-ot. Más technológiánál ugyanaz a szerződés:

1. `POST /api/internal/content-publish`;
2. `X-Imperial-Timestamp` és `X-Imperial-Signature` ellenőrzése;
3. payload átvétele;
4. cache/read-model frissítés;
5. JSON visszajelzés.

A Hub nem kap FTP- vagy közvetlen weboldali adatbázis-hozzáférést.

## Ellenőrzés

```bash
python -m pip install -e '.[dev]'
pytest -q
python scripts/static_check.py
python scripts/verify_connections.py
python scripts/import_operational_catalog.py
python scripts/operational_guidance_demo.py
python scripts/qa_operational_guidance.py --output runtime/operational-guidance-qa
python scripts/production_gate.py --env-file .env --output runtime/production-gate-v0.8.1.json
```

A kapcsolati ellenőrző csak a kitöltött integrációkat hívja meg.

## Dokumentáció

- `docs/ARCHITECTURE.md`: rendszer- és adatfolyamok;
- `docs/BRAND-REGISTRY.md`: márkák, domainek és új weboldalak felvétele;
- `docs/ACCESS-CHECKLIST.md`: jogosultsági ellenőrzőlista;
- `docs/DIRECTUS-FLOW.md`: jóváhagyási Flow;
- `docs/DEPLOYMENT.md`: élesítési runbook;
- `docs/INGATLAN-MAPPING.md`: ingatlan.com megfeleltetés;
- `docs/WORDPRESS-FLEET.md`: a 11 teljesen önálló blog telepítése és elkülönítése;
- `docs/QA-REPORT.md`: végrehajtott ellenőrzések és fennmaradó staging tesztek.
- `docs/OPERATIONAL-GUIDANCE-ENGINE.md`: a közös Process Card + checklist működési modell;
- `docs/PROCESS-CARD-GENERATOR.md`: generálás, jóváhagyás és verziózás;
- `docs/CHECKLIST-ENGINE.md`: checklist-adatmodell, HOLD és kapuszabályok;
- `docs/PROCESS-CARD-GENERATOR-QA.md`: 99/99 artefaktum- és funkcionális QA;
- `docs/AUTHORIZATION-MATRIX-v0.7.0.md`: az öt munkakör és a service identitások jogai;
- `docs/BACKUP-RESTORE-v0.7.0.md`: mentés, ellenőrzés és restore drill;
- `docs/PRODUCTION-UAT-v0.7.0.md`: production GO/NO-GO és canary;
- `docs/RELEASE-NOTES-v0.7.0.md`: a production-candidate változásai.

## Jelenlegi határ

Hozzáférési adatok nélkül nem történt éles Google-, Gmail-, Directus-, Docker-host-, ingatlan.com- vagy weboldali hívás. A v0.8.1 offline regressziós és 99/99 artefaktumkapu sikeres; a tényleges online staging UAT kizárólag valódi szerver- és Google/Directus-hozzáférésekkel hajtható végre. A Meta, Google Ads, Billingo és bank adapterekhez a közös adapter-, naplózási-, ütemezési- és secret-kezelési architektúra készen áll, de maguk az adapterek még nincsenek ebben a csomagban.

## Online staging UAT v0.8.1

A valós környezeti telepítés és három üzleti pilot teljes leírása: `docs/ONLINE-STAGING-UAT-v0.8.1.md`.

```bash
python scripts/credential_manifest.py
BASE_URL=https://staging.example.hu make online-staging-uat
```
