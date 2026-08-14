# BuildConfig – as-built 1.0

## Kanonikus határ

A BuildConfig nem szabadon szerkeszthető ajánlati kalkulátor. Csak ugyanahhoz a `ProjectID`-hoz tartozó, kiválasztott HouseBuild-változatból indulhat. A HousePlan bruttó területe, az árforrások, a normakönyv, a vállalati fedezeti policy és minden választott opció hash-kötött konfigurációverzióba kerül.

## Verzió és BOM

Minden `BuildConfigID` több, megváltoztathatatlan `BuildConfigVersion` pillanatképet tartalmazhat. A revízió nem írja felül az előző számítást. A verzió tartalmazza:

- márka, technológia, készültségi szint és csomag;
- kiválasztott opciók és kompatibilitási szabályok;
- tételes alap- és opció-BOM;
- nettó önköltség, nettó ajánlati ár, ÁFA, bruttó ár és fedezet;
- mérföldkő-alapú fizetési és költség-cashflow;
- kezdés, brigádszám, heti kapacitás, becsült és vállalt átadás;
- forrás-, BOM- és teljes konfiguráció SHA-256.

## Fail-closed kapuk

Nyolc automatikus kapu kézzel nem írható felül:

1. `source`: ármodell, belső költségmodell és normakönyv hash;
2. `houseplan`: azonos projekt kiválasztott HousePlanja;
3. `compatibility`: opció-, csomag-, tető-, garázs- és akadálymentességi szabályok;
4. `bom`: a tételes BOM és önköltség egyezése;
5. `pricing`: pozitív, forráskötött ár és költség;
6. `margin`: legalább 35% vállalati minimumfedezet;
7. `cashflow`: nem negatív kumulált finanszírozási egyenleg;
8. `capacity`: a vállalt dátum tartható a rögzített kapacitással.

A `technical` és `finance` kaput két külön, jogosult, név szerinti ellenőr hagyja jóvá SHA-256 bizonyítékkal. A verzió készítője egyiket sem reviewzhatja, és saját konfigurációját nem adhatja ki.

## Kiadás és adatkapcsolatok

Kiadáskor SHA-256 ellenőrzött PDF kerül a dokumentumtárba, majd `CONFIGURATION_APPROVED` esemény és tartós outbox-kézbesítés indul a HouseBuild, Sales, Reservation Engine, Contract Generator, Financial Control, Finance Intelligence, Procurement, Project Control, CRM és MyImperial felé.

## UAT

- `scripts/seed_buildconfig_uat.py`: idempotens kiadott és kompatibilitási STOP teszteset;
- `scripts/verify_buildconfig_schema.py`: verzió-, validáció-, kapu-, BOM-hash- és PDF-invariánsok;
- `tests/test_buildconfig_engine.py`: teljes kiadás, négyszem, routing, STOP, revízió és legacy írási tiltás.
