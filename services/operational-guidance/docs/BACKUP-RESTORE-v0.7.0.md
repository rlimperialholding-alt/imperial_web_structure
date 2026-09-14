# Imperial Intelligence v0.7.0 – mentés, ellenőrzés és visszaállítási próba

## Mit ment a rendszer?

A `backup` profil egy időbélyeges csomagba menti:

- a PostgreSQL adatbázist custom-format `pg_dump` fájlba;
- a közös Operational Guidance runtime volume teljes tartalmát;
- a 99/99 kanonikus operatív katalógust;
- mindhárom fájl SHA-256 manifestjét.

## Mentés

```bash
make backup
```

A mentések a `backup_data` Docker volume-ba kerülnek. A `latest` szimbolikus hivatkozás mindig a legutóbbi mentésre mutat. Az alapértelmezett megőrzés 30 nap.

## Integritásellenőrzés

```bash
make backup-verify
```

Az ellenőrzés:

- visszaszámolja a SHA-256 értékeket;
- `pg_restore --list` paranccsal vizsgálja az adatbázismentést;
- teljesen beolvassa a runtime tar-archívum tartalomjegyzékét.

## Nem destruktív restore drill

```bash
make restore-drill
```

A rendszer külön ideiglenes adatbázist hoz létre, visszatölti a dumpot, ellenőrzi az Alembic és operatív táblák elérhetőségét, majd törli a próbaadatbázist. Az élő adatbázist nem módosítja.

## Éles visszaállítás

Az éles adatbázis felülírása nem automatikus. Kötelező:

1. karbantartási ablak;
2. újabb biztonsági mentés;
3. ügyvezetői GO döntés;
4. az érintett szolgáltatások leállítása;
5. a kiválasztott backup kétszeres ellenőrzése;
6. adatbázis és runtime visszaállítása;
7. Alembic verzióellenőrzés;
8. production canary;
9. dokumentált lezárás.

Az alkalmazáskép visszaállítása a `scripts/ops/rollback-release.sh` segítségével elvégezhető. Ez szándékosan nem hajt végre automatikus adatbázis-downgrade-ot.
