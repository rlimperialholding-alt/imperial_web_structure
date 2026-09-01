# HD-001 — Háztervező normatív specifikáció v1.0

Állapot: FROZEN  
Osztályozás: CRITICAL  
Modulkulcs: `house-designer`  
Elsődleges útvonal: `/house-designer`

Az RFC 2119 szerinti MUST/SHOULD/MAY kifejezések normatívak.

## 1. Termék- és biztonsági határ

HD-001 MUST biztosítson önálló, brandelhető webes shellt és Imperial Intelligence-be ágyazott modult közös API-val. A rendszer koncepciótervező, konfigurációs, becslési és lead/order-intake eszköz; MUST NOT állítsa, hogy a kimenet engedélyezési vagy kiviteli terv.

A felhasználó MUST tudjon telek nélkül vázlatot készíteni. Telek és bizonyított szabálykészlet nélkül a UI MUST jól láthatóan `Előzetes vázlat — megfelelőség nem igazolt` jelzést adni, és MUST blokkolni az `APPROVED`, `ORDERABLE`, `SUBMITTED` állapotot.

## 2. Szereplők és scope

| Szereplő | Jog |
|---|---|
| vendég | új ideiglenes session, szerkesztés, előnézet; mentéshez azonosítás |
| customer | saját sessionök CRUD, snapshot, render, becslés, jóváhagyás, beküldés, foglalás |
| sales | explicit projekthez rendelt submission olvasás, megjegyzés, konzultáció |
| designer | explicit projektscope mellett szakmai review, változtatáskérés |
| compliance reviewer | ruleset jóváhagyás és compliance review; saját szerzői rekordját nem hagyhatja jóvá |
| pricing reviewer | ár-snapshot és kivétel review |
| platform-admin | technikai admin; productionben nem kap automatikus üzleti jóváhagyási jogot |

Minden hozzáférés MUST tenant-, brand-, subject- és objektumscope-ot ellenőrizni. A deny MUST megelőzni az allow-t. Az objektum tulajdonosa kliensoldali mezővel nem változtatható.

## 3. Kanonikus objektumok

### 3.1 DesignSession

`session_id`, `tenant_id`, `brand_id`, `owner_subject_id`, `project_id?`, `origin(template|blank)`, `template_plan_id?`, `status`, `current_revision_id`, `title`, `locale`, `currency`, `row_version`, auditmezők.

Állapotgép:

`DRAFT → CHECK_REQUIRED → CHECKED → ESTIMATED → CUSTOMER_APPROVED → SUBMITTED`

Mellékállapotok: bármely nem végállapotból `ARCHIVED`; `CHECKED|ESTIMATED|CUSTOMER_APPROVED → STALE` ha geometry/config/ruleset/pricing/capacity változik; `SUBMITTED → CANCELLED` kizárólag üzleti workflow-val. `STALE → CHECK_REQUIRED` új ellenőrzéssel. Kliens közvetlen állapotírása tiltott.

### 3.2 DesignRevision

Immutable felhasználói verzió: `revision_id`, `session_id`, növekvő `revision_no`, `predecessor_revision_id?`, `geometry_json`, `configuration_json`, `site_json`, `canonical_sha256`, `change_summary`, `created_by`, `created_at`. Módosítás mindig új revíziót hoz létre optimistic concurrency (`If-Match` / row version) mellett.

### 3.3 DesignSnapshot

Immutable jóváhagyási csomag: revision hash, ruleset hash, compliance run id/hash, BuildConfig preview/revision id/hash, price snapshot id/hash, schedule snapshot id/hash, selected render id/hash, consent/terms version, customer approval timestamp. A hash-elt összetevő eltérése MUST érvénytelenítse.

### 3.4 SiteContext

`country`, `municipality_code`, `postal_code`, `address`, `parcel_number`, `geometry?`, `source`, `verified_at`, `verification_status`, `protected_flags`, `source_refs`. A telekazonosító normalizálása után tenanton belül determinisztikus kulcs készül; a pontos személyes cím titkosítandó és hozzáférés-auditált.

### 3.5 RegulatoryRuleSet

