# MKT-001 — Élő implementációs terv

Állapot: COMPLETE — a belső üzleti vertikum és a scope-kötött service API publikálható; a külső fetch, publikálás és azonosított fogyasztó nélküli szolgáltatási tokenek változatlanul fail-closed OFF állapotban maradnak
Spec: Drive master `10sdAJme3LJjs8pnHd7hIjAin979ofCq5_DsqEqn4zqA`, revision `AIroW37Z2kzCHtlWQLw7VfkSYdje626nCM0Ddp0G-XmMH5Pxxi25SHI-5UuvdxMOvj6Qbf-a-5y0fNU8dKzajsCf2I9_Fu-kw-_omlMmttfc` + `specs/MKT-001-live-adaptation-v1.0.md` (FROZEN, ellenőrizve: 2026-08-11)

## WP-MKT-01 — Adatmodell és migráció

SourceTarget family/revision, CaptureJob, SourceSnapshot/redaction, MarketAsset, Observation, VOCSignal, PatternCluster/member, ResearchHypothesis, ResearchPack/member/review/handoff watermark és Validation. Additív `20260810_0051`, adatvesztés nélküli downgrade guard.

## WP-MKT-02 — SourceTarget és capture policy

Four-eyes lifecycle, allowlist, rights/privacy/retention policy, latest lock; manual/fixture import és biztonságos fetch adapter interfész. SSRF/redirect/MIME/size/decompression/timeout/rate-limit negatív teszt.

## WP-MKT-03 — Immutable evidence pipeline

Snapshot hash/dedupe/encryption envelope, parser digest, quarantine, redaction/crypto-erasure; asset/observation/VOC extraction provenance spanokkal. Prompt injection nem végrehajtható data.

## WP-MKT-04 — Pattern/hypothesis/validation

Reprodukálható cluster revision, member review, hypothesis supporting/contradicting evidence, hash-kötött Validation four-eyes és evidence-level gate.

## WP-MKT-05 — ResearchPack workflow

Composer, manifest JCS hash, review/freeze/immutable revision/invalidation, author-reviewer separation, compare; concurrency/If-Match/revoke/expiry teszt.

## WP-MKT-06 — Downstream handoff

Monotonic watermark, latest/hash/scope recheck, idempotens brief reference és outbox egy tranzakcióban. Dependency guard: nincs publication/ad/email/budget mutation.

## WP-MKT-07 — UI/jogosultság

Dashboard, targets, jobs/snapshots, assets/evidence, patterns, hypothesis/validation, pack composer/review/handoff, audit/health. SQL-before-limit allowed-minus-denied scope; CSRF/Origin és WCAG.

## WP-MKT-08 — Modulintegráció és release

Module registry/seed/role/nav; AGT-017 reuse; fixture tesztadat; connector flags default OFF; MKT + HD együtt 49 modul; regression/security/performance/deploy evidence.

## Definition of Done

Az HD terv DoD-ja alkalmazandó, továbbá minden evidence-objektum provenance-kötött, minden frozen pack reprodukálható, és statikus + runtime teszt bizonyítja a tiltott downstream mutation hiányát.

## 2026-08-11 végrehajtási állapot

- Elkészült: SourceTarget négy-szem, manuális snapshot és dedupe, Observation, MarketAsset, VOCSignal, PatternCluster, ResearchHypothesis, hash-kötött Validation, evidence-level promotion, heterogén ResearchPack, review/freeze, idempotens belső handoff, monotonic watermark, outbox és a teljes vertikum közös munkafelülete.
- Elkészült: SourceTarget új revízió/supersede/revoke lifecycle, capture-job napló, bizonyíték-karantén négy-szem kapuval, függő ResearchPack automatikus visszavonás és downstream invalidációs outbox.
- Elkészült: a teljes jelenlegi vertikum session-auth JSON API-ja kötelező `application/json`, CSRF/Origin, `If-Match` és `Idempotency-Key` kapukkal; a HTML és API ugyanazt a fail-closed service-réteget használja.
- Elkészült: HMAC-aláírt, monoton sequence-ű ITEP permission replica, explicit allow/deny, deny-first brand/market scope, lejárat és rollback/collision védelem. A platform-admin tesztüzemben csak olvasási és szerzői jogot kap, üzleti review/freeze/handoff jogot nem.
- Elkészült: alapból OFF, külön kill switch mögötti public-fetch queue és worker; idempotens job, cancel/retry, DNS/IP-pinning, redirectenkénti scope- és publikus-IP ellenőrzés, MIME/byte/UTF-8/content-encoding/aktív-tartalom kapu, HTTP provenance és commit előtti target-revízió/policy recheck.
- Elkészült: snapshotonkénti AES-256-GCM adatkulcs, külön KEK-kel titkosított envelope, hitelesített metadata-kötés, legacy plaintext automatikus cutover, manipuláció fail-closed elutasítása és négyszemelvű végleges crypto-erasure audit/tombstone-nal.
- Elkészült: immutable PatternCluster- és ResearchPack-revízió, latest-only elágazásvédelem, automatikus `SUPERSEDED` és handed-off invalidáció, tagság-/manifestdiff, session UI és olvasási API összehasonlítás.
- Elkészült: target-policyba kötött, forráscsaládon át folytonos capture-kvóta; target-sorzárral több worker között is tranzakciósan egységes, idempotens replay nem fogyaszt új kvótát, túllépés HTTP 429.
- Elkészült: scope-szűrt operations/audit felület és API, queue/running/24h-failure/oldest-job állapot, connector readiness, evidence-encryption és belső handoff/outbox health.
- Release evidence: `faac4cf8d0c51294e17337f60f8f9dc9905098b9`, schema `20260811_0060`, célzott Ruff/format PASS, teljes MKT regresszió 15/15 PASS, hitelesített HTML+API smoke PASS, core/worker error és traceback 0. A public fetch és külső publikálás továbbra is OFF.
- Biztonsági alapállapot: production fetch OFF, külső publikálás OFF, CSRF + Origin kapu, PII/secret/prompt-injection/aktív HTML elutasítás, brand/market scope és szerző–jóváhagyó szétválasztás.
- Elkészült: alapból OFF service API, SHA-256 token-regiszter, expiry, explicit read/handoff permission, tenant/brand/market scope, OpenAPI Bearer security és idempotens handoff contract.
- Elkészült: külön HTTP-folyamaton végrehajtott hálózati E2E 10 050 capture-jobbal; hitelesítés nélkül 401, scope-kötött tokennel a legfrissebb 100 saját rekord 0,009 másodpercen belül, idegen scope nélkül.
- Release evidence: `b247b6310fe82e605ccaf0e8abe6e071b98f2597`, schema `20260813_0064`, célzott Market/security/performance 28/28 PASS, teljes többmodulos regresszió 490/490 PASS, autentikált HTML smoke PASS, nyilvános health és standalone smoke PASS, core/outbox/typehouse/gateway error és traceback 0.
- Üzemeltetési alapállapot: `MARKET_SERVICE_API_ENABLED=false`, külső publikálás OFF, public fetch OFF. Éles service credential csak azonosított fogyasztó, jóváhagyott scope és külön secret-provisioning után adható ki.
