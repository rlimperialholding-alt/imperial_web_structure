# HD-001 — Élő implementációs és readiness terv

Állapot: **IN PROGRESS / SANDBOX-READY SLICE / PRODUCTION BLOCKED**

Spec: `docs/specs/HD-001-house-designer-v1.0.md` (FROZEN)

Utolsó egyeztetés: 2026-08-14, exact code commit `78e865bce5c5214deae1f81c5e297a03f4515262`

## Release-döntés

A standalone és beágyazott szerkesztő belső/szintetikus sandbox használatra elérhető. A teljes House Designer production release és az éles `ORDER_REQUEST` fogadás **nem engedélyezhető**. A következő külső és belső bizonyítékok hiányoznak:

- szakmai/jogi tulajdonos által jóváhagyott TÉKA/OTÉK/HÉSZ forrás- és provenance-csomag;
- azonosított production render, pricing és capacity provider credential, friss health és provider QA;
- teljes CRM–Booking–MyImperial idempotens E2E;
- teljes WCAG 2.2 AA, billentyűzetes, böngészőmátrix- és reszponzív bizonyíték;
- PostgreSQL migrációs dry run, Hetzner-only backup/restore és deploy utáni smoke. Az exact code commit teljes regressziója zöld, de nem helyettesíti ezeket a környezeti release-kapukat.

Fail-closed runtime alapállapot:

- `HOUSE_DESIGNER_ADAPTERS_ENABLED=false`;
- `HOUSE_DESIGN_ORDER_INTAKE_ENABLED=false`;
- sandbox estimate/render `non_production=true`, és approval/order célra nem használható.

## Munkacsomagok valós állapota

