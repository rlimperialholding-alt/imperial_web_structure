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

## Imperial Care biztonsági és release-állapot – 2026-08-15

- A MyImperial projektoldal csak az Imperial Care-re mutató CTA-t tartalmaz;
  `/my-imperial/{project_id}/issues` nincs regisztrálva és 404-et ad.
- A Field és Partner Field problémafolyamok kizárólag belső kivitelezési,
  illetve tokenes alvállalkozói operációk. Ügyfélszerepkör nem érheti el őket,
  ezért nem jelentenek ügyfél-hibabejelentési kerülőutat.
- Az Imperial Care ügyfél-, belső és kijelölt alvállalkozói scope-jai külön
  szerveroldali ellenőrzést kapnak; a belső megjegyzés ügyfél és alvállalkozó
  számára nem látható.
- A 0069 migráció minden Care-bizonyítékhoz perzisztálja a malware-scan
  állapotát, motorját, verzióját, időpontját és opcionális szignatúráját. A régi
  fájlok `legacy_unverified` állapotban maradnak, és letöltésük fail-closed
  blokkolt.
- Feltöltés előtt kötelező a típus/szignatúra ellenőrzés és a ClamAV
  `INSTREAM` vizsgálat. Fertőzés 400, scanner-hiány vagy bizonytalan válasz 503;
  fájl csak tiszta verdict után kerülhet tárhelyre. A letöltés újraellenőrzi a
  tárolási gyökérutat, a scan-státuszt és az SHA-256-ot, és minden eredményt
  auditál.
- A Care külön `CARE_AV_MODE` / `CARE_CLAMAV_*` konfigurációt támogat; ha ezek
  nincsenek megadva, a közös Tender ClamAV-konfigurációra esik vissza. A
  determinisztikus scanner kizárólag `ENVIRONMENT=test` mellett engedett.
- Célzott MyImperial + Care teszt: 12/12 PASS. Friss adatbázis 0001→0069 és a
  Care AV-sémaellenőrző PASS.
- Az exact Care-változtatásokon futtatott teljes Platform Core regresszió:
  **557 passed, 5 nem hibát okozó warning, 669,48 s**. A futás pytest-cache és
  Python bytecode nélkül, külön JUnit-eredménnyel készült.

Nyitott éles kapu: a Hetzneren futó ClamAV szolgáltatás, frissítési és riasztási
felügyelet, a 0065→0069 migráció előtti Hetzner-only mentés/visszaállítás-próba,
valamint a valódi támogatott böngészőkön végzett ügyfél/PM/alvállalkozó kézi UAT.
Ezek nélkül a modul szerveroldali folyamata bizonyított, de teljes production
readiness nem állítható.
