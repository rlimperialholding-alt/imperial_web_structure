# Imperial Copy Gate és négykapus tartalomminőség v1.0

## Architektúra

A Copy Gate a meglévő Marketing Quality Gate kötelező Gate 1 alrendszere, nem
ötödik kapu. A hagyományos végrehajtási út:

`DRAFT → COPY_QA → FOUR_GATE_QA → HUMAN_EDITORIAL → OWNER_APPROVAL → PUBLISHED`

Bármely hiba `BLOCKED` állapotot eredményez. Javítás után új tartalomverzió és új
review-futás szükséges.

Az igazolt, változatlan forrás újraközlésének rövidített útja:

`DRAFT → COPY_QA → FOUR_GATE_QA → SOURCE_PREVALIDATED → PUBLISHED`

Ez nem általános gépi approval. Kizárólag a verziózott kereskedelmi
forrásregistryben szereplő, hash-azonos webes állítás, webes típusház/floorplan
asset vagy a kanonikus Drive-árkalkulátor pontos kimenete használhatja.
Átírt állítás, eltérő összeg, hiányzó árfeltétel, forrásváltozás vagy új
tényszerű claim visszaesik a hagyományos emberi ellenőrzésre.

Az input minden esetben jóváhagyott CopyBrief, feloldott kanonikus forráspillanat
és verziózott ContentAsset. A generáló orchestrator kilenc külön szakaszt hajt
végre: source resolution, offer core, hook/big idea, first draft, brand voice edit,
direct response critique, Hungarian edit, claim/fact validation és message match.
Az adapterekhez szükséges modellcredential nincs a repositoryban.

### Vizuális variánsok

Ugyanazon brief külön vizuális irányai külön generálási futások. Egy A/B/C
variánskészlet minden tagja önálló `generation_run_id`, `creative_variant_id` és
`visual_direction_id` értéket kap. Azonos futás vagy azonos vizuális irány
újrafelhasználása ugyanabban a `variant_set_id` készletben blokkolt. A variáns
nem lehet pusztán szín-, cím- vagy logócsere: a kompozíció, a képi bizonyíték és
az elsődleges vizuális hipotézis is eltér.

A trace-ben a futásazonosítókon túl kötelező a `layout_archetype_id`,
`composition_signature`, `primary_text_zone`, `image_treatment`,
`background_treatment` és a mért `minimum_text_contrast_ratio`. Egy
variánskészleten belül nem ismétlődhet a layout-archetípus, a kompozíciós
aláírás, illetve a szövegpozíció–képhasználat–háttérkezelés hármas.
Normál szövegnél legalább 4,5:1 kontraszt kötelező. Színátmenetes
kreatívháttér alapértelmezetten blokkolt, és csak dokumentált emberi
art-direction kivétellel használható.

### Márkalogók

A rendszer először jóváhagyott vektoros/Drive-forrást keres, majd az élő
márkawebhely eredeti SVG/PNG/WebP assetjét olvassa be. Képernyőképből kivágás
vagy OCR csak végső, emberi ellenőrzést igénylő fallback. Minden fájlhoz
forrás-URL, megfigyelési dátum, SHA-256 és jóváhagyási állapot tartozik.
Webhelyről megfigyelt logó tesztanyagban használható, de külső publikációhoz a
registry `approval_status=approved` állapota kötelező.

A jelenlegi registry hét élő webhellyel rendelkező márkát fed le: Imperial
Holding, Danish Fabrik, Bautica, Prefab, Casa Moderna, BauFreund és Timberhaus.
A részletes forrás- és 404-audit:
`docs/BRAND_ASSET_REGISTRY_AUDIT.md`.

## Gate 1

A tíz dimenzió:

1. Brand Voice Fit
2. Natural Hungarian
3. Direct Response Strength
4. Offer Clarity
5. Specificity
6. Proof Coverage
7. Objection Handling
8. Message Match
9. CTA Strength
10. Readability & Rhythm

A minimum 92/100. Bármely kritikus finding pontszámtól függetlenül blokkol.
Deterministikus szabály ellenőrzi többek között a szlogen és megszólítás
pontosságát, márkakeveredést, duplikált szöveg/layout blokkot, verziókat,
ClaimID/ProofID-ket, tiltott nyelvet, CTA-t, message match-et, visual rightsot és
a független editori futást.

