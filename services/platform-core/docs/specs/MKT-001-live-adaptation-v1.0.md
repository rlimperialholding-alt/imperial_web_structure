# MKT-001 — Market & Creative Intelligence élő adaptáció v1.0

Állapot: FROZEN  
Modulkulcs: `market-creative-intelligence`  
Útvonal: `/market-intelligence`  
Kanonikus tartalmi forrás: Drive `10sdAJme3LJjs8pnHd7hIjAin979ofCq5_DsqEqn4zqA`, revision `AIroW37Z2kzCHtlWQLw7VfkSYdje626nCM0Ddp0G-XmMH5Pxxi25SHI-5UuvdxMOvj6Qbf-a-5y0fNU8dKzajsCf2I9_Fu-kw-_omlMmttfc` (ellenőrizve: 2026-08-11)

Ez a dokumentum az élő platformhoz szükséges normatív delta; ellentmondás esetén a Drive master üzleti szerződése és a szigorúbb biztonsági kapu irányadó.

## 1. Modulhatár

MCI MUST külön research/evidence layer legyen. MUST NOT közvetlenül:

- tartalmat publikálni;
- hirdetést, e-mailt vagy kampányt indítani;
- költést, bidet, célzást vagy CRM státuszt módosítani;
- ellenőrizetlen következtetést tényként downstream továbbadni.

Az összes production connector default OFF. Engedélyezése connectoronként külön release-bizonyítékot és kill switch-et igényel.

## 2. Objektumok

### SourceTarget

Tenant/brand/market scope, forrástípus, normalizált origin/domain, engedélyezett path, capture mód, jogalap/rights státusz, robots/policy, PII policy, rate limit, retention, státusz és author/approver.

Revisionált aggregate: `DRAFT → IN_REVIEW → APPROVED → REVOKED|SUPERSEDED`. Author != approver. Capture csak jurisdiction/target parent `FOR UPDATE` lock után latest APPROVED revisionnel indulhat; a job rögzíti target revision és policy hash értékét, majd minden hálózati kérés/redirect és snapshot commit előtt újraellenőrzi. Változás `target_changed` fail-closed állapot.

### CaptureJob

Idempotens feladat egy targetre: request policy snapshot, státusz `QUEUED|RUNNING|SUCCEEDED|PARTIAL|FAILED|CANCELLED`, attempts, költség/limit, hiba, audit.

### SourceSnapshot

Immutable: resolved URL, captured_at, HTTP metadata, MIME, storage ref, content SHA-256, normalized text hash, policy hash, parser version, provenance, privacy classification. Azonos target+content hash újraolvasása nem hoz létre tartalmi duplikátumot.

A nyers blob envelope-encryptionnel tárolt. PII/secret/jogi törléskor a blob kulcsa crypto-erasure alá kerül, a snapshot immutable metadata marad, és külön append-only `EvidenceRedaction`/tombstone tartja a jogalapot, scope-ot, actor/reviewer és időpontot. Minden olvasó a redaction állapotot ellenőrzi; erased/quarantined snapshot tartalma nem olvasható és új packba nem tehető.

### MarketAsset

Snapshotból kinyert reklám/landing/creative/offering objektum, brand/market/channel/type, source offsets/refs, detected claims, CTA, offer, format, media metadata és extraction version.

### Observation és VOCSignal

Mindkettő forrás-spanhoz kötött. Evidence level csak `OBSERVED|INFERRED|VALIDATED_INTERNAL`. Az inference MUST tartalmazzon módszert, confidence-et és supporting source IDs-t. VOC személyes adatot nem őrizhet szükségtelenül; idézet rövid, maszkolt és provenance-kötött.

### PatternCluster és member

Verziózott klaszter membership, algoritmus/model version, inclusion/exclusion, summary, confidence. Új futás új revision; történetet nem ír felül.

### ResearchHypothesis

Állítás, célközönség, brand/market, supporting/contradicting evidence, falsification criterion, evidence level, owner, status és validity.

### ResearchPack

