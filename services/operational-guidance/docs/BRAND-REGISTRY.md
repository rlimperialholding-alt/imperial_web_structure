# Többmárkás Brand Registry

## Cél

A publikációs rendszerben nincs öt- vagy tizenegyoldalas technikai korlát. A márkák és weboldalak konfigurációból töltődnek, ezért új márka, új domain, aldomain vagy nyelvi változat alkalmazáskód módosítása nélkül felvehető.

## Jelenlegi márkák

| Kulcs | Márka | Weboldalállapot |
|---|---|---|
| `imperial` | Imperial Holding | aktív URL, publikálókulcs még beállítandó |
| `danishfabrik` | Danish Fabrik | aktív URL, publikálókulcs még beállítandó |
| `bautica` | Bautica | aktív URL, publikálókulcs még beállítandó |
| `prefab` | Prefab | aktív URL, publikálókulcs még beállítandó |
| `timberhaus` | Timberhaus | aktív URL, publikálókulcs még beállítandó |
| `casamoderna` | Casa Moderna | pontos URL beállítandó |
| `property360` | Property 360 | pontos URL beállítandó |
| `everydayhomes` | Everyday Homes | pontos URL beállítandó |
| `familyhomes` | Family Homes | pontos URL beállítandó |
| `budapestimagasepito` | Budapesti Magasépítő Vállalat | pontos URL beállítandó |
| `redproperty` | RED Property | pontos URL beállítandó |

## Konfigurációs fájlok

- `config/brand-registry.json`: márkák, megjelenési nevek, webhelyek és alap URL-ek;
- `config/website-targets.json`: publikációs végpont, engedélyezés és oldalanként eltérő titkos aláírókulcs;
- `GA4_PROPERTIES_JSON`: márkánként egy vagy több GA4 property;
- `SEARCH_CONSOLE_SITES_JSON`: márkánként egy vagy több Search Console property;
- `GBP_LOCATIONS_JSON`: márkánként több Google Business Profile helyszín.

A `WEBSITE_TARGETS_JSON` környezeti változó felülírhatja a fájlban megadott célokat. Így az éles secret nem kerül forráskódba.

## Új márka felvétele

1. Adj új objektumot a `brands` listához.
2. Adj hozzá legalább egy egyedi `website.key` értéket.
3. Add meg a pontos `base_url` értéket, vagy hagyd `null` értéken a beállításig.
4. Vedd fel ugyanazt a weboldalkulcsot a `website-targets.json` fájlba.
5. Telepítsd a fogadómodult az oldalra.
6. Generálj külön, erős HMAC-kulcsot.
7. Csak a staging tesztek után állítsd `enabled: true` értékre.
8. Futtasd újra a Directus bootstrap scriptet; az upserteli a rekordot.

## Több weboldal egy márkához

Egy márka `websites` listája több elemet tartalmazhat, például:

```json
{
  "key": "imperial",
  "name": "Imperial Holding",
  "websites": [
    {
      "key": "imperial-hu",
      "name": "Imperial Magyarország",
      "base_url": "https://example.hu"
    },
    {
      "key": "imperial-en",
      "name": "Imperial English",
      "base_url": "https://example.com"
    }
  ]
}
```

A Directus tartalom `website_keys` mezője dönti el, melyik webhely vagy webhelyek kapják meg az adott tartalmat.

## Állapotellenőrzés

A `python -m scripts.validate_brand_registry` paranccsal helyben ellenőrizhető a teljes jegyzék és a publikálási készültség. Az admin API-n is lekérhető, melyik márka és webhely áll készen publikálásra:

```text
GET /api/v1/brands
GET /api/v1/brands/{brand_key}
```

A válasz nem adja vissza a titkos kulcsot, csak azt jelzi, hogy a cél regisztrált, engedélyezett és technikailag publikálásra kész-e.
