# Imperial Intelligence — vizuális tesztplatform

Az Imperial Holding 12 márkájához készült, lokálisan futtatható webes
tesztkörnyezet. A platform elsődleges célja a vizuálisan megnyitható,
kattintható prototípusok egy helyen történő áttekintése, reszponzív
ellenőrzése és szekciószintű review-zása.

> [!IMPORTANT]
> Ez **nem production rendszer**. Nem használ valódi ügyféladatot, külső API-t,
> production secretet, adatbázist vagy automatikus élesítést. A Compose stack
> alapértelmezetten kizárólag a `127.0.0.1` címen figyel, minden oldal
> `noindex,nofollow` jelölést kap.

## Mit tartalmaz?

- központi Imperial Intelligence admin dashboard;
- weboldalak modul az Imperial cégcsoport mind a 12 márkájával;
- márka- és oldalválasztó, összesen 131 kattintható tesztoldallal;
- elkülönített, forrásazonosítóval követhető Google Drive HTML-importok;
- desktop (1440), tablet (834) és mobile (390) nézet;
- teljes Imperial Holding főoldalprototípus sötétkék–arany–fehér arculattal;
- nyolc stabil, JSON-ban is dokumentált tartalmi szekcióazonosító;
- review panel szekcióhoz kötött, lokálisan tárolt megjegyzésekkel;
- JSON review export, külső továbbítás nélkül;
- lokális, szintetikus JSON tesztadatok;
- közös design tokenek és újrahasznosítható komponensosztályok;
- biztonságos, read-only nginx Docker Compose futtatás;
- szerkezeti, adat- és HTTP smoke tesztek GitHub Actionsben.

## Gyorsindítás

Előfeltétel: Docker Desktop vagy Docker Engine Compose v2 támogatással.

PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --detach --wait
```

Bash:

```bash
cp .env.example .env
docker compose up --detach --wait
```

Ezután nyisd meg:

- admin dashboard: [http://localhost:8080](http://localhost:8080)
- Imperial főoldal közvetlenül:
  [http://imperial.localhost:8080](http://imperial.localhost:8080)
- health check: [http://localhost:8080/healthz](http://localhost:8080/healthz)

Leállítás:

```bash
docker compose down --remove-orphans
```

Ha a `HTTP_PORT` értékét megváltoztatod, ugyanazt a portot használd a fenti
URL-ekben. A `.localhost` hostok modern böngészőben a loopback címre oldódnak
fel, hosts fájl módosítása általában nem szükséges.

Gyors, Docker nélküli preview-hoz Python 3.12-vel:

```bash
python3 scripts/serve-preview.py --port 8080
```

Ez ugyanazokat a `/site-preview/<brand>/`, `/assets/` és `/data/` útvonalakat
szolgálja ki, mint az nginx staging konfiguráció.

## Admin dashboard használata

1. A **Weboldalak / Portfólió** modulban válassz márkát a selectből vagy a 12
   márkakártya egyikével.
2. Az **Oldal vagy részprototípus** listában válaszd ki az adott márka
   főoldalát, aloldalát, kalkulátorát vagy tudásoldalát.
3. A preview eszköztáron válts **Desktop**, **Tablet** vagy **Mobile** nézetre.
4. Kattints a preview bármely kijelölhető tartalmi szekciójára. Az importált
   oldalakon a review bridge determinisztikus azonosítót ad az azonosító nélküli
   szekcióknak is.
5. Írd be a megjegyzés címét, részleteit és prioritását, majd rögzítsd.
6. A megjegyzések oldalútvonalhoz és szekcióazonosítóhoz kötve, a böngésző
   `localStorage` tárában maradnak.
7. A **JSON export** gombbal letölthető egy hordozható tesztfájl.

Mind a 12 márkához van futtatható, katalógusban regisztrált webes anyag. Az
eredeti 50 oldal mellett a Drive-forrásokból hét márkaspecifikus bemutatóoldal
és a Family Homes 13 oldalas webhelye is elérhető. A forrásból generált oldalak
eredeti specifikációja a megfelelő márkakönyvtár `source/website-spec.md`
fájljában marad visszakövethető.

## Stabil tartalmi szekcióazonosítók

| ID | Jelentés |
| --- | --- |
| `hero` | Nyitó szekció |
| `trust` | Bizalmi mutatók |
| `portfolio` | Márkaportfólió |
| `capabilities` | Komplex szakértelem |
| `projects` | Kiemelt projektek |
| `sustainability` | Fenntartható jövőkép |
| `news` | Hírek és perspektívák |
| `contact` | Kapcsolati felhívás |

Az ID-k egyszerre szerepelnek a `sites/imperial/index.html` DOM-jában és a
`sites/_shared/assets/data/imperial-home.json` `sections` listájában. A
validáció hibával leáll, ha a két forrás eltér.

## Mappastruktúra

```text
sites/
├── _portal/
│   ├── index.html                 # központi admin dashboard
│   └── data/
│       ├── brands.json            # a 12 márka lokális tesztadata
│       └── artifacts.json         # 131 tesztoldal és Drive-forrásazonosító
├── _shared/assets/
│   ├── tokens.css                 # közös szín-, térköz-, tipó- és radius tokenek
│   ├── components.css             # közös gomb, ikon, logó és accessibility alapok
│   ├── admin.css / admin.js       # dashboard megjelenés és működés
│   ├── imperial.css / imperial.js # főoldal megjelenés és működés
│   ├── review-bridge.*             # szekciókijelölés minden importált oldalon
│   └── data/imperial-home.json    # szintetikus főoldaladatok
├── imperial/index.html            # teljes Imperial Holding prototípus
└── <márka>/
    ├── drive/                      # Drive-ról importált teljes oldalak
    ├── source/                     # visszakövethető forrásspecifikáció
    └── assets/                     # saját CSS, JS, kép, ikon, font és vendor
