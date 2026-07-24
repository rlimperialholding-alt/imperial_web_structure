# HouseBuild Agent – helyi integrációs prototípus

## Szerepe

A HouseBuild önálló, típusház-generáló ügynök. Meghatározott és jóváhagyott
adatforrásokból normalizált, verziózott `HousePlan`-jelöltet készít. Nem azonos a
HouseVision vizualizációs modullal, és nem publikálhat közvetlenül a
házkatalógusba vagy a weboldalakra.

## Bemenet és származás

Minden forráshoz kötelező:

- stabil `SourceID`;
- forrástípus, márka és lekérési idő;
- tartalom-hash;
- felhasználási jog állapota;
- `approved` kapu a generálás előtt.

Az ismeretlen jogállású forrás `rights_blocked`, ezért abból a felület sem enged
generálni. A repositoryban található források szintetikus pillanatképek, nem
valódi ügyféladatok és nem élő külső kapcsolatok.

## Folyamat

1. Forrás- és jogkapu.
2. Program normalizálása: alapterület, hálószoba, szint, technológia, karakter.
3. Determinisztikus helyi `HousePlanID` és geometry signature létrehozása.
4. Alapterület-, topológia- és duplikációs QA.
5. `HOUSE_PLAN_DRAFTED` esemény a PlanCheck felé.
6. PlanCheck és kötelező emberi jóváhagyás.
7. `HOUSE_PLAN_APPROVED` esemény a BuildConfig felé.
8. Későbbi integrációban árazás, HouseVision vizuálcsomag és HouseMatch
   katalóguspublikáció.

## Biztonsági határ

- nincs külső API;
- nincs valós generatív modellhívás;
- nincs automatikus publikáció;
- nincs production secret;
- nincs valódi ügyfél- vagy telekadat;
- minden futás visszaállítható a böngésző helyi tárának törlésével.

## Tesztelés

Nyisd meg a `/housebuild-agent/` útvonalat, hozz létre jelöltet, majd futtasd a
PlanCheck jóváhagyást. Az `/integration-control-room/` oldalon megjelenik a két
helyi esemény és az outbox-bejegyzés. Újratöltés után a futás megmarad, a
„Tesztfutás visszaállítása” gombbal törölhető.
