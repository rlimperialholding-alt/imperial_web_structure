# HouseBuild – as-built 1.0

## Határ és forrás

A HouseBuild nem látványgenerátor és nem közvetlen katalóguspublikáló. Aktív, kiadott `HouseCatalogVersion` pillanatképből készít auditálható `HousePlan`-változatokat. A forrás tartalom-hash-e, a felhasználásijog-bizonyíték hivatkozása és SHA-256 értéke kötelező. Visszavont, ellenőrizetlen vagy hash nélküli forrásból nem indul ügy.

## Generálás

Minden `HouseBuildID` három tartós változatot tartalmaz:

1. katalógushű;
2. célprogramra hangolt;
3. kompakt költségoptimalizált.

Mindegyik változat saját bruttó/nettó területet, befoglaló méretet, lábnyomot, szint-, szoba-, fürdő- és garázsprogramot, tető- és homlokzati karaktert, orientációt, helyiséglistát, kapcsolati gráfot, becsült katalógusárat, geometry signature-t és tartalom-hash-t kap. A motor determinisztikus ugyanazon bemenet mellett; a duplikációt a geometry signature jelzi.

## Fail-closed kapuk

- `source_rights`: kiadott katalógusverzió és jogbizonyíték;
- `program`: területkonzisztencia, építhető befoglaló és helyiségminimumok;
- `deduplication`: vállalati geometry signature egyezés;
- `topology`: az előtérből minden helyiség elérhető;
- `plotcheck`: azonos ProjectID, `FIT` vagy `FIT WITH CONDITIONS`;
- `buildconfig`: azonos ProjectID, jóváhagyott konfiguráció;
- `plancheck`: azonos ProjectID, `SENDABLE` eredmény;
- `technical`: hash-kötött, név szerinti műszaki jóváhagyás.

Az első négy kapu automatikus és kézzel nem írható felül. A nem megfelelő jelölt megmarad összehasonlítható tervezési eredményként, de kiválasztása után a STOP kapu megakadályozza a beküldést.

## Kiadás

A létrehozó nem adhatja ki saját ügyét. Kiadáskor a kiválasztott változat `released`, a többi `superseded` állapotú lesz, SHA-256 ellenőrzött PDF-jegyzőkönyv kerül a dokumentumtárba, majd `HOUSE_PLAN_APPROVED` esemény indul a House Catalog, HouseVision, HouseMatch, BuildConfig, PlanCheck, CRM, MyImperial, Engineering Workspace és Contract Generator felé.

## UAT és ellenőrzés

- `scripts/seed_housebuild_uat.py`: idempotens, elkülönített kiadott és duplikációs STOP eset;
- `scripts/verify_housebuild_schema.py`: változatszám-, kapu-, tartalom-hash- és PDF-checksum ellenőrzés;
- `tests/test_housebuild_engine.py`: generálás, STOP, kanonikus függőségek, négy szem, outbox, képernyő és szerepkör.