```

Az admin JavaScript kizárólag same-origin JSON fájlokat tölt be. Nincs
analytics, cookie-alapú követés, külső font, futásidejű CDN, API vagy
adatküldés. A Drive csak fejlesztési forrásként szolgált; a böngésző nem
kapcsolódik a Drive-hoz.

## Drive-import és forráskövetés

A `sites/_portal/data/artifacts.json` az egyetlen tesztoldal-katalógus. Minden
Drive-ból importált elemhez tartozik:

- márkaazonosító és helyi útvonal;
- felhasználóbarát oldalnév;
- típus (`drive-full-site`, `drive-partial` vagy `drive-knowledge`);
- az eredeti Google Drive fájlazonosító.

Csak futtatható webes artefaktumok kerültek a repositoryba. Ügyféladatot,
értékesítési adatbázist, üzleti spreadsheetet, production secretet és
operatív dokumentumot a rendszer nem importál. A Drive-ról származó oldalak
`noindex,nofollow` jelölést és közös review bridge-et kapnak; az űrlapok
tesztmódban nem továbbítanak adatot.

## A 12 márka

| Márka | Könyvtár | Helyi URL |
| --- | --- | --- |
| Imperial Holding | `sites/imperial` | `http://imperial.localhost:8080` |
| Danish Fabrik | `sites/danish-fabrik` | `http://danish-fabrik.localhost:8080` |
| Bautica | `sites/bautica` | `http://bautica.localhost:8080` |
| Prefab | `sites/prefab` | `http://prefab.localhost:8080` |
| Casa Moderna | `sites/casa-moderna` | `http://casa-moderna.localhost:8080` |
| Family Homes | `sites/family-homes` | `http://family-homes.localhost:8080` |
| Everyday Homes | `sites/everyday-homes` | `http://everyday-homes.localhost:8080` |
| Property 360 | `sites/property-360` | `http://property-360.localhost:8080` |
| Budapesti Magasépítő Vállalat | `sites/budapesti-magasepito-vallalat` | `http://budapesti-magasepito-vallalat.localhost:8080` |
| BauFreund | `sites/baufreund` | `http://baufreund.localhost:8080` |
| RED Property | `sites/red-property` | `http://red-property.localhost:8080` |
| Timberhaus | `sites/timberhaus` | `http://timberhaus.localhost:8080` |

## Tesztadat- és review-modell

### Tesztadatok

- `brands.json`: márkanév, slug, monogram, prototípusállapot és vizuális akcentus.
- `artifacts.json`: az oldalválasztó 131 bejegyzése és a Drive-források
  visszakövethetősége.
- `imperial-home.json`: szekciók, szintetikus mutatók, portfólió-, projekt- és
  hírkártyák.
- A `containsCustomerData: false` mezőt a CI és a helyi validátor is ellenőrzi.
- A projektnevek, helyszínek, dátumok és mutatók demonstrációs mintaadatok.

### Review megjegyzések

A review rekord mezői:

