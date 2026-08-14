# MyImperial projektportál – as-built

## Cél és határ

A MyImperial a futó ügyfélprojektek ellenőrzött, ügyfélhez rendelt projekttere. Csak aktív `CustomerPortalAccess` alapján mutat adatot; egy ügyfél másik ügyfél projektazonosítójával sem férhet hozzá projekthez.

Hiba-, hiány- és garanciális bejelentés itt nem indítható. Ezek kizárólag az Imperial Care-ben rögzíthetők. A MyImperial frissítéshez vagy döntéshez adott megjegyzés nem minősül hibabejelentésnek.

## Megvalósított üzleti folyamatok

- projektmenedzseri, ügyvezetői vagy platform-adminisztrátori projektfrissítés;
- 0–100% közötti, validált készültségi állapot;
- opcionálisan kötelező ügyfél-visszaigazolás, névre szóló feladatkártyával;
- 2–6, előre kiadott opciót tartalmazó ügyféldöntési kérés;
- jövőbeli döntési határidő és névre szóló ügyfélteendő;
- ügyfélválasz csak a kiadott opciók egyikével;
- egyszer rögzíthető döntés: utólagos módosítás csak dokumentált ChangeControl-folyamatban;
- a döntés kanonikus `ProjectObjectState` rekordot hoz létre a modulkapcsolatokhoz;
- projektmérföldkövek a Smart Calendar adataiból;
- ügyfélnek kiadható állapotok a BuildConfig, PlanCheck, Contract Generator, ChangeControl, Imperial Care és más kapcsolódó modulokból;
- teljes audit a publikálásról, visszaigazolásról, döntéskérésről, döntésről és teendőzárásról.

## Jogosultság

- `customer`: csak a saját aktív hozzáférésű projektje, saját feladatai, visszaigazolásai és döntései;
- `project-manager`, `managing-director`, `owner`, `platform-admin`: kiadott MyImperial-projektek belső felügyelete és publikálás;
- más szerepkör nem publikálhat projektfrissítést és nem rögzíthet ügyféldöntést.

## Bizonyító tesztek

`tests/test_my_imperial_project_portal.py` ellenőrzi a szerepkörös elszigetelést, a publikálás–visszaigazolás folyamatot, a döntési opciók szerveroldali kötését, az egyszer rögzíthető döntést, a modulállapot létrejöttét, valamint azt, hogy a MyImperialban nincs hibabejelentési végpont.
