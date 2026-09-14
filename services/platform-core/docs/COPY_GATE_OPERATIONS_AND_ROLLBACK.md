# Copy Gate üzemeltetés és rollback

## Kötelező, repositoryn kívüli secretek

- `secrets/platform_db_password.txt`
- production `SESSION_SECRET`
- `CONTROL_CENTER_API_TOKEN`
- `INTERNAL_JOB_TOKEN`
- a választott generáló és független editori modell credentialje
- CMS/publishing adapter OAuth vagy API credentialje
- e-mail értesítési provider credentialje

Meta, Google Ads és CMS credential csak akkor szükséges, amikor az adott külső
adaptert külön engedélyezik. Nyers kulcs nem kerülhet `.env`, Drive dokumentum,
log, auditpayload vagy Git repository tartalmába.

## Indítás

1. Hozza létre a platformadatbázis secret fájlt.
2. Tartsa `CONTENT_EXTERNAL_PUBLISHING_ENABLED=false` értéken az UAT végéig.
3. `docker compose up --detach --wait platform-postgres platform-core`
4. Ellenőrizze: `alembic current` → `20260726_0007`.
5. Ellenőrizze a `/health/ready` endpointot.

## Biztonságos rollback

Alkalmazás-visszaállítás előtt állítsa le a publication adapter consumert.
Publikált asset üzleti visszavonását az owner-role rollback endpointtal végezze;
ez új tartalomverziót nyit, törli az approval flageket és auditál.

Sémarollback:

```bash
alembic downgrade 20260719_0006
```

A downgrade előtt adatmentés kötelező. A `cq_*` táblák eltávolítása elveszíti a
CopyBrief-, review-, approval- és performance történetet, ezért productionben
csak export és tulajdonosi change approval után hajtható végre.

## Incidens

Forráskonfliktus, lejárt offer/price/terms, megváltozott content hash, hiányzó
ClaimID/ProofID vagy adapterhiba esetén nincs fallback publikáció. Az asset
`BLOCKED` vagy függő állapotban marad; a rendszer Task/Outbox rekordot és auditot
készít.
