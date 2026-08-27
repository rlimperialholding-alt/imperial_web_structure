# Imperial Intelligence Workspace v1.0 – UAT-terv

## UAT-1: Személyes kezdőlap
1. Belépés tulajdonosi jogosultsággal.
2. Nyitott és lejárt feladatok száma egyezzen az Action Centerrel.
3. Blokkolt projekt pénzügyi hatása egyezzen a Projekt 360° adataival.
4. Modulindító ne mutasson egészségesnek nem csatlakoztatott modult.

## UAT-2: Feladatkezelés
1. Nyisson meg egy modulból érkezett feladatot.
2. Állítsa `in_progress`, majd `done` állapotba.
3. Ellenőrizze az auditnaplót.
4. Ellenőrizze, hogy az eredeti forrásesemény nem módosult.

## UAT-3: Projekt 360°
1. Nyisson meg egy valós aktív projektet.
2. Ellenőrizze az ügyfél-, felelős-, pénzügyi és határidőadatokat.
3. Hasonlítsa össze a ProjectFact adatokat a Finance és Contract Generator forrásával.
4. Nyissa meg a dokumentum-, feladat- és idővonalfület.

## UAT-4: Dokumentumtár
1. Regisztráljon valós Google Drive dokumentumot.
2. Rendeljék hozzá ProjectID-hoz.
3. Állítsák jóváhagyott és ellenőrzött státuszba.
4. Ellenőrizzék, hogy megjelenik a Projekt 360° dokumentumfülén.

## UAT-5: Központi kereső
1. Keressen ProjectID-ra.
2. Keressen ügyfélnévre.
3. Keressen egy dokumentum tartalmi kifejezésére.
4. Keressen egy esemény vagy feladat megnevezésére.
5. Ellenőrizze a találatok forrását és céloldalát.

## UAT-6: Mobil és tablet
1. 390 px szélességű mobilnézet.
2. 800 px szélességű tabletnézet.
3. Oldalsó menü nyitása és bezárása.
4. Feladatlista és dokumentumtár használata vízszintes oldal-kilógás nélkül.