Aggregate: források, assetek, findingok, VOC, pattern, hypothesis, summary, intended downstream use, brand/market/channel scope, validity, canonical manifest hash, author/approver és handoff metadata.

Állapotgép:

`DRAFT → IN_REVIEW → APPROVED → FROZEN → HANDED_OFF`

`FROZEN|HANDED_OFF → EXPIRED|REVOKED|SUPERSEDED`. Módosítás fagyasztás után tiltott; új revision készül. Author != approver. Handoff csak FROZEN, nem lejárt/nem visszavont, hash-azonos, brand/market-kompatibilis packból.

`submit_review`: DRAFT + If-Match → IN_REVIEW, rögzített manifest hash. `review(approve|request_changes|reject)`: külön reviewer; approve csak változatlan hash mellett → APPROVED. `freeze`: külön freeze-jog, APPROVED + változatlan hash + nem lejárt komponensek → FROZEN, JCS manifest SHA-256. Bármely draftkomponens-változás új pack revision és új review. A pack family subject monotonic sequence-t kap; scope parentet minden transition/handoff lockolja.

### Validation

Belső teszt eredménye, módszer, mérőszám, minta, időablak, outcome, supporting artifact, reviewer. Csak ez emelhet findingot `VALIDATED_INTERNAL` szintre.

Lifecycle `DRAFT → IN_REVIEW → APPROVED|REJECTED|REVOKED`; author != reviewer. Tartalmazza a validált finding/hypothesis canonical hash-t, így módosított állítás új validationt igényel. Evidence level emeléskor a service lockolja és újraellenőrzi a latest APPROVED validationt és hash-egyezést.

## 3. Capture biztonság

- csak jóváhagyott SourceTarget és allowlisted scheme/host/port/path;
- DNS feloldás és minden redirect után private, loopback, link-local, metadata és tiltott IP tartomány blokkolása;
- URL credential, file/data/gopher és nem engedélyezett protokoll tiltása;
- timeout, byte/MIME limit, decompression limit, rate limit, robots/rights policy;
- aktív tartalom nem fut; script/macro eltávolítás; parser sandbox;
- prompt-injection jelölés és a forrás szövegének utasításként való végrehajtása tiltott;
- PII/secret scan, minimalizálás, retention és quarantine;
- hálózati fetch és fixture/manual import azonos immutable snapshot-contractot használ.
- parser image/container digest, dependency lock hash és model/version minden snapshotban rögzített; ismeretlen vagy visszavont parser image tiltott;
- `QUARANTINED|ERASED|MALWARE|PARSER_UNVERIFIED` snapshot downstream feldolgozása tiltott.

## 4. Képernyők

1. Dashboard: queue, frissesség, lejárat, blokkolók, pack handoff.
2. SourceTarget lista/detail/create/review/revoke.
3. Capture jobs lista/detail/retry/cancel és snapshot viewer.
4. Assets/observations/VOC böngésző bizonyíték-spanokkal.
5. Pattern cluster compare és membership review.
6. Hypothesis lista/detail/validation.
7. ResearchPack composer, review, freeze, compare, handoff és invalidation.
8. Audit/outbox/connector health read-only nézet.

## 5. Handoff contract

A downstream brief adapter csak a következőket fogadja:

`pack_id`, `revision`, `manifest_sha256`, `brand_id`, `market_id`, `channels`, `valid_until`, `handoff_id`, `idempotency_key`, kiválasztott finding/hypothesis/source refs.

Átvételkor a szolgáltatás MUST újraolvasni és lockolni a packet; ellenőrizni latest revision, FROZEN state, hash, validity, revoke/supersede és scope feltételeket. Sikeres tranzakció `MCI_RESEARCH_PACK_HANDED_OFF` outbox eseményt és downstream reference-et ír. Hiba részleges briefet nem hozhat létre.

A downstream consumer brand+market+purpose subjectenként monotonic pack sequence watermarkot tart. Alacsonyabb sequence, azonos sequence eltérő manifesttel vagy superseded family revision 409/410; azonos sequence+hash idempotens replay. A watermark-ellenőrzés és brief reference/outbox ugyanazon tranzakcióban, lockolt subject sor mellett történik.