| WP | Bizonyított implementáció | Nyitott rés / kapu | Állapot |
|---|---|---|---|
| WP-HD-01 — adatmodell és migráció | Session, immutable revision/snapshot, site, regulatory, render, estimate, schedule, submission, durable submission decision, entitlement, adapter és guest modellek; `20260810_0050`–`20260813_0065`. A teljes Alembic-lánc friss SQLite DB-n 0065-ig PASS, az új decision tábla 17/17 oszlopa egyezik. | Exact jelenlegi commit PostgreSQL migration dry run és rollback-bizonyíték még szükséges. | RÉSZBEN BIZONYÍTOTT |
| WP-HD-02 — geometria és command engine | Canonical hash, optimistic concurrency, idempotencia, geometriai negatív tesztek, template import és audit; korábbi verzió visszaállítása új immutable revisionként működik, replay-safe. | A frozen spec teljes 1/2/3 szint + attic elfogadási mátrixát egyetlen traceability futásban még össze kell zárni. | RÉSZBEN BIZONYÍTOTT |
| WP-HD-03 — szabályforrás és compliance | Four-eyes source/interpretation/ruleset workflow; source/ruleset revoke; PostgreSQL advisory scope lock; latest source/interpretation binding ellenőrzés; megváltozott vagy visszavont kötés új futásnál `UNKNOWN/RULESET_CHANGED`; finding evidence megjelenik a UI-n. | A Drive-hivatkozás önmagában nem jogi jóváhagyás. A tényleges TÉKA/OTÉK/HÉSZ tartalom, felhasználási jog, verzió, hatály és szakmai tulajdonosi approval nincs ebben a slice-ban igazolva. | KÓD BIZONYÍTOTT, JOGI/PROVENANCE BLOCKED |
| WP-HD-04 — session, jogosultság és telekadat-védelem | Owner/tenant/brand scope, guest expiry/claim/replay védelem, CSRF/Origin, audit. Staff olvasás aktív `ii.house-designer.read` ITEP project/global grant alapján; project deny elsőbbséget élvez; platform-admin nem kap automatikus üzleti session-hozzáférést. Az exact cím/HRSZ mezők külön House Designer KEK alatti AES-256-GCM envelope-ban kerülnek a revision JSON-ba; az envelope AAD-ja revision ID-hez és tartalomhashhez kötött. Az induláskori, tranzakciós cutover a legacy plaintext revisionöket titkosítja, az igazolási HRSZ-oszlopot kulcsolt tokenre cseréli, a kanonikus tervhash változatlan marad. A HTML/API olvasás értékmentes hozzáférési auditot ír; a production adapter várólista szintén csak titkosított telekadatot tárol és csak hitelesített küldéskor fejti vissza. | Production ITEP grant-replica hálózati E2E és revocation-latency mérés még szükséges. A PostgreSQL cutover, kulcsrotáció/crypto-erase, valamint a teljes retention/export/deletion workflow még nincs bizonyítva; ezért NFR-HD-008 nem tekinthető teljesnek. | RÉSZBEN BIZONYÍTOTT |
| WP-HD-05 — ügyfél UI | Standalone + embedded UI, site/config/geometry/compliance/render/estimate/approval/consultation/order felületek; revision history és restore. A site/config mezők 1,2 s-os autosave-ot kaptak. Hálózati megszakadáskor a teljes parancsboríték AES-256-GCM-mel, nem exportálható és IndexedDB-ben tárolt `CryptoKey` használatával kerül helyi sorba; CSRF-token és cookie nem része a tárolt rekordnak, plaintext `localStorage` fallback nincs. Visszakapcsoláskor az idempotens parancsok sorban futnak, külső stale revision esetén automatikus rebase helyett explicit konfliktus UI marad. Másik actor saját érvényes CSRF mellett is 404-et kap a vendég tervére. A részleges cím/település draft megmarad, miközben településkód + helyrajzi szám nélkül `verificationStatus=missing`. Chromium UAT: offline v1→v2 flush, külső v3 konfliktus, függő sor megtartás/elvetés, nem exportálható kulcs, 390 px-en 0 overflow, egy `main`, 44 px input/button célok. A közös UI kapott billentyűzettel látható fókuszkeretet, skip linket, címkézett menü/kereső/navigáció landmarkokat és a House Designer oldalak 44 px-es induló vezérlőket, valamint státusz/aside accessible neveket. | A browser-control kernel asset hibája miatt az új fókusz- és landmark-javítások interaktív böngészős újramérése nem készült el. Kézi keyboard, screen reader, 200% zoom, több böngésző és további viewport UAT kell. A böngésző eredet tárhelyének elvesztése vagy felhasználói törlése ellen a helyi pending sor természeténél fogva nem garantálható. | KÓD ÉS KORÁBBI CHROMIUM UAT BIZONYÍTOTT, ACCESSIBILITY MATRIX OPEN |
| WP-HD-06 — BuildConfig/HouseVision/ár/idő | Sandbox adapterek explicit nem production; production adapter contract signed, four-eyes, timeout/retry/idempotency/fail-closed; approval és order gate tiltja a non-production snapshotot. Readiness csak 15 percen belüli `HEALTHY` adaptert fogad el. | Valódi provider credential, költségkeret, terhelési/QA és üzemeltetési bizonyíték nincs; production flag OFF. | SANDBOX BIZONYÍTOTT, PRODUCTION BLOCKED |
| WP-HD-07 — ORDER_REQUEST és integrációk | Approval snapshot, consent, consultation a kanonikus Booking Engine-en; order létrehozás tranzakcióban, dedupe kulccsal és integrációs eseménnyel. Külön runtime order-intake kill switch került a DB entitlement elé. Elkészült az explicit project-scope-os queue/detail UI és API, durable append-only decision napló, optimistic row version, idempotens transition, customer cancel, sales/design/compliance/pricing lane, friss review-ciklushoz kötött és külön személyeket követelő acceptance gate. A lokális böngészős UAT owner → legal → finance → designer szerepkörökkel `RECEIVED → SALES_REVIEW → DESIGN_REVIEW → ACCEPTED` állapotot, öt auditdöntést és row v1→v6 változást bizonyított. | Pozitív production order E2E nincs; CRM/MyImperial fogyasztói idempotencia és valódi külső handoff nincs végig bizonyítva; ezért az order-intake flag OFF marad. | KÓD ÉS LOKÁLIS UAT BIZONYÍTOTT, PRODUCTION INTEGRATION BLOCKED |
| WP-HD-08 — standalone termék | Standalone shell, guest session/cookie/claim, ugyanazon domainen ugyanazon service layer; sandbox entitlement admin fail-closed. Az éles aktiválási kérelem pending állapotban nem írható felül más szerzővel; review pontos row-versionhöz és readiness-hashhez, suspend pontos row-versionhöz kötött. A stale form 409/redirect error mellett változatlanul hagyja az állapotot. Suspend lezárja a standalone flaget, production flageket és `valid_until` értéket; új kérelem csak friss versionből indul és a korábbi lejáratot törli. Four-eyes szerző/jóváhagyó elkülönítés megmaradt. | A repóban a Billingo kanonikus bejövőszámla read-only szinkronja látható, de House Designer-termék/SKU/payment entitlement contract nincs definiálva. Custom domain/DNS, jóváhagyott kereskedelmi termékdefiníció, billing-entitlement adapter és production entitlement UAT külső üzleti/integrációs kapu; meglévő API-secretet nem kell újrakérni, de önmagában nem entitlement-bizonyíték. | BELSŐ LIFECYCLE BIZONYÍTOTT, COMMERCIAL PRODUCTION BLOCKED |
| WP-HD-09 — release | Modul/nav/readiness felületek léteznek; runtime security és friss adapter-health readiness ellenőrzés; explicit adapter- és order-intake flag; a readiness manifest külön `site_data_encryption` checket tartalmaz, ezért hiányzó vagy a Market-kulccsal azonos site KEK mellett az aktiválás fail-closed és a readiness hash megváltozik. Exact `78e865bce5c5214deae1f81c5e297a03f4515262` code commit teljes suite 507 PASS. | Dedikált secret scanner, performance, PostgreSQL titkosítási cutover, Hetzner-only backup/restore, külön production site KEK létrehozása, pinelt image és deploy bizonyíték még nincs. A távoli core/worker image-eket közben más release-folyamat módosította, ezért új exact-state audit nélkül ez a commit nem deployolható. | NEM KÉSZ |

