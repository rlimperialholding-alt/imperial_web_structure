# Release notes – v0.7.0 production candidate

## Új üzemi kontrollok

- az öt valós munkakörhöz külön Bearer-tokenes RBAC;
- technikai service-identitás a gépi integrációkhoz;
- ügyvezető-only Process Card- és checklist-jóváhagyás;
- a végrehajtó szerepkörhöz kötött checklist-hozzáférés;
- payloadból származó aktornév helyett tokenből származó hiteles aktor;
- idempotens checklist-indítás és kulcsütközés-védelem;
- kérésazonosító, strukturált napló és PostgreSQL audit trail;
- Prometheus-kompatibilis, külön tokennel védett `/metrics`;
- production trusted-host, CORS, request-size és docs-kontroll;
- operációs állapot- és auditlekérdező API;
- verziózott production Compose overlay;
- automatikus backup, integritásvizsgálat és nem destruktív restore drill;
- online production canary;
- image rollback, automatikus adatbázis-downgrade nélkül.

## Kompatibilitás

Az `X-Imperial-Token` fejléc átmenetileg támogatott. Minden új kliensnek az `Authorization: Bearer ...` formát kell használnia.

## Adatbázis

Új Alembic migráció: `8f6db9b7a701`, amely létrehozza az `audit_events` táblát. A változás additív.

## Offline QA

- 51/51 automatikus teszt;
- Python AST és JSON static check;
- Alembic upgrade/downgrade/upgrade;
- 99/99 katalógus;
- 396/396 PDF/PNG artefaktum;
- production preflight;
- production release gate.

## Függő online ellenőrzés

Valódi production/staging hozzáférés nélkül a Google Drive, Gmail delegation, élő Directus, Docker deployment, backup volume és production canary nem volt tényleges külső környezetben lefuttatható.