```json
{
  "brandId": "imperial",
  "pagePath": "/drive/venture/venture-studio.html",
  "pageTitle": "Imperial Venture Studio",
  "sectionId": "hero",
  "title": "CTA pontosítása",
  "comment": "A fő CTA legyen rövidebb.",
  "priority": "normal",
  "createdAt": "2026-07-23T12:00:00.000Z"
}
```

A rekordok nem kerülnek szerverre. Böngészőprofil- vagy site data törléskor
elvesznek, ezért hosszabb review folyamat előtt használd a JSON exportot.

## Konfiguráció

| Változó | Alapérték | Jelentés |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `imperial-staging` | Compose projekt neve |
| `HTTP_PORT` | `8080` | Csak loopbackre publikált HTTP port |
| `NGINX_IMAGE` | `nginx:stable-alpine` | Nginx image |

A `.env` gitignore alatt van. Production secretet vagy ügyféladatot ne írj
sem `.env` fájlba, sem a JSON fixture-ökbe.

## Biztonsági alapok

- a host port csak `127.0.0.1` címen nyílik meg;
- az nginx `101:101` felhasználóként, read-only fájlrendszerrel fut;
- minden capability le van dobva, `no-new-privileges` aktív;
- a webtartalom read-only volume;
- minden oldal `noindex,nofollow`, a válaszok `X-Robots-Tag` fejlécet kapnak;
- a Content Security Policy csak same-origin scriptet, fetch-et, assetet és
  preview iframe-et enged;
- a `/site-preview/<brand>/` útvonal explicit, 12 elemű allow-listet használ;
- nincs production deployment workflow.
- az importált, önálló HTML-prototípusok saját inline megjelenítési logikája
  csak a loopback staging környezetben engedélyezett; hálózati kapcsolataikat a
  CSP továbbra is same-originra korlátozza;
- a Bootstrap-oldalak teljes Bootstrap CSS/JavaScript és Bootstrap Icons
  csomagja márkánként, helyben található; futásidőben nincs CDN-függőség.

Az iframe támogatása miatt `X-Frame-Options: SAMEORIGIN` és
`frame-ancestors 'self'` van beállítva; külső oldal továbbra sem ágyazhatja be a
prototípust.

## Helyi ellenőrzések

PowerShell:

```powershell
.\scripts\validate-structure.ps1
docker compose config --quiet
docker compose up --detach --wait
Invoke-WebRequest http://localhost:8080/healthz -UseBasicParsing
docker compose down --remove-orphans
```

Linux/macOS:

```bash
sh scripts/validate-structure.sh
docker compose config --quiet
docker compose up --detach --wait
curl --fail http://localhost:8080/healthz
docker compose down --remove-orphans
```

A `.github/workflows/ci.yml`:

1. ellenőrzi a 12 site belépési pontját és a noindex jelölést;
2. parse-olja a JSON fixture-öket és validálja mind a 131 katalógusbejegyzést;
3. ellenőrzi az importált fájlok Drive-forrásazonosítóját, review bridge-ét és
   a futásidejű Bootstrap CDN hiányát;
4. összeveti a stabil Imperial szekció-ID-ket a DOM-mal;
5. validálja a Compose konfigurációt és elindítja az nginx stacket;
6. HTTP-n ellenőrzi az admint, a márka- és artefaktumadatokat, mind a 12 hostot,
   valamint négy reprezentatív Drive-preview útvonalat;
7. asset-crawlerrel minden HTML-, CSS- és JavaScript-függőséget HTTP-n is
   ellenőriz;
8. mind a 131 oldalt desktop, tablet és mobil nézetben megnyitja, ellenőrzi a
   konzolt és a hálózati hibákat, majd 393 képernyőképet készít;
9. ellenőrzi a health endpointot, majd minden esetben eltávolítja a tesztstacket.

## Branch-modell és kiadás

- `main`: ellenőrzött, kiadható staging-alap;
- `staging`: integrációs ág, a feature branchek célága;
- `feature/<rövid-név>`: rövid életű fejlesztési ág a `staging` ágból.

Javasolt folyamat: feature → draft PR a `staging` ágra → review és sikeres CI →
kézi merge. A repository szándékosan nem tartalmaz automatikus production
deploymentet vagy automatikus merge-et.

## Következő, külön jóváhagyást igénylő lépések

- tartós review backend, SSO és jogosultságkezelés;
- jóváhagyott CMS vagy tartalom-API integráció;
- éles domainek, TLS, secret store, monitoring és release folyamat;
- accessibility audit és támogatott böngészőmátrix;
- production adatmodell és adatmegőrzési szabályok.
