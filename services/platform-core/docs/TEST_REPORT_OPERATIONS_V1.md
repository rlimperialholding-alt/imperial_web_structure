# Operations Workspace v1.0 – tesztjelentés

## Automatizált tesztek

- Eredmény: **38/38 sikeres**
- Korábbi Workspace/Control Center regresszió: sikeres
- Új Operations tesztek: 6/6 sikeres
- Futási bizonyíték: `docs/PYTEST_OUTPUT_OPERATIONS_V1.txt`

Újonnan bizonyított szabályok:

1. PM Cockpit, projektoldal és munkacsomag-frissítés működik.
2. Akadályos napi jelentés helyszíni ügyet, feladatot és eseményt képez.
3. Mennyiségi eltéréses, hiányos anyagátvétel lotot és kontrolleseményeket képez.
4. Negatív anyagkészlet blokkolva van.
5. Túlhasználás csak emberi review-t és levonási javaslatot képez; automatikus levonás nincs.
6. Operatív összesítő API működik.

## Migráció

- Tiszta adatbázis-migráció: sikeres
- Alembic head: `20260719_0004`
- Táblák száma az `alembic_version` táblával együtt: **39**
- Futási bizonyíték: `docs/ALEMBIC_OUTPUT_OPERATIONS_V1.txt`

## Vizuális QA

Ellenőrzött képernyők:

- PM Cockpit 2.0 – 1440 px;
- projektmunkalap – 1440 px;
- beszerzési munkapad – 1440 px;
- projektbeszerzés – 1440 px;
- helyszíni projektlista – 430 px;
- helyszíni projektmunkalap – 430 px.

Eredmény:

- hat képernyőből 6/6 renderelt;
- vízszintes kilógás: 0;
- JavaScript page error: 0;
- bizonyíték: `screenshots/operations_visual_qa.json` és a PNG-fájlok.

## Statikus biztonsági ellenőrzés

- private key, Google API key, AWS access key, GitHub token és hosszú bearer-token minták: **0 találat**;
- eredmény: PASS;
- bizonyíték: `docs/SECRET_SCAN_OPERATIONS_V1.json`.

## Ismert figyelmeztetések

Az openpyxl két meglévő forrásfájl beolvasásánál ismeretlen Excel-kiterjesztésre és conditional formatting extensionre figyelmeztet. Ez a teszteredményt nem befolyásolta; a forrásfájlok írása nem történt meg.