`ruleset_id`, `jurisdiction`, `scope_geometry|municipality|parcel`, `national_basis(TÉKA|OTÉK_TRANSITION)`, `local_plan_basis`, `hesz_version`, `tkr_version`, `tak_version`, `effective_from`, `effective_to?`, `source_snapshot_ids`, `interpreter_version`, `rules_json`, `canonical_sha256`, `status(DRAFT|IN_REVIEW|APPROVED|REVOKED|SUPERSEDED)`, author/approver. APPROVED csak teljes provenance, hash és négy-szem elv mellett.

Minden nyers jogi/önkormányzati forrás külön immutable `RegulatorySourceSnapshot`: source URL/irat-ID, issuer, kihirdetés és hatály, területi scope, retrieval timestamp, bytes/text hash, parser version, storage ref, privacy/security state és revoke/supersede. A szabályfordítás `RuleInterpretationRevision`, amely source spanonként tartja az értelmezést és a tesztvektorokat. Csak APPROVED interpretation kerülhet APPROVED rulesetbe.

Új check indulásakor a szolgáltatás előbb lockolja a jurisdiction/scope parentet, majd újraolvassa a hatálynapon latest APPROVED ruleset revisiont és forrásait. A run commit előtt ugyanezt ellenőrzi. Revoke vagy újabb revision a régi snapshotot reprodukálhatóan megőrzi, de új PASS-t nem enged; folyamatban lévő run `UNKNOWN/ruleset_changed` eredménnyel zár.

### 3.6 ComplianceRun és Finding

Immutable run az input hash-ekkel. `outcome=PASS|FAIL|UNKNOWN`; finding: `code`, `severity=BLOCKER|ERROR|WARNING|INFO`, `outcome`, `rule_ref`, `source_ref`, érintett geometry path, mért és határérték, magyar magyarázat, javítási javaslat. Bármely kötelező UNKNOWN vagy FAIL → nem orderable.

### 3.7 RenderRevision

`render_id`, `session_id`, `design_revision_id`, `geometry_lock_hash`, `parent_render_id?`, `prompt`, `negative_prompt`, `provider`, `provider_job_id`, `asset_ref`, `asset_sha256`, QA-metrikák, `status`. A promptot biztonsági szűrés és költséglimit kapuzza; a render nem minősül elfogadottnak automatikusan.

### 3.8 EstimateSnapshot és ScheduleSnapshot

Immutable és lejáró. Ár: nettó, áfa, bruttó, sáv, pénznem, árszint, scope, exclusions, source BuildConfig/pricing hash, érvényesség. Ütem: legkorábbi/legkésőbbi kezdés, szakaszok, munkanap-tartomány, függőségek, kapacitás-snapshot, feltételek, érvényesség. Pontérték csak bizonyított determinisztikus számításból jelenhet meg; egyébként intervallum.

### 3.9 DesignSubmission

`submission_id`, snapshot id/hash, customer/lead/opportunity/project references, `status=RECEIVED|SALES_REVIEW|DESIGN_REVIEW|CHANGES_REQUESTED|CONSULTATION_BOOKED|ACCEPTED|REJECTED|CANCELLED`, attribution, consent, idempotency key, audit. Létrehozás egyetlen tranzakcióban outbox eseményt ír; CRM/booking/MyImperial fogyasztók idempotensen dolgoznak.

## 4. Geometriai szerződés

Egység milliméter, koordináták egész számok. A root tartalmazza: `schemaVersion`, `units=mm`, `levels`, `verticalCores`, `verticalConnections`, `sitePlacement?`, `northAngleDeg`.

Egy szint: `levelId`, `elevationMm`, `heightMm`, `outerBoundary`, `wallSegments`, `rooms`, `openings`, `connections`, `voids`. A poligon egyszerű, zárt és óramutató járásával ellentétes; a kanonizáló a kezdőpontot lexikografikusan választja, kulcsokat és ID-s tömböket rendez, majd JCS szerint hash-el.

MUST invariánsok:

- 1–3 lakószint; tetőtér a szint típusával és hasznos magassági zónával;
- szintkontúr önmetszés nélkül, pozitív területtel;
- helyiség a megengedett envelope-on belül, tiltott átfedés nélkül;
- falcsatlakozás rés vagy lebegő végpont nélkül;
- nyílás egy és csak egy falon, határok és más nyílás között biztonságos távolsággal;
- minden használati helyiség elérhető a bejárattól a connection graphban;
- több szint esetén koherens verticalCore és szomszédos szinteket összekötő verticalConnection;
- lépcső fejmagasság, fellépő/belépő, szélesség és pihenő ellenőrzés verziózott szabályból;
- számított nettó/bruttó területek nem kliensből elfogadott értékek;
- minden szerkesztőparancs atomi, validált, undo/redo-kompatibilis.

