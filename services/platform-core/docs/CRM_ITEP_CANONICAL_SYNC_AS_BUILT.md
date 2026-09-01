# CRM–ITEP kanonikus szinkron – as-built és readiness

## Határ és adatirányok

A Platform Core nem írja felül kontroll nélkül a forrásrendszereket. A jelenlegi
kanonikus híd négy elkülönített műveletet valósít meg:

1. CRM és ITEP pénzügyi források olvasása `EnterpriseCanonicalRecord`
   rekordokba, stabil külső üzleti kulccsal és provenance-adattal;
2. platform-tulajdonú kanonikus rekordok checksumos, idempotens átadása a
   CRM-tükörbe, a CRM- és ITEP-tulajdonú rekordok visszhangjának tiltásával;
3. ITEP taskok SHA-256-ellenőrzött beolvasása, valamint platformesemények
   idempotens ITEP-átadása;
4. platform→CRM hash-alapú reconcile és külön kanonikus integritási riport.

Az import megőrzi a kézzel, pénzügyi szerepkörrel igazolt projektallokációt
akkor is, ha a forrásrekord később változik. Hibás lapozás, hibás checksum,
azonos verzióhoz tartozó eltérő tartalom és visszafelé haladó ITEP-verzió
fail-closed konfliktus.

## Jogosultság és biztonság

- A session UI sync/push/pull/reconcile műveletei kizárólag a regisztrált
  `owner`, `managing-director`, `platform-admin` szerepekkel indíthatók.
- Az internal API-k külön `INTERNAL_JOB_TOKEN` függőséget használnak.
- Az ITEP-kapcsolat rövid életű, nonce-os, HMAC-SHA-256 aláírt identity
  envelope-ot használ.
- A CRM read és write URL/token párok együtt kötelezők; a tokenek legalább 32
  karakteresek, a read/write és Sites-hozzáférési credentialek nem oszthatók
  meg egymással.
- CRM/ITEP konfliktus, távoli elutasítás, sikertelen kézbesítés vagy nem PASS
  reconcile esetén a UI és az internal API HTTP 409/502 választ ad. A delivery
  és az auditrekord a hiba ellenére megmarad.
- A 0070 migráció öt elkülönített adatbázis-lease-t seedel a CRM import/push/
  reconcile és ITEP pull/push műveletekhez. Az acquire egyetlen feltételes
  `UPDATE`, ezért nem lejárt tulajdonos mellett csak egy futás léphet tovább.
  A 15 perces lease 5 percenként megújul; folyamatkiesés után lejárattal
  visszavehető. A holder token megakadályozza, hogy egy régi futás az új
  tulajdonos lease-ét megújítsa vagy felszabadítsa. A generáció, heartbeat,
  contention és release időpontjai perzisztens operációs bizonyítékok.
- Busy lease HTTP 409, elveszett lease HTTP 503, és mindkettő külön auditált
  `canonical_sync.lease_*` esemény. Szolgáltatáshiba után a lease biztonságosan
  felszabadul, így a delivery-állapot megőrzése mellett újrapróbálható.

## Bizonyíték – 2026-08-16

- Célzott CRM–ITEP, route, credential és security regresszió: **31 passed, 1
  nem hibát okozó warning, 17,53 s**.
- A 0070 lease-szelet kibővített célzott regressziója: **37 passed, 1 nem
  hibát okozó warning, 24,76 s**. A friss adatbázis 0001→0070 migrációja és a
  lease-séma + öt seedelt kulcs verifier PASS.
- Az exact 0070 lease-változtatásokon futtatott teljes Platform Core
  regresszió: **570 passed, 5 nem hibát okozó warning, 739,48 s**. A futás
  pytest-cache és Python bytecode nélkül, külön JUnit-eredménnyel készült.
- Az exact CRM–ITEP változtatásokon futtatott teljes Platform Core regresszió:
  **562 passed, 5 nem hibát okozó warning, 457,98 s**. A futás pytest-cache és
  Python bytecode nélkül, külön JUnit-eredménnyel készült.
- Élő, read-only CRM canonical export checksum-smoke PASS a futó Hetzner
  konténerből: users 2/2, customers 5/1145 mintarekord, projects 3/3,
  contracts 0/0, invoices 5/151 és cashflow 5/159; minden visszaadott minta
  workspace-, source- és SHA-256-azonossága igazolt.
- Az import által használt külön `platform-export` contract elsőlapos,
  read-only smoke-ja minden konfigurált entitásnál érvényes listaválaszt adott;
  a `contracts` és `migration_documents` forrás jelenleg üres volt.
- A futó konténerben a CRM read/write és ITEP kapcsolat szükséges változói
  nem üresek, a CRM read és write credential egymástól különbözik. Secretérték
  nem került kiírásra.
- A távoli adatbázis összesített állapota 16 245 `applied` és 1 `superseded`
  kanonikus deliveryt, valamint 21 reconcile futást tartalmaz. A legutóbbi,
  2026-08-02 10:03:23 UTC-kor lezárt reconcile `passed`: 195 lokális rekordból
  195 egyezett, 0 hiányzó, 0 hash-eltérő és 0 konfliktusos rekord mellett.
  Ez történeti, az aktív szerverkiadáshoz tartozó production-bizonyíték, nem az
  új helyi commit exact deploy-utáni igazolása.

## Nyitott production kapuk

- Ebben a szeletben élő platform→CRM írás vagy teljes roundtrip nem futott;
  ezért a write receipt és a zero-diff reconcile még nem bizonyított az új
  exact kódon.
- A lease kód- és SQLite recovery/negatív bizonyítéka elkészült; tényleges,
  két párhuzamos klienssel futtatott PostgreSQL concurrency UAT csak a 0070
  Hetzner-migráció és exact image deploy után végezhető el.
- A forrásból eltűnt vagy törölt CRM-rekordok tombstone/retention szerződése
  nincs ebben a repóban hitelesen dokumentálva; enélkül automatikus törlés vagy
  archiválás nem vezethető be.
- A helyi commit szerverre telepítése előtt Hetzner-only adatbázismentés,
  restore-list ellenőrzés, exact image pin, core/worker/gateway újralétrehozás,
  belső és publikus smoke, majd logellenőrzés szükséges.

E kapuk miatt a kapcsolat olvasási oldala és a helyi üzleti szerződés
bizonyított, de a kétirányú production roundtrip még nem minősíthető késznek.
