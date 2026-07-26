# Imperial Copy Gate és négykapus tartalomminőség v1.0

## Architektúra

A Copy Gate a meglévő Marketing Quality Gate kötelező Gate 1 alrendszere, nem
ötödik kapu. A végrehajtási út:

`DRAFT → COPY_QA → FOUR_GATE_QA → HUMAN_EDITORIAL → OWNER_APPROVAL → PUBLISHED`

Bármely hiba `BLOCKED` állapotot eredményez. Javítás után új tartalomverzió és új
review-futás szükséges.

Az input minden esetben jóváhagyott CopyBrief, feloldott kanonikus forráspillanat
és verziózott ContentAsset. A generáló orchestrator kilenc külön szakaszt hajt
végre: source resolution, offer core, hook/big idea, first draft, brand voice edit,
direct response critique, Hungarian edit, claim/fact validation és message match.
Az adapterekhez szükséges modellcredential nincs a repositoryban.

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

Alembic revision: `20260726_0007`. A downgrade kizárólag a nyolc `cq_*` táblát
távolítja el, a meglévő platformadatokhoz nem nyúl.
