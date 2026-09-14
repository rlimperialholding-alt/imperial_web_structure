# Imperial Intelligence Workspace v1.0 – Tesztjelentés

Kiadás dátuma: 2026-07-19

## Automatizált tesztek

- összes teszt: 32;
- sikeres: 32;
- sikertelen: 0.

A tesztkör tartalmazza:
- a korábbi Control Center esemény-, idempotencia- és outbox tesztjeit;
- rendszerközi konzisztencia-ellenőrzést;
- kiadási és production kapukat;
- három integrációs pilotot;
- Import Center commit és rollback teszteket;
- újépítési, felújítási, HouseMatch és BuildConfig regressziót;
- TenderMail domain-, suppression- és leiratkozási teszteket;
- Workspace Action Center feladatfrissítést;
- dokumentumregisztrációt;
- Projekt 360° dokumentumkapcsolatot;
- központi kereső UI- és API-teszteket.

## Böngészős renderellenőrzés

Vizsgált nézetek:
- Workspace kezdőlap;
- Projekt 360°;
- dokumentumtár;
- Action Center.

Viewport: 1440 × 1000 px.

Eredmény:
- nincs vízszintes kilógás;
- nincs JavaScript page error;
- minden oldal sikeresen renderelődött;
- képernyőképek a `screenshots/` mappában.

## Ismert figyelmeztetés

Az `openpyxl` a régi Excel-források egyes nem támogatott kiterjesztéseit és feltételes formázási metaadatait figyelmeztetéssel kezeli. A kalkulációs értékek tesztje sikeres; a forrásfájlokat a rendszer nem írja felül.