## 6. Jogosultság

Brand/market scope kötelező. Szerepek: researcher, research-reviewer, marketing-strategist, compliance/privacy reviewer, read-only executive, technical admin. A platform-admin productionben nem approve/freeze/handoff jogú automatikusan. Deny-first; global list bármely projekt/brand deny esetén explicit scope-ot követel vagy effektív allowed-minus-denied listát ad.

Dashboard/list query SQL-szinten az effektív allowed-minus-denied brand/market halmazra szűr, még LIMIT/pagináció előtt. Ha a felhasználónak globális allow mellett bármely releváns explicit deny-ja van és nincs biztonságosan kiszámított halmaz, explicit brand+market paraméter kötelező; fail-open összesített lista nincs.

## 7. API

- `/api/v1/market-intelligence/source-targets`
- `/api/v1/market-intelligence/capture-jobs`
- `/api/v1/market-intelligence/snapshots/{id}`
- `/api/v1/market-intelligence/assets`
- `/api/v1/market-intelligence/observations`
- `/api/v1/market-intelligence/voc-signals`
- `/api/v1/market-intelligence/pattern-clusters`
- `/api/v1/market-intelligence/hypotheses`
- `/api/v1/market-intelligence/research-packs`
- `/api/v1/market-intelligence/research-packs/{id}/review|freeze|handoff|invalidate`

Write: explicit scope, CSRF/Origin vagy token scope, Idempotency-Key, If-Match, audit. 428/409/422/403/404 konvenció az HD-001 szerint.

## 8. Elfogadási feltételek

- AC-MKT-001: fixture/manual/approved public fetch azonos hashű immutable snapshotot hoz; duplikáció nincs.
- AC-MKT-002: private IP, redirect-to-private, túlméret, tiltott MIME, active content, secret/PII és prompt injection fail-closed.
- AC-MKT-003: observation/VOC mindig source spanhoz kötött; source törlés helyett revoke/tombstone.
- AC-MKT-004: author saját packját nem approve/freeze-eli.
- AC-MKT-005: invalid/expired/revoked/superseded/hash-mismatch/wrong-brand pack handoff elutasított.
- AC-MKT-006: handoff concurrency/idempotency egy downstream brief reference-et és outboxot eredményez.
- AC-MKT-007: MCI route vagy service nem hív publikációs, ad delivery, e-mail vagy budget mutation kódot; dependency/negative test bizonyítja.
- AC-MKT-008: evidence level enumon kívüli érték, illetve forrás nélküli OBSERVED elutasított.
- AC-MKT-009: VALIDATED_INTERNAL csak jóváhagyott Validationből.
- AC-MKT-010: frozen pack immutable; változtatás új revision és SUPERSEDED kapcsolat.
- AC-MKT-011: brand/market cross-scope olvasás és write tiltott; admin fail-closed.
- AC-MKT-012: 49-modulos katalógus, nav, role és release-readiness konzisztens.
- AC-MKT-013: target revoke/new revision capture közben `target_changed`; snapshot/asset részleges write nincs.
- AC-MKT-014: crypto-erased/quarantined snapshot metadata auditálható, tartalom olvasása és pack felhasználása tiltott.
- AC-MKT-015: pack/validation author-reviewer separation, hash change, stale If-Match és concurrent transition teszt PASS.
- AC-MKT-016: out-of-order/replay/collision pack handoff watermark mellett fail-closed.
- AC-MKT-017: globális allow + explicit brand/market deny mellett list/detail/handoff nem szivárogtat.
- AC-MKT-018: módosított finding hash régi Validationnel nem emelhető VALIDATED_INTERNAL szintre.
- AC-MKT-019: ismeretlen/visszavont parser digest és minden quarantine state downstream tiltott.

## 9. Release-kapu

MVP-ben manual/fixture és jóváhagyott public fetch engedhető. Minden más connector OFF. Handoff production csak teljes permission, privacy, SSRF, immutable hash, idempotency és downstream contract teszt után kapcsolható be.
