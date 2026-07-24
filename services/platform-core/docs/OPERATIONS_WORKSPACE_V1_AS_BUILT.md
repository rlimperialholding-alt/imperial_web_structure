# Imperial Intelligence Operations Workspace v1.0 – As-Built

## 1. Cél és rendszerszerep

Az Operations Workspace a már elkészült Imperial Intelligence Workspace v1.0 additív operatív bővítése. Nem hoz létre párhuzamos projekt-, beszerzési vagy pénzügyi rendszert. A Smart Calendar, Procurement, Finance, Document & Evidence és Control Center marad a saját tranzakcióinak hiteles forrása; az Operations Workspace közös ProjectID-alapú vetületet, adatbeviteli felületet és auditált parancssort biztosít.

Alkalmazásverzió: 1.3.0
Platformverzió: 4.8.0
Alembic head: `20260719_0004`

## 2. Megvalósított felületek

### PM Cockpit 2.0

- projektportfólió beavatkozási prioritással;
- projektkészültség, blokkolt munkacsomag, nyitott helyszíni ügy, függő indulási kapu és dokumentumblokk;
- költségkeret, lekötött összeg és tényköltség forrásmodul-vetülete;
- projektoldali fülek: fázisok, munkacsomagok, indulási kapuk, napi jelentések, helyszíni ügyek és beszerzés;
- munkacsomag-státusz és készültség auditált frissítése;
- kapuellenőrzés bizonyítékkal, eredménnyel és megjegyzéssel.

### Helyszíni PWA

- mobilra optimalizált projektlista és projektmunkalap;
- napi jelentés: dátum, létszám, időjárás, elvégzett munka, akadály, munkavédelem, minőség és bizonyíték URL;
- probléma/eltérés rögzítése súlyossággal, munkacsomaggal, hellyel, felelőssel, határidő- és pénzügyi hatással;
- az akadályos napi jelentés automatikusan helyszíni ügyet, feladatot és eseményt képez;
- online/offline állapotjelzés;
- helyi piszkozatmentés, böngészői storage-tiltás esetén memóriabeli biztonságos fallback;
- telepíthető webalkalmazás-manifest és service worker alap.

Az első kiadás offline állapotban a piszkozatot őrzi meg. A szerveroldali beküldéshez hálózati kapcsolat szükséges; valódi háttérszinkron, fájl- és fotófeltöltés későbbi adapterfeladat.

### Beszerzési munkapad

- projekt- és portfóliószintű rendelési vetület;
- szállítólevél és tényleges átvétel;
- rendelt és átvett mennyiség eltéréskontrollja;
- teljesítménynyilatkozat- és e-napló-bizonyíték státusz;
- anyaglot, tárolási hely, felelős, időjárásvédelem és mozgás;
- engedélyezett és tényleges felhasználás, maradvány és túlhasználat;
- a készlet negatívba fordulását megakadályozó blokk;
- túlhasználásnál emberi felülvizsgálatot igénylő levonási javaslat, automatikus pénzügyi levonás nélkül.

## 3. Új adatobjektumok

- `PMPhase`
- `PMWorkPackage`
- `PMGateCheck`
- `SiteDailyReport`
- `SiteIssue`
- `ProcurementOrderProjection`
- `DeliveryNoteProjection`
- `MaterialLot`
- `MaterialMovement`
- `MaterialUsageControl`

## 4. Kötelező üzleti szabályok

1. A hiteles üzleti tranzakció a forrásmodulban zárul.
2. A PM Cockpit vetületet és auditált parancsot képez, nem írja felül csendben a forrásmodult.
3. A napi jelentésben szereplő akadály nem maradhat szabad szöveges megjegyzés: ügy, feladat és esemény készül belőle.
4. Hiányos szállítólevél vagy teljesítménynyilatkozat dokumentumblokkot és vezetői/PM feladatot képez.
5. Rendelt és átvett mennyiség eltérése mennyiségi riasztást képez.
6. Anyagkészlet nem mehet negatívba.
7. Túlhasználásból kizárólag levonási javaslat születhet; szerződéses jogalap és jogosult emberi jóváhagyás szükséges.
8. Külső rendszerbe irányuló módosítás Outbox-parancson keresztül, idempotensen történik.

## 5. Új webes útvonalak

- `GET /operations`
- `GET /operations/projects/{ProjectID}`
- `POST /operations/projects/{ProjectID}/work-packages/{id}`
- `POST /operations/projects/{ProjectID}/gates/{id}`
- `GET /field`
- `GET /field/{ProjectID}`
- `POST /field/{ProjectID}/daily-reports`
- `POST /field/{ProjectID}/issues`
- `GET /procurement/workbench`
- `GET /procurement/projects/{ProjectID}`
- `POST /procurement/projects/{ProjectID}/delivery-notes`
- `POST /procurement/projects/{ProjectID}/material-movements`
- `POST /procurement/projects/{ProjectID}/usage-controls`

## 6. Új API-k

- `GET /api/operations/summary`
- `GET /api/operations/projects/{ProjectID}`
- `POST /api/operations/daily-reports`
- `POST /api/operations/issues`
- `POST /api/operations/commands`
- `POST /api/procurement/delivery-notes`
- `POST /api/procurement/material-movements`
- `POST /api/procurement/usage-controls`

## 7. Biztonsági és production-határ

A kiadás nem tartalmaz valós Imperial projektadatot, API-kulcsot vagy szolgáltatói titkot. Nem kapcsolódik éles Smart Calendar, Procurement, Finance, Drive, e-napló, Billingo, NAV vagy banki környezethez. Production előtt kötelező a PostgreSQL, SSO/2FA, HTTPS, titokkezelés, szerepkör/UAT, mentés-visszaállítás, malware-szűrés, fájltároló, monitoring és három valós ProjectID integrációs pilot.