Műveletek: fal rajzolás/mozgatás/hasítás/törlés, helyiségcímke és funkció, ajtó/ablak elhelyezés, méret módosítás, szint hozzáadás/klónozás/törlés, lépcső/core, tető footprint, bútor-segédréteg. Invalid művelet 422 + géppel olvasható finding; részleges írás nincs.

Minden command envelope: `commandId` (UUID), `sessionId`, `baseRevisionId`, `baseCanonicalSha256`, `commandType`, `payload`, `clientCreatedAt`, `schemaVersion`. `commandId` sessionön belül unique és idempotens: azonos ID + azonos hash ugyanazt az eredményt adja; azonos ID + más payload 409. A szerver generálja az új objektum-ID-ket és egy tranzakcióban validál, létrehoz revisiont, session pointert és auditot. Elavult base revision 409 + current revision/ETag; automatikus last-write-wins tiltott.

## 5. Szabálymotor

A szabályválasztó inputja: ellenőrzés dátuma, site context, helyi terv basis/effective date, building use és design revision. Nem választhat pusztán mai dátum alapján országos rendszert.

Minimum szabálycsoportok:

- övezet, rendeltetés, kialakítható telek és beépítési mód;
- max. beépítettség, min. zöldfelület, szintterületi mutató;
- elő-, oldal- és hátsókert, építési hely;
- épületmagasság/párkány/gerinc és szintszám;
- tetőforma, hajlásszög, anyag/szín, településkép;
- parkolás, megközelítés, közmű és alapvető telekfeltételek;
- helyiségméret, belmagasság, természetes megvilágítás/szellőzés, közlekedés;
- lépcső, korlát, akadálymentességi relevancia;
- védettség és külön előírás;
- tűz- és energetikai ellenőrzésre átadandó kötelező adatok.

Szabályfuttatás determinisztikus, side-effect-mentes és verziózott. LLM MAY segítsen forrásszöveg-javaslat készítésében, de eredménye DRAFT és emberi jóváhagyás nélkül nem végrehajtható.

## 6. Műszaki konfiguráció

A customer választhat jóváhagyott csomagot vagy tételes opciókat. Csomag felbontása explicit option snapshot; egyedi módosítás `customized=true`. Függőségek és inkompatibilitások szerveroldalon validáltak.

Kötelező csoportok: szerkezet/építési technológia, készültségi fok, alapozás, fal/födém, tető, lépcső, nyílászáró, hőszigetelés/homlokzat, gépészet, villamosság, energetika, belső felületek, szaniterek, burkolatok, külső munkák. Minden választás verziózott katalógustétel és mennyiségi driver.

## 7. Ügyfélfolyamat és képernyők

1. Landing + termékmagyarázat + folytatható session.
2. Kiindulás: típusterv-szűrés vagy üres alaprajz.
3. Telek: cím/HRSZ, források, verifikáció és hiányok.
4. 2D szerkesztő: vászon, szintválasztó, eszköztár, objektumtulajdonság, méretek, finding panel, autosave, undo/redo.
5. Műszaki tartalom: kategória és tételes override, függőségi hibák.
6. Megfelelőség: szabályonként PASS/FAIL/UNKNOWN, bizonyíték és javítás.
7. Látvány: nézetek, prompt-revízió, összehasonlítás, elfogadás.
8. Ár és ütem: tételcsoportok, sáv, feltételek, lejárat.
9. Összefoglaló: hash-elt snapshot, hozzájárulás, elfogadás.
10. Beküldés és konzultáció: submission státusz és meglévő Booking Engine.
11. MyImperial: státusz, változtatáskérés, dokumentumok és időpont.
12. Belső queue/detail: sales/designer/compliance/pricing döntések, audit.

Minden adatmódosító UI CSRF-védett; API session-auth mellett application/json + CSRF + Origin, token-auth mellett scope és idempotency.

