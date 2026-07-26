# Control Center v1.0 – tesztjelentés

Kiadási dátum: 2026-07-19

## Automatizált tesztek

- Eredmény: 20/20 sikeres.
- Futási idő: 2,35 másodperc a forrásmappából.
- Lefedett területek: health/readiness, login és UI, modulregiszter, heartbeat, esemény-idempotencia, projekt/task/objektum/outbox képzés, kritikus projektblokk, retry/dead-letter, tényadat-upsert, rendszerközi eltérés felismerése és lezárása, artifact-idempotencia, archiválási és production kapu, három integrációs pilot, dashboard KPI-k, production konfigurációs blokkolás.

## Migrációs próba

- Alembic revision: `20260719_0001`.
- Tiszta SQLite adatbázison sikeres.
- Létrehozott táblák az Alembic táblával együtt: 16.

## Integrációs pilot

- Előkészítés: 10/10 lépés sikeres.
- Aktív kivitelezés/beszerzés: 10/10 lépés sikeres.
- Változtatás/garancia: 7/7 lépés sikeres.
- A ChangeControl–Finance szándékos eltérés felismerése, majd egyezés után automatikus lezárása sikeres.

## Élő indítási próba

- `/health`: 200 OK, Control Center 1.0.0, Platform 4.0.0.
- `/health/ready`: 200 OK, adatbázis elérhető.
- `/login`: 200 OK.

## Korlát

A tesztcsomag szintetikus adapter- és projektadatokkal futott. Élő modulhitelesítések és három valódi Imperial ProjectID még deployment/UAT feladat.
