# Imperial Intelligence Integration Hub v0.6.0 – kiadási jegyzet

## Kiadási cél

A v0.6.0 a v0.5.0 Operational Guidance Engine üzleti logikáját nem írja át. A kiadás a staging- és későbbi production-telepítéshez szükséges biztonsági, migrációs és ellenőrzési réteget adja hozzá.

## Új elemek

- Alembic inicializáló migráció az összes alkalmazástáblához.
- Külön `migrate` Docker Compose szolgáltatás.
- Az API, worker és beat csak sikeres migráció után indul.
- `/live`, `/health` és összetett `/ready` végpont.
- Staging/production konfigurációs fail-fast validáció.
- Külön `DRIVE_PUBLICATION_ENABLED` és `GMAIL_APPROVAL_ENABLED` feature flag.
- Kötelező 32+ karakteres admin- és webhook titok staging/production környezetben.
- Nem-root Docker runtime felhasználó.
- API és konténer healthcheck.
- Külön `docker-compose.staging.yml` overlay.
- `.env.staging.example`.
- Offline és online staging preflight.
- Teljes release gate: teszt, migráció, Compose, preflight és 99/99 artefaktum-QA.

## Kompatibilitás

- A Process Card és checklist adatmodell változatlan.
- A 99 ProcessID és 99 checklist TemplateID változatlan.
- A Directus kollekciónevek környezeti változókból továbbra is felülírhatók.
- A v0.5.0 runtime-fájlok beolvashatók.

## Fontos változás

Staging és production környezetben az alkalmazás nem indul el placeholder titkokkal, alapértelmezett adatbázis-jelszóval vagy `AUTO_CREATE_DB_SCHEMA=true` beállítással.

## Migráció

```bash
alembic upgrade head
```

Docker Compose esetén ezt a `migrate` szolgáltatás automatikusan elvégzi.