Vendég sessionhez a szerver random, HttpOnly, Secure, SameSite=Lax cookie-t és külön egyszer használatos, rövid életű claim tokent ad. Bejelentkezéskor claim egy tranzakcióban owner subjecthez köt, minden vendégtokent/cookie session ID-t rotál és replay deny-listet ír. Claim token URL-be, logba vagy analytics payloadba nem kerülhet; lejárt/replayed/cross-tenant claim 404/409 fail-closed.

### 7.1 Invalidation mátrix

| Változás | Compliance | Estimate | Schedule | Render | Customer approval |
|---|---|---|---|---|---|
| geometry revision | stale | stale | stale | geometry QA újra | visszavont |
| site/ruleset revision vagy revoke | stale/UNKNOWN | változatlan, de submit tiltott | változatlan, de submit tiltott | változatlan | visszavont |
| configuration revision | releváns szabályok újra | stale | stale | material/style esetén stale | visszavont |
| pricing/BOM revision vagy expiry | változatlan | stale | releváns esetben stale | változatlan | visszavont |
| capacity revision vagy expiry | változatlan | változatlan | stale | változatlan | visszavont |
| selected render change | változatlan | változatlan | változatlan | új selection | visszavont |
| terms/consent version change | változatlan | változatlan | változatlan | változatlan | visszavont |

Az invalidáció ugyanabban a tranzakcióban történik, mint a kiváltó write. Session státusz `STALE`, majd a hiányzó kapuk újrafuttatása után determinisztikusan `CHECKED`/`ESTIMATED` lehet; customer approval mindig új explicit művelet.

## 8. API v1

- `POST /api/v1/house-designer/sessions`
- `GET /api/v1/house-designer/sessions/{id}`
- `POST /api/v1/house-designer/sessions/{id}/commands`
- `POST /api/v1/house-designer/sessions/{id}/revisions/{rev}/check`
- `POST /api/v1/house-designer/sessions/{id}/estimate`
- `POST /api/v1/house-designer/sessions/{id}/renders`
- `POST /api/v1/house-designer/renders/{id}/revisions`
- `POST /api/v1/house-designer/sessions/{id}/approve`
- `POST /api/v1/house-designer/sessions/{id}/submit`
- `GET /api/v1/house-designer/submissions/{id}`

Write: kötelező `Idempotency-Key`, `If-Match` ahol meglévő aggregate változik, actor/scope a hiteles identityből. Hiányzó precondition 428, conflict 409, validation 422, deny 403, nem található vagy nem látható objektum egységesen 404.

A `submit` kizárólag `submissionType=ORDER_REQUEST` objektumot hoz létre. Ez nem adásvételi/kivitelezési szerződés és nem végleges, kötelező ár; a UI a verziózott order-request tájékoztatót és elfogadását rögzíti. Kötelező joghatás csak a későbbi Contract Generator folyamat bizonyított aláírásával keletkezhet.

Mock/sandbox render, pricing vagy capacity provider eredménye vízjeles és `non_production=true`; ilyen eredmény customer approvalhoz és submithez nem használható. Provider timeout/failure részleges snapshotot nem publikál, a session szerkeszthető marad, és célzott retry lehetséges.

## 9. Integrációs események

- `HOUSE_DESIGN_SESSION_CREATED`
- `HOUSE_DESIGN_REVISION_CREATED`
- `HOUSE_DESIGN_COMPLIANCE_COMPLETED`
- `HOUSE_DESIGN_ESTIMATE_READY`
- `HOUSE_DESIGN_RENDER_ACCEPTED`
- `HOUSE_DESIGN_CUSTOMER_APPROVED`
- `HOUSE_DESIGN_SUBMITTED`
- `HOUSE_DESIGN_CHANGES_REQUESTED`
- `HOUSE_DESIGN_CONSULTATION_BOOKED`

Payload MUST tartalmazza az object id-t, tenant/brand/project scope-ot, causation/correlation/idempotency kulcsot, verziót és snapshot hash-t; személyes adatot csak szükséges minimumként.

## 10. NFR

