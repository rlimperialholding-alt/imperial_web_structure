# Production runbook

## Kötelező infrastruktúra

- PostgreSQL 16;
- HTTPS reverse proxy;
- vállalati SSO vagy központi identitásszolgáltatás;
- Secret Manager;
- modulonkénti szolgáltatástoken;
- külön outbox worker;
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
7. Outbox retry/dead-letter próba.
8. Három valódi ProjectID pilot.
9. UAT és tulajdonosi production jóváhagyás.
10. Visszaállítási próba és dokumentálás.
