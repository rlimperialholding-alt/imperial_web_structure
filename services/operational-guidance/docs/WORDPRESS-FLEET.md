# Önálló WordPress-bloghálózat

## Kötelező elv: nincs WordPress Multisite

A márkák technikailag és szerkesztőségileg nem kapcsolódhatnak össze. Ezért a rendszer 11 külön WordPress-stacket generál. Egy stack sem oszt meg adatbázist, felhasználót, médiatárat, titkos kulcsot, Docker-volume-ot vagy Docker-networköt egy másik márkával.

## Márkánként elkülönített elemek

- WordPress runtime;
- MariaDB runtime és adatvolume;
- WordPress fájl- és médiavolume;
- admin-felhasználó;
- szerzői felhasználó és megjelenített szerzőnév;
- HMAC publikációs titok;
- blog URL és API-végpont;
- téma, témanév és színpaletta;
- tiltott külső márkadomain-lista;
- opcionális, külön médiadomain vagy objektumtár.

## Egyedi szerzők

A `wordpress-fleet/brand-fleet.json` minden márkához egy külön szerkesztői álnevet rendel. A generátor ellenőrzi, hogy az alábbiak egyike se ismétlődhessen:

- author login;
- author display name;
- author email.

A WordPress plugin figyelmen kívül hagy minden bejövő szerzőazonosítót, és mindig az adott oldal környezeti változóiban beállított szerzőt rendeli a cikkhez.

## Keresztmárkás publikáció tiltása

A védelem két helyen működik.

### Integration Hub

A Hub a Directus `brand_key` mezőjét összeveti a céloldal Brand Registry szerinti márkájával. Eltérés esetén a publikálás meghiúsul.

### WordPress plugin

A fogadó plugin ellenőrzi:

- `X-Imperial-Brand-Key` fejléc;
- `X-Imperial-Website-Key` fejléc;
- payload szintű `brand_key`;
- tartalmi elem `brand_key`;
- HMAC-aláírás és időbélyeg;
- tiltott másik márkadomain jelenléte a címben, kivonatban vagy cikkben.

## Generálás

```bash
python wordpress-fleet/generate_fleet.py --clean
```

## Titkok létrehozása

```bash
cd wordpress-fleet
python provision_secrets.py
```

A parancs márkánként külön véletlen adatbázis-, admin- és publikációs titkot ír a nem verziókezelt `.env` fájlba.

## Hub célfájl előállítása

A production URL-ek beállítása után:

```bash
cd wordpress-fleet
python export_hub_targets.py
```

Ez létrehozza a `secrets/website-targets.runtime.json` fájlt. A Hub környezetében ezután a `WEBSITE_TARGETS_FILE=secrets/website-targets.runtime.json` értéket kell használni.

## Egy blog indítása

```bash
cd wordpress-fleet/generated/imperial
docker compose up -d
```

## Publikációs cím

```text
POST /wp-json/imperial/v1/articles
```

A blogcélpontokat a `config/website-targets.json` fájlban kell engedélyezni, miután a tényleges domain és az adott blog `.env` fájljában szereplő HMAC-secret bekerült.

## További elkülönítés

A csomag már egy szerveren is elkülönített Compose-projekteket használ. Magasabb biztonsági szintnél márkánként külön VM, külön felhőprojekt vagy külön Kubernetes namespace javasolt. A kód ezt nem akadályozza, mert minden generált mappa önállóan telepíthető.