## Négykapus aggregáció

Gate 1 minden assetnél kötelező. Gate 2–4 előtt dokumentált relevanciarouting fut.
Nem releváns kapu kizárólag `SKIPPED_NOT_RELEVANT`; releváns, de hiányzó vagy
bizonytalan specialistadöntés `HUMAN_APPROVAL_REQUIRED`, Task és e-mail Outbox
rekordot hoz létre. A három külső döntés:

- `APPROVED`
- `RETURN_FOR_REVISION`
- `HUMAN_APPROVAL_REQUIRED`

Forrás-elővalidált tartalomnál Gate 2–4 csak arra a kategóriára kaphat
determinisztikus `APPROVED` eredményt, amelyet a registry bizonyítéka teljesen
lefed. A nem lefedett jogi, kereskedelmi, ár- vagy műszaki állítás továbbra is
specialista- vagy emberi döntést igényel.

## Kereskedelmi forrás-elővalidáció

- Az auditált élő weboldal normalizált szövegfragmentumai USP-ként,
  marketingajánlatként, műszaki vagy jogi tájékoztatásként változatlanul
  újraközölhetők.
- A weboldalon megfigyelt típusházképek és alaprajzok automatikus
  marketinganyagban használhatók, ha márka, forrásoldal és asset-URL egyezik a
  snapshotban tárolt referenciával.
- Ár csak a márkához rendelt, hash-azonos Drive-forrásból, a repository
  kalkulátorának pontos kimeneteként publikálható. Az input, az output mező, az
  összeg és a feltételek együtt kerülnek auditálásra.
- A weboldali árhoz tartozó kizárásokat, becslési vagy érvényességi feltételeket
  nem szabad elhagyni.
- A registry és a részletes audit:
  `docs/COMMERCIAL_SOURCE_PREVALIDATION_AUDIT.md`.

## Biztonsági korlátok

- Gép nem adhat emberi szerkesztői vagy tulajdonosi approvalt.
- Az approval az aktuális content versionhöz és SHA-256 hashhez kötött.
- Az adatbázis CHECK constraint minden kötelező flag, PublicationProof és
  timestamp nélkül tiltja a `PUBLISHED` állapotot.
- Forrásváltozás után a régi GateResult nem használható publikációra.
- Külső delivery alapértelmezetten ki van kapcsolva
  (`CONTENT_EXTERNAL_PUBLISHING_ENABLED=false`).
- Jogi, pénzügyi vagy műszaki bizonytalanság emberi feladatot hoz létre.
- A rendszer nem vállalhat automatikusan kötelezettséget, nem módosíthat
  szerződést, nem ismerhet el felelősséget és nem igazolhat teljesítést.
- A már publikált jogi vagy szerződéses tájékoztatás marketingkommunikációként
  újraközölhető, de joghatást kiváltó R6–R7 műveletként soha. Az
  `external_action_type` és az `action_risk_level` ezt külön, fail-closed módon
  ellenőrzi.

## API

- `POST /api/content-quality/sources`
- `POST /api/content-quality/briefs/validate`
- `POST /api/content-quality/briefs`
- `POST /api/content-quality/assets`
- `POST /api/content-quality/assets/{id}/copy-qa`
- `POST /api/content-quality/assets/{id}/four-gates`
- `POST /api/content-quality/assets/{id}/editorial-approval`
- `POST /api/content-quality/assets/{id}/owner-approval`
- `POST /api/content-quality/assets/{id}/publish`
- `POST /api/content-quality/assets/{id}/rollback`
- `POST /api/content-quality/assets/{id}/performance`

## Adatmodell

Új `cq_*` táblák: source records, CopyBriefs, content assets, review runs, gate
decisions, approvals, Golden Copy samples és performance metrics. Minden
állapotváltás a meglévő `cc_audit_logs` táblába kerül.

## Migráció

Alaprevision: `20260726_0007`; kereskedelmi forrás-elővalidáció:
`20260726_0008`. Az utóbbi a `cq_content_assets.source_prevalidated` jelzőt és a
publikációs CHECK constraint alternatív, bizonyítékalapú ágát adja hozzá.
