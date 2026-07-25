# Imperial Intelligence moduláris tesztplatform

Az Imperial Intelligence ezen változata kizárólag lokális és staging célú, kattintható prototípus. A teljes rendszer szintetikus tesztadatot használ; nem kapcsolódik külső API-hoz, nem tartalmaz production secretet vagy valós ügyféladatot.

## Modulok és stabil route-ok

| Modul | Modulazonosító | Route |
|---|---|---|
| Executive Dashboard | `executive-dashboard` | `/executive-dashboard/` |
| MyImperial | `my-imperial` | `/my-imperial/` |
| CRM | `crm` | `/crm/` |
| Sales / ajánlatkezelés | `sales` | `/sales/` |
| Contract Generator | `contract-generator` | `/contract-generator/` |
| Project Control | `project-control` | `/project-control/` |
| Financial Control | `financial-control` | `/financial-control/` |
| Imperial Care | `imperial-care` | `/imperial-care/` |
| Partner Control | `partner-control` | `/partner-control/` |
| Marketing Control | `marketing-control` | `/marketing-control/` |
| Website & Content Control | `website-content-control` | `/website-content-control/` |
| Document Center | `document-center` | `/document-center/` |
| Workflow Center | `workflow-center` | `/workflow-center/` |
| Admin / jogosultságok | `admin` | `/admin/` |

Minden modul ugyanazt a kliensoldali alkalmazásréteget és a `sites/_portal/data/platform.json` közös adatmodellt használja. A route-váltás History API-val történik, az oldal újratöltése nélkül; a route-ok közvetlenül is megnyithatók.

## Tesztadat és bemutató ügyfélút

A közös modell legalább 10 leadet, 5 ügyfelet, 3 aktív építési projektet, 5 partnert, 8 ajánlatot, 4 szerződést, 20 pénzügyi tételt, 6 Care hibajegyet, továbbá mérföldköveket, dokumentumokat, feladatokat, kampányokat, workflow-kat és demo felhasználókat tartalmaz.

A `journey-demo-001` bemutató út a marketingkampánytól és leadtől az ajánlaton, szerződésen, partneren, projekten, pénzügyön, dokumentumon, workflow-n és MyImperial profilon keresztül a garanciális Care ügyig követi a `C-2001` szintetikus ügyfelet. A rekordok részletpaneljén található modulhivatkozásokkal a kapcsolódó entitások közvetlenül megnyithatók.

## Helyi indítás

1. Másold a `.env.example` fájlt `.env` néven, és kizárólag tesztértékeket használj.
2. Indítsd el a staging alapot:

   ```powershell
   docker compose up --detach --wait
   ```

3. Nyisd meg például a `http://127.0.0.1:8080/executive-dashboard/` vagy a `http://127.0.0.1:8080/crm/` címet.
4. Leállítás:

   ```powershell
   docker compose down --volumes --remove-orphans
   ```

A mobil és tablet megjelenést a böngésző reszponzív nézetében lehet ellenőrizni. A Website & Content Control modul saját desktop, tablet és mobil előnézeti kapcsolókat is biztosít.

## Ellenőrzés

Lokális strukturális és adatkapcsolati validáció:

```powershell
python scripts/validate-platform.py
```

JavaScript szintaxisellenőrzés, ha Node.js elérhető:

```powershell
node --check sites/_shared/assets/platform.js
```

Az `Imperial Intelligence CI` workflow ellenőrzi:

- mind a 14 modulazonosítót és stabil route-ot;
- a minimális fixture-mennyiségeket és az egyedi azonosítókat;
- a teljes ügyfélút entitásait;
- a demo ügyfél CRM-ből elérhető ajánlat-, szerződés-, projekt-, pénzügy-, MyImperial- és Care-kapcsolatait;
- a lokális adatbiztonsági jelzőket;
- a kliens szintaxisát;
- a Docker Compose konfigurációt, minden modul HTTP-route-ját, a platformadatot és a health endpointot.

## Biztonsági korlátok

- A prototípus noindex staging környezetben fut.
- A runtime csak repositoryban tárolt JSON-fájlokat olvas.
- Minden e-mail-cím az `@example.test` fenntartott tartományt használja.
- A kliens nem végez külső hálózati hívást.
- A jogosultságkezelés és a szerződésgenerálás vizuális tesztfunkció; nem jelent valódi hozzáférés-vezérlést, aláírást vagy dokumentumküldést.