- NFR-HD-001: minden write auditált; append-only esemény.
- NFR-HD-002: szerkesztőparancs p95 < 250 ms 200 objektumos szinten; teljes compliance p95 < 3 s 500 szabályig.
- NFR-HD-003: autosave legfeljebb 2 s; hálózati megszakításkor helyi, titkosított pending queue és konfliktuskezelés.
- NFR-HD-004: WCAG 2.2 AA; billentyűzetes szerkesztési alternatíva, nem csak színnel jelzett finding.
- NFR-HD-005: UTC tárolás, Europe/Budapest megjelenítés; DST gap/fold explicit elutasítás foglalásnál.
- NFR-HD-006: migráció additív; downgrade adatvesztés helyett fail-safe runbook.
- NFR-HD-007: CSP, CSRF, rate limit, prompt-injection és upload AV/MIME/méret kontroll.
- NFR-HD-008: cím/HRSZ és render-prompt privacy retention; export/törlési workflow, de audit bizonyíték anonimizált megőrzése.
- NFR-HD-009: provider kill switch, költségkeret, timeout, retry és circuit breaker.
- NFR-HD-010: teljes számítás reprodukálható canonical hash-ekből.

## 11. Elfogadási feltételek

- AC-HD-001: blank és típusterv flow-ban 1, 2 és 3 szintes valid ház létrehozható.
- AC-HD-002: önmetsző fal, átfedő helyiség, falon kívüli nyílás és összekötetlen felső szint atomi 422-vel elutasított.
- AC-HD-003: telek/ruleset/provenance hiányában draft működik, submit 409/422 `compliance_unknown`.
- AC-HD-004: hatálytalan vagy visszavont szabálykészlet nem használható új checkhez; régi check reprodukálható.
- AC-HD-005: határérték alatti/egyenlő/feletti teszt minden numerikus compliance szabályhoz.
- AC-HD-006: országos transition selector fixture szerint választ, és ismeretlen helyi basis esetén UNKNOWN.
- AC-HD-007: csomag + override dependency és ár ugyanazt a BuildConfig contractot használja.
- AC-HD-008: geometry-changing render QA-fail és nem választható ki.
- AC-HD-009: stale price/schedule/ruleset/revision mellett approval és submit tiltott.
- AC-HD-010: dupla submit azonos idempotency key-jel egy submissiont és egy outbox handoffot eredményez.
- AC-HD-011: submission CRM opportunityt, MyImperial eseményt és booking belépési pontot hoz létre duplikáció nélkül.
- AC-HD-012: customer nem olvas más customer/tenant sessiont; sales csak explicit projektscope-ot; admin nem hagy jóvá üzleti jog nélkül.
- AC-HD-013: author nem approve-olhat saját rulesetet/árkivételt.
- AC-HD-014: prompt injection, tiltott tartalom, túlméret és provider failure biztonságosan kezelve.
- AC-HD-015: standalone és embedded ugyanarra a sessionre azonos ETag/hash eredményt ad.
- AC-HD-016: auditból minden state change, ruleset, ár, render és submission bizonyítható.
- AC-HD-017: új modul regisztrálva, role/nav/release-readiness és 49-modulos katalógus konzisztens.
- AC-HD-018: geometry/site/config/pricing/capacity/render/terms változás az invalidation mátrix minden cellája szerint tesztelt.
- AC-HD-019: command replay azonos payloadnál idempotens, eltérő payloadnál 409, stale base revisionnél nincs részleges write.
- AC-HD-020: guest claim expiry/replay/cross-tenant/session-fixation negatív teszt PASS.
- AC-HD-021: ruleset revoke vagy concurrent new revision a checket fail-closed `ruleset_changed` eredménnyel zárja.
- AC-HD-022: mock/non-production providerrel approval és ORDER_REQUEST submit tiltott.
- AC-HD-023: a felület mindenhol `megrendelési igény`/`ORDER_REQUEST` joghatást jelenít meg; szerződés csak Contract Generatorban keletkezik.

## 12. Release-kapu

Éles order-intake csak akkor ON, ha:

- legalább egy brandhez jóváhagyott template/ruleset/option/pricing/capacity/terms verzió van;
- szakmai megfelelőségi tulajdonos jóváhagyta a szabályforrásokat;
- render provider production QA bizonyított;
- CRM/booking/MyImperial idempotens integrációs teszt PASS;
- backup/rollback és megfigyelhetőség PASS;
- biztonsági, adatvédelmi és jogosultsági negatív tesztek PASS.

Egyébként `HOUSE_DESIGN_ORDER_INTAKE_ENABLED=false`; a szerkesztő sandboxként működhet.
