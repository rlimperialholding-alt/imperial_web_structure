# HD-001 — Implementációs terv review

Első verdikt: BLOCKED

## P1 és feloldás

1. **47→49 migráció sorrend:** a HD terv önmagában 48-at, MKT-val 49-et eredményezhet. Feloldás: a két modul seed-katalógus módosítása egy közös release WP-ben történik; teszt explicit set-egyezést, nem csak darabszámot mér.
2. **Provider nélkül „kész” félrejelölés:** feloldás: mock vízjel + order-intake false; release csak production provider contract teszttel.
3. **HÉSZ teljes lefedettség illúziója:** feloldás: fixture/curated ruleset mellett UNKNOWN; telekscope coverage mutató és submission gate.
4. **Migráció downgrade:** feloldás: 0050 adat esetén abort, külön export/archive runbook, automatikus drop nincs.
5. **Túl nagy UI WP:** feloldás: képernyőnként route/service/template/test atomokra bontandó végrehajtáskor, az első vertikális slice blank→check→estimate preview.

Végső verdikt: PASS. P0/P1 nincs; WP-HD-01 indítható.

