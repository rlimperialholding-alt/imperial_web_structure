# Partner Field Portal v1.0 – tesztjelentés

## Automatizált tesztek

- Teljes eredmény: **43/43 sikeres**.
- Korábbi Control Center, Import Center, TenderMail, Workspace, Operations, kalkulátor és HouseMatch regressziók sikeresek.
- Új partnerportál tesztek: 5/5 sikeres.

## Bizonyított új folyamatok

1. Kódos partnerbelépés csak a kijelölt projektre és munkacsomagra.
2. A partner nem kapja meg a belső Finance vagy más partner adatait.
3. Személyenkénti érkezés és távozás időbélyeggel és valós jelenléti nyilatkozattal.
4. A partner által jelentett készültség PM-jóváhagyás előtt nem írja felül a munkacsomagot.
5. Jóváhagyott partnerjelentés átvezethető a PM munkacsomagba.
6. Problémából feladat és esemény keletkezik.
7. Változásból ChangeControl Outbox-ügy keletkezik; automatikus scope- és árváltozás nincs.
8. JPG/PNG/WEBP feltöltés fájlfejléc-, méret- és SHA-256-ellenőrzéssel.
9. Partnerkép csak belső felhasználó vagy a hozzá tartozó partner-session számára olvasható.

## Migráció

- Friss adatbázison Alembic `20260719_0005` sikeres.
- Összes adatbázistábla: 45.
- Új partnerportál-táblák: 6.

## Reszponzív ellenőrzés

- Mobil partnernézet: 390 px szélességnél nincs vízszintes túlnyúlás.
- Belső PM partnerfül: 1440 px szélességnél nincs vízszintes túlnyúlás.
- A mobil CSS túlnyúlását okozó negatív fejlécmargó javítva.

## Ismert production-határok

- A jelenléti ív belső bizonyíték, nem helyettesíti az e-naplót vagy a kötelező munkaügyi nyilvántartást.
- Productionben objektumtároló, malware-szűrés, HTTPS, rate limit, hozzáférési kód-élettartam és adatmegőrzési szabály szükséges.