## Elfogadási feltételek nyomon követése

- AC-HD-001/002/019/020: meglévő geometry/API/guest tesztek részben bizonyítják; teljes traceability futás még kell.
- AC-HD-003/004/021: fail-closed compliance és ruleset/source binding/revoke tesztelve.
- AC-HD-009/022: stale/non-production gate-ek tesztelve; éles provider pozitív út külső kapu.
- AC-HD-010: az order és review idempotencia, collision, optimistic concurrency és ciklusfriss gate automatizált teszttel bizonyított. AC-HD-011 teljes pozitív production handoff E2E még nincs; nem tekinthető késznek.
- AC-HD-012: customer isolation és explicit project grant + deny-first negatív API teszt megvan; production ITEP E2E még kell.
- NFR-HD-003: az 1,2 s autosave, titkosított helyi pending sor, online replay és stale konfliktuskezelés Chromiumban bizonyított. Ez nem jelenti a teljes több-böngészős vagy accessibility elfogadást.
- NFR-HD-008: az exact cím/HRSZ at-rest titkosítása, legacy cutover, értékmentes hozzáférési audit és adapter-queue védelem kóddal és negatív teszttel bizonyított. A retention/export/deletion és crypto-erase/rotáció teljes életciklusa, valamint a production PostgreSQL cutover még nyitott.
- AC-HD-013: four-eyes regulatory és adapter/entitlement út tesztelve; entitlement review stale row-version/readiness-hash esetén fail-closed.
- AC-HD-015: a standalone, embedded és v1 API detail válasz erős `ETag` értéke ugyanabból a kanonikus revision hashből származik; a standalone/embedded paritás, a HTML-hash egyezés és a revision utáni ETag-változás automatizált teszttel bizonyított. A válaszok `private, no-cache` policyt használnak.
- AC-HD-016: a submission review minden belső state change-e append-only decision és központi audit/event rekordot ír; az internal workflow bizonyított. A külső fogyasztói auditlánc production E2E-je még nyitott.
- AC-HD-017: modul-regisztrációs teszt és exact `78e865bce5c5214deae1f81c5e297a03f4515262` code commit full suite 507 PASS.
- AC-HD-023: a felület `megrendelési igény` joghatást használ; a szövegezést legal review-nak is jóvá kell hagynia.

## Aktuális tesztbizonyíték

