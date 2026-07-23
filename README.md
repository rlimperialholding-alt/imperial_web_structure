# Imperial Holding web staging

Egységes, biztonságos kiindulópont az Imperial Holding webhelyeinek helyi és
CI-alapú staging ellenőrzéséhez. A repository statikus helyőrző oldalakat,
Docker Compose futtatást, nginx host-alapú routingot és GitHub Actions
füsttesztet tartalmaz.

> [!IMPORTANT]
> Ez a projekt **nem éles telepítés**. Nincs benne publikus TLS-lezárás,
> éles domain, secret, adatbázis, tartós adat vagy automatikus production
> deployment. Alapértelmezetten kizárólag a `127.0.0.1` címen figyel.

## Branch-modell

- `main`: ellenőrzött, kiadható staging-alap. Közvetlen fejlesztés helyett
  pull requesttel frissítendő.
- `staging`: integrációs ág; a feature branchek elsődleges célága.
- `feature/<rövid-név>`: rövid életű fejlesztési ág a `staging` ágból.

Javasolt folyamat:

1. `staging` frissítése és `feature/<rövid-név>` létrehozása.
2. Pull request `feature/*` → `staging`, sikeres CI után merge.
3. Ellenőrzött staging csomag esetén pull request `staging` → `main`.
4. A `main` és `staging` ágakon érdemes branch protectiont beállítani:
   kötelező PR, legalább egy review és kötelező `Staging CI` ellenőrzés.

## Gyorsindítás

Előfeltétel: Docker Desktop vagy Docker Engine Compose v2 támogatással.

PowerShell:

```powershell
Copy-Item .env.example .env
docker compose pull
docker compose up --detach --wait
```

Bash:

```bash
cp .env.example .env
docker compose pull
docker compose up --detach --wait
```

A staging portál ezután a
[http://localhost:8080](http://localhost:8080) címen érhető el. A `.localhost`
aldomainek modern böngészőkben automatikusan a loopback címre oldódnak fel,
így helyi hosts fájl módosítása általában nem szükséges.
Ha a `HTTP_PORT` értékét módosítod, a portál linkjei helyett közvetlenül a
kívánt `http://<site>.localhost:<port>` címet nyisd meg.

Leállítás:

```bash
docker compose down --remove-orphans
```

## Webhelyek

| Márka | Könyvtár | Helyi staging URL |
| --- | --- | --- |
| Imperial | `sites/imperial` | `http://imperial.localhost:8080` |
| Danish Fabrik | `sites/danish-fabrik` | `http://danish-fabrik.localhost:8080` |
| Bautica | `sites/bautica` | `http://bautica.localhost:8080` |
| Prefab | `sites/prefab` | `http://prefab.localhost:8080` |
| Casa Moderna | `sites/casa-moderna` | `http://casa-moderna.localhost:8080` |
| Family Homes | `sites/family-homes` | `http://family-homes.localhost:8080` |
| Everyday Homes | `sites/everyday-homes` | `http://everyday-homes.localhost:8080` |
| Property 360 | `sites/property-360` | `http://property-360.localhost:8080` |
| Budapesti magasépítő vállalat | `sites/budapesti-magasepito-vallalat` | `http://budapesti-magasepito-vallalat.localhost:8080` |
| BauFreund | `sites/baufreund` | `http://baufreund.localhost:8080` |
| RED Property | `sites/red-property` | `http://red-property.localhost:8080` |
| Timberhaus | `sites/timberhaus` | `http://timberhaus.localhost:8080` |

Minden site saját könyvtárban él, közös vizuális assetjeik pedig a
`sites/_shared` könyvtárból érhetők el. A `sites/_portal` a helyi belépőoldal.

## Konfiguráció

A `.env.example` csak nem érzékeny alapértékeket tartalmaz:

| Változó | Alapérték | Jelentés |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `imperial-staging` | Compose projekt neve |
| `HTTP_PORT` | `8080` | Kizárólag loopbackre publikált HTTP port |
| `NGINX_IMAGE` | `nginx:stable-alpine` | Használt nginx image |

A `.env` fájl gitignore alatt van. Secreteket ne commitolj; egy későbbi
valódi staging szolgáltatásnál használj szervezeti secret store-t és külön
hozzáférés-kezelést.

## Biztonsági alapok

- A host port csak `127.0.0.1` címen nyílik meg.
- A konténer nem root (`101:101`) felhasználóként, read-only fájlrendszerrel,
  capabilityk nélkül és `no-new-privileges` módban fut.
- A site tartalom read-only mount.
- Minden oldal `noindex,nofollow` meta tagot és `X-Robots-Tag` fejlécet kap.
- Az nginx alap biztonsági fejléceket és szigorú Content Security Policyt ad.
- Ismeretlen Host fejléc esetén az nginx válasz nélkül lezárja a kapcsolatot.
- Nincs production deployment workflow és nincs internet felé nyitott port.

Ez az alap nem helyettesíti a valódi staging környezet TLS-ét, hitelesítését,
hálózati szegmentálását, naplókezelését és titokkezelését.

## CI

A `.github/workflows/ci.yml` a `main` és `staging` pushokra, valamint az ezekre
irányuló pull requestekre fut. A workflow:

1. ellenőrzi a kötelező könyvtárakat és a keresőtiltást;
2. validálja a Compose konfigurációt;
3. elindítja az nginx stacket;
4. végigteszteli a portált, mind a 12 hostot és a health endpointot;
5. mindig leállítja és eltávolítja a tesztkonténert.

Helyi szerkezeti ellenőrzés:

```powershell
.\scripts\validate-structure.ps1
docker compose config --quiet
```

Linux/macOS:

```bash
sh scripts/validate-structure.sh
docker compose config --quiet
```

## Új tartalom vagy webhely hozzáadása

Egy meglévő oldal módosításához a megfelelő `sites/<slug>` könyvtárban
dolgozz. Új webhely esetén:

1. hozz létre `sites/<slug>/index.html` fájlt `noindex,nofollow` metával;
2. add hozzá a host → könyvtár leképezést az `nginx.conf` `map` blokkjához;
3. add a hostot a `staging.conf` `server_name` listájához;
4. bővítsd a portált, a validációs scriptet, a CI füsttesztet és ezt a táblát;
5. futtasd a helyi ellenőrzéseket, majd nyiss PR-t a `staging` ágra.

## Élesítés

Szándékosan nincs implementálva. Production bevezetés előtt külön döntés kell
a hosztingról, domainekről, TLS-ről, hozzáférésről, secret store-ról,
megfigyelhetőségről, backupokról és jóváhagyott release folyamatról.
