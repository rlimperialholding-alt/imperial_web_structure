# ADR-HD-001 — Termékhatár és szabályellenőrzési architektúra

Állapot: ACCEPTED  
Dátum: 2026-08-10

## Döntés

1. A Háztervező egy új `house-designer` modul, de az önálló és a beágyazott változat ugyanazt a szolgáltatásmagot, adatbázist és API-szerződést használja.
2. A felhasználói szerkesztési modell nem a HousePlan táblákba ír közvetlenül. `DesignSession` → verziózott `DesignRevision` → immutable `DesignSnapshot` folyamat készül. Az elfogadott snapshotból kontrollált adapter hoz létre vagy köt HousePlan/BuildConfig/HouseVision objektumot.
3. A megfelelőség verziózott, bizonyítékalapú `RegulatoryRuleSet`-ből számol. A kiválasztó figyelembe veszi az ellenőrzés hatálynapját, a helyi terv jogalapját, az országos TÉKA/átmeneti OTÉK szabályt, HÉSZ-t, településképi követelményt és védettséget.
4. A gép három eredményt adhat: `PASS`, `FAIL`, `UNKNOWN`. Bármely kötelező `UNKNOWN` blokkolja a megépíthetőségi állítást, az ügyféljóváhagyást és a megrendelési továbbítást.
5. A szabályforrás immutable snapshotot, tartalmi hash-t, hatályt, eredeti hivatkozást, területi scope-ot, értelmezési verziót, készítőt és külön jóváhagyót kap. Szerző és jóváhagyó nem lehet ugyanaz.
6. A látványterv minden revíziója geometry-lockhoz kötött. A prompt csak stílust, anyagot, színt, környezetet és nem zárolt részletet módosíthat; tömeg, szintszám, tetőforma, nyílások vagy floorplan eltérése QA-fail.
7. Ár és ütemterv lejáró snapshot. Megjelenik a becslési sáv, feltételezés, kizárás, áfa és árszint-dátum. Lejárt snapshot mellett submission tiltott.
8. A standalone termék tenant- és brand-scope-pal működik. A hozzáférési/licenc-adapter interfész része a terméknek, de fizetési szolgáltató-választás nem része az első szállításnak.
9. A jogi megfelelőségi kimenet előzetes gépi ellenőrzés; a folyamat kötelező szakmai telekre adaptálási kaput tart fenn.

## Következmények

- Az ismeretlen HÉSZ nem eredményezhet hallgatólagos engedélyt.
- A szabálykészlet frissítése nem írja át a régi eredményt; új compliance run készül, a korábbi snapshot reprodukálható marad.
- A kliens nem küldhet végleges összeget, státuszt, compliance-eredményt vagy projekt-scope-ot hiteles adatként.
- Később hatósági/GIS adapter hozzáadható a kanonikus modell változtatása nélkül.

## Elvetett megoldások

- Csak OTÉK nevű, dátum nélküli szabálymotor.
- LLM által közvetlenül, emberi jóváhagyás nélkül értelmezett HÉSZ.
- Képalapú látványterv geometriai visszaellenőrzés nélkül.
- Külön standalone adatbázis és utólagos szinkronizáció.

