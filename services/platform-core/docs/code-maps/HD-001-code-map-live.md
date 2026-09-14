# HD-001 — Élő kódtérkép

Forrásállapot: `agent/houseplan-ui-v1` / `cd83840008f42d20e14772fda7645989249129ba`  
Adatbázis-head: `20260809_0049`  
Élő modulok száma: 47

## Meglévő, újrahasználandó képességek

| Terület | Élő objektum/szolgáltatás | Felhasználás | Tiltott duplikáció |
|---|---|---|---|
| Típusház-geometria | `HouseCatalogPlan`, `HousePlanRecord`, `house_geometry.py`, `house_plan_execution.py` | típusterv-import, geometriai kanonizálás, család/verzió | új párhuzamos HousePlan-törzs |
| Belső terv-jóváhagyás | `/house-studio`, HousePlan audit és PlanCheck queue | elfogadott ügyfélkoncepció szakmai továbbítása | ügyfél közvetlen katalógus-publikálása |
| Műszaki konfiguráció | `BuildConfigCase` és `app/services/buildconfig.py` | option catalog, BOM, ár, kapacitás, release | külön ár/BOM igazságforrás |
| Kivitelezési tervezés | `HouseBuildCase` | kész tervből kivitelezési változat | új HouseBuild workflow |
| Látvány | HouseVision modellek és `app/services/housevision.py` | geometry lock, render-provider, QA, csomag | geometriától független kép elfogadása |
| Időpont | `BookingExperienceVersion`, `BookingSlot`, `BookingRecord`, `booking_reservation.py` | konzultáció foglalása | külön naptárfoglaló |
| Értékesítés | `SalesOpportunity`, CRM, intent/reservation | lead/opportunity/order-intent | külön ügyféltörzs |
| Ügyfélportál | MyImperial projekt- és eseményvetület | ügyfél státuszkövetése | második ügyfélportál |
| Integráció | `OutboxMessage`, audit események | idempotens handoff | közvetlen, audit nélküli side effect |
| Jogosultság | ITEP-replika és szerepkörök | projekt- és objektumscope | kliens által állítható scope |

## Ténylegesen hiányzó réteg

- fogyasztói DesignSession és verziózott DesignRevision;
- szerkesztési parancsokkal módosítható méretpontos floorplan schema;
- telek és alkalmazandó szabályrendszer bizonyítéka;
- országos/helyi szabályfordító és fail-closed compliance run;
- customer-safe magyarázatok és blokkoló javítási útmutatás;
- tételes/csomagos választás BuildConfig-előnézettel;
- geometriához kötött promptos render-revízió;
- ár- és schedule-snapshot;
- submission aggregate és kanonikus CRM/booking/MyImperial handoff;
- önálló termék tenant/brand/licence shellje.

## Érintett élő fájlok

- `app/models.py`
- `app/schemas.py`
- `app/roles.py`
- `app/seed.py`
- `app/main.py`
- `app/templates/base.html`
- `app/services/house_geometry.py`
- `app/services/house_plan_execution.py`
- `app/services/buildconfig.py`
- `app/services/housevision.py`
- `app/services/booking_reservation.py`
- `data/platform_demo_seed.json`
- `alembic/versions/`

## Új komponensek tervezett helye

- `app/routes/house_designer.py`
- `app/services/house_designer.py`
- `app/services/house_designer_geometry.py`
- `app/services/regulatory_compliance.py`
- `app/templates/house_designer*.html`
- `app/static/house-designer.js`
- `tests/test_house_designer_*.py`
- `alembic/versions/20260810_0050_house_designer.py`

## Integrációs határok

`DesignRevision` tartja a szerkesztési igazságot. Jóváhagyáskor kanonikus, immutable snapshot készül; csak ez adható át BuildConfignak, HouseVisionnak, CRM-nek és az időpontfoglalásnak. A külső/standalone felület ugyanazt az API-t és adatmodellt használja, tenant- és brand-scope-pal.