- AC-HD-015 célzott guest/API regresszió: **2 passed**, **7,70 s**. A teljes House Designer + regulatory szelet az ETag-javítás után **44 passed**, **474 deselected**, **109,11 s**; Ruff a módosított route- és tesztfájlon PASS. Ez worktree-bizonyíték, exact commit full-suite még szükséges.
- Korábbi baseline House Designer/regulatory célzott csomag: **33 passed**, 1 nem hibát okozó deprecation warning.
- A jelenlegi worktree átfedésmentes, fájlonként soros regressziója: **47 passed** — House Designer 28, regulatory 7, module readiness 2, security 9, signed ITEP House Designer permission replica 1. Minden futásban ugyanaz az egy, nem hibát okozó Starlette/httpx deprecation warning jelent meg.
- Lokális szintetikus böngészős role UAT: grant nélkül idegen projekt rejtve/404; aktív project allow mellett látható/200; későbbi project deny mellett ismét rejtve/404. Session létrehozás, új revision és immutable restore működött.
- Lokális vizuális/reszponzív UAT: 390 px viewportban nincs oldal-szintű vízszintes overflow; a látható interaktív elemek static name/target auditja zöld; böngészőkonzol 0 error és 0 warning.
- WP-HD-07 szintetikus, több-szerepkörös böngészős UAT: owner elindította és design review-ba továbbította a csomagot; legal kizárólag compliance, finance kizárólag pricing, designer kizárólag tervezői accept műveletet kapott. Végállapot `ACCEPTED`, row v6, öt döntési naplóbejegyzés, 390 px és 1440 px nézetben 0 horizontal overflow, egyetlen `main` landmark, 44 px minimum műveleti vezérlők, konzol 0 error/warning.
- WP-HD-07 célzott API/service/event regresszió: **22 passed**, 1 nem hibát okozó warning, **53,95 s**. A WP-HD-05 utáni teljes House Designer/regulatory/security/ITEP mátrix: **53 passed**, 1 warning, **74,82 s**.
- WP-HD-05 célzott API/guest/vertical regresszió: **12 passed**, 1 warning, **12,21 s**; külön végső scope/site negatív csomag **2 passed**, **2,56 s**. Ruff és a tartós editor JavaScript `node --check` PASS.
- WP-HD-05 headless Chrome UAT: AES-GCM ciphertext-only pending rekord; strukturált klónozással tárolt, `extractable=false` kulcs, amelynek raw exportja `InvalidAccessError`; offline autosave v1→v2; másik sessionből érkező v3 után 409/stale konfliktus és a helyi rekord megtartása; explicit elvetés után pending=0. Mobil 390×844 nézetben 0 px horizontal overflow, 44 px minimum célok és egyetlen `main`. A szándékos 409 és favicon 404 hálózati konzolbejegyzésen kívül 0 váratlan console warning/error/pageerror.
- WP-HD-08 lifecycle célzott service/UI regresszió: **4 passed**, 1 warning, **3,27 s**; teljes adapter–guest–security csomag: **22 passed**, 1 warning, **14,60 s**. A teszt bizonyítja a pending-request rewrite tiltását, stale row/hash visszautasítását, a HTML precondition mezőket, a felfüggesztési lezárást és a sandbox external-write flagjeinek OFF állapotát.
- WP-HD-04 adatvédelmi célzott csomag: privacy/API audit **4 passed**, adapter+privacy **12 passed**, a teljes House Designer/regulatory/guest/adapter/security szelet **55 passed**. Bizonyított a ciphertext-only revision és adapter queue, round-trip, tamper fail-closed, legacy cutover, HRSZ-tokenizálás, kanonikus hash megőrzése és értékmentes olvasási audit. A compose YAML-ellenőrzés igazolta a külön site KEK bekötését a core-ba és mindkét azonos image-et használó workerbe.
- Accessibility statikus/server-rendered regresszió: House Designer API/guest/security **19 passed**, 1 warning, **21,91 s**; skip link, main target, fókuszstílus, címkézett menü/kereső/navigáció és House Designer landmarkok HTML-assertjei PASS. A szintetikus localhost UAT readiness 200 volt, de a Browser skill kernel asset útvonalhibája reset után is megismétlődött, ezért interaktív browser claim nem készült. A 13320 PID leállítva, a célzott UAT SQLite és log fájlok eltávolítva, maradvány 0.
- Friss, izolált SQLite adatbázison a teljes Alembic-lánc `20260813_0065` headig PASS; az új `house_design_submission_decisions` tábla 17/17 elvárt oszlopa jelen van; a 7,7 MB-os teszt-DB ellenőrzés után törölve.
- Ruff az összes módosított Python fájlon: PASS; `compileall app tests`: PASS; `git diff --check`: PASS.
- A teszt harness az elkülönített `sqlite://` in-memory adatbázist `StaticPool`-lal használja; a 47 tesztes célzott csomag ezen **25,98 s** alatt PASS, és nem ír lokális DB-artefaktumot. A production PostgreSQL és a fájlos fejlesztői SQLite konfiguráció változatlan.
- Exact code commit `f44de5f890ef4ac06f29cbcf6ef8de15a680c3d4`: teljes platform-core suite **501 passed**, 5 nem hibát okozó warning, **504,33 s**. A PID-izolált pytest temp root session végén eltűnt; az UAT helyi DB/log/script és szerverfolyamat szintén célzottan törölve/leállítva. A leglassabb egyedi teszt 4,53 s volt.
- Exact code commit `c96195e0775520e51f38c1116c698d5883bd5683`: teljes platform-core suite **502 passed**, 5 nem hibát okozó warning, **439,43 s**. A PID-izolált pytest temp root session végén eltűnt; a leglassabb egyedi teszt 4,85 s volt.
- Exact code commit `e015d942d7978a3b1773746bef88f6188b7e6602`: teljes platform-core suite **506 passed**, 5 nem hibát okozó warning, **567,82 s**. A PID-izolált pytest temp root session végén eltűnt; a futás után 8,71 GB szabad hely maradt. Production deploy nem történt.
- Exact code commit `2b2354c9458e4fcede86e1ab03ecedd719dc013f`: teljes platform-core suite **506 passed**, 5 nem hibát okozó warning, **572,57 s**. A közös template/CSS módosítás után minden modul regressziója zöld; ez továbbra sem helyettesíti a nyitott kézi/screen-reader/browser-mátrixot. Production deploy nem történt.
- Exact code commit `78e865bce5c5214deae1f81c5e297a03f4515262`: titkosítási readiness célzott privacy/adapter/security csomag **22 passed**, 1 warning, **15,68 s**; teljes platform-core suite **507 passed**, 5 nem hibát okozó warning, **438,86 s**. Production deploy nem történt.

