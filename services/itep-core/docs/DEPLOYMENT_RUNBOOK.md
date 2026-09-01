# Imperial ITEP v1.1 deployment runbook

## Telepítési sorrend

1. PostgreSQL adatbázis és titokkezelés létrehozása.
2. `imperial-itep-secrets` Secret feltöltése.
3. `npm ci`, `prisma validate`, `prisma generate`.
4. `prisma migrate deploy`.
5. API deployment indítása.
6. `/health/live` és `/health/ready` ellenőrzése.
7. Worker deployment indítása.
8. Connector accountok létrehozása és OAuth-kapcsolás.
9. Smoke test futtatása.
10. Első backup elkészítése és checksum ellenőrzése.

## Visszaállítás

- maintenance mód;
- friss backup checksum ellenőrzése;
- `scripts/restore.sh`;
- migration ellenőrzése;
- readiness teszt;
- worker visszaindítása;
- audit és outbox állapot ellenőrzése.

## Backup szabályzat

- 6 óránként adatbázismentés;
- legalább két ellenőrzött példány;
- 35 napos megőrzés;
- havonta dokumentált restore-próba.

## Release gate

Production release csak akkor engedhető:

- TypeScript build sikeres;
- tesztek sikeresek;
- Prisma migration ellenőrzött;
- readiness zöld;
- rollback csomag elérhető;
- adatbázisbackup elkészült.
