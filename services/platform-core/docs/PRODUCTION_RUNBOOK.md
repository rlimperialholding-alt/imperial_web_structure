# Production runbook

## Kötelező infrastruktúra

- PostgreSQL 16;
- HTTPS reverse proxy;
- vállalati SSO vagy központi identitásszolgáltatás;
- Secret Manager;
- modulonkénti szolgáltatástoken;
- külön `platform-outbox-worker`, tartós belső inbox-receiptekkel;
- adatbázismentés és visszaállítási próba;
- monitoring, loggyűjtés és incidensriasztás;
- vírusellenőrzött dokumentumcsatorna;
- GDPR/adatmegőrzési szabály.

## Élesítési sorrend

1. Secret és adatbázis létrehozása.
2. `alembic upgrade head`.
3. `/health/ready` ellenőrzése.
4. Modulregiszter és környezetregiszter kitöltése.
5. Minden forrásmodul heartbeat-tesztje.
6. Egy modulonkénti eseménypróba.
7. `platform-outbox-worker` futásának, belső inbox-receiptjének, SHA-256 kötésének és idempotens újrafeldolgozásának ellenőrzése; külső adapter nélkül `sent` státusz tiltott.
8. Három valódi ProjectID pilot.
9. UAT és tulajdonosi production jóváhagyás.
10. Visszaállítási próba és dokumentálás.

## Outbox üzemeltetés

- Az outbox-ciklus alapértelmezés szerint 15 másodperc; `CONTROL_CENTER_WORKER_INTERVAL_SECONDS` értéke legalább 5 lehet.
- A konzisztenciavizsgálat külön ciklusa alapértelmezés szerint 3600 másodperc; `CONTROL_CENTER_CONSISTENCY_INTERVAL_SECONDS` értéke legalább 60 lehet.
- Belső modulüzenet csak akkor tekinthető kézbesítettnek, ha a `cc_module_inbox` rekord, a payload SHA-256 és a `delivery_receipt_json` egyezik.
- A `scripts/verify_module_outbox_schema.py` hibamentes eredménye kötelező kiadási kapu.
- Ismeretlen modul, hibás JSON vagy idempotenciaütközés fail-closed hiba; külső adaptercél igazolt adapter nélkül retry/dead-letter.
