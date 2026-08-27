# Imperial Copy Gate v1.0 – ellenőrzési riport

Dátum: 2026-07-26

## Automatikus minőségi kapuk

| Ellenőrzés | Eredmény |
| --- | --- |
| Platform Core Ruff format | sikeres |
| Platform Core Ruff lint | sikeres |
| Copy Gate mypy | sikeres, 6 ellenőrzött forrásfájl |
| Platform Core teljes pytest | 66 sikeres, 0 hibás |
| Digital PM Ruff | sikeres |
| Digital PM mypy | sikeres, 16 ellenőrzött forrásfájl |
| Digital PM teljes pytest | 32 sikeres, 0 hibás, 87,52% lefedettség |
| Platform-regiszter validáció | sikeres: 47 modul, 12 szerepkör, 16 eseményszerződés |
| Webstruktúra-validáció | sikeres: 12 márka, 50 regisztrált preview |
| JavaScript szintaxis | sikeres |
| Teljes Compose-konfiguráció | sikeres |
| `git diff --check` | sikeres |

A pytest figyelmeztetések kizárólag a FastAPI/Starlette TestClient jövőbeli
`httpx2` átállására és két meglévő openpyxl extensionre vonatkoztak; teszt- vagy
kapuhibát nem jeleztek.

## PostgreSQL és migráció

Tiszta, izolált Docker-projektben a `postgres:17-alpine` adatbázis és a runtime
Platform Core image indult el.

- readiness: `{"status":"ready","database":"ok"}`;
- Alembic head: `20260726_0007`;
- létrejött `cq_*` táblák száma: 8;
- gateway proxy health: sikeres;
- SQLite migrációs regresszió: `upgrade head → downgrade 0006 → upgrade head`
  sikeres.

Az izolált PostgreSQL-projektet és köteteit a smoke teszt után eltávolítottuk.

## Pilot bizonyíték

A `data/copy_gate/imperial_pilot_v1.json` 15 különböző Imperial assetjét a
regresszióteszt egyenként értékeli. Mindegyik eléri a 92/100 minimumot és Gate 1
`APPROVED`, de egyik sem kap automatikus publikációs jogot. A specialistakapu,
az emberi szerkesztői approval és a tulajdonosi approval továbbra is kötelező.

Negatív tesztek igazolják, hogy a márkakeveredés, a szöveg- és layoutduplikáció,
a tiltott nyelv, az eltérő offer/price/terms/product verzió, a hiányzó
ClaimID/ProofID, az elégtelen vizuális jogigazolás, a message mismatch és az
elavult approval blokkolja a publikációt.