Ezek a kódszintű bizonyítékok nem helyettesítik a hiányzó környezeti, jogi és külső
integrációs release-kapukat, és önmagukban nem jogosítanak production deployra.

## Következő végrehajtási sorrend

1. A browser-control infrastruktúra helyreállítása után lezárni a WP-HD-05 fennmaradó kézi keyboard/screen-reader/200% zoom és több-böngészős accessibility mátrixát; az autosave/offline/conflict út és a statikus fókusz/landmark javítás már bizonyított.
2. A WP-HD-08 production entitlementet csak jóváhagyott House Designer termék/SKU/payment contract és azonosított Billingo-fogyasztói folyamat után E2E-zni; custom domain/DNS és production entitlement külső kapu marad.
3. A WP-HD-07 külső CRM/MyImperial fogyasztói idempotencia és production handoff E2E-jét csak azonosított fogyasztóval, jóváhagyott credentiallel bizonyítani; addig order-intake OFF.
4. A jogi/provenance tulajdonostól tényleges jóváhagyást kérni a szabályforrásokra; jóváhagyás nélkül a compliance production kapu zárva marad.
5. Azonosított provider és credential után külön production adapter QA; addig flag OFF.
6. Dedikált secret scan, performance, külön production House Designer site KEK előállítása, PostgreSQL titkosítási cutover dry run, Hetzner-only backup/restore, új remote exact-state audit, pinelt release és csak ezután külön deploy-döntés.

## Minden WP Definition of Done

- frozen AC traceability és negatív teszt;
- tenant/brand/project deny-first scope;
- minden write audit, idempotencia és concurrency bizonyíték;
- ruff/compile/targeted pytest, majd exact-commit full suite;
- migráció/rollback és adatmegőrzési hatás dokumentált;
- sandbox/mock sehol nem productionként jelölt;
- külső jogi, credential- vagy publication-kaput kód nem kerül meg;
- ideiglenes tesztartefaktum nem marad a release-ben.
