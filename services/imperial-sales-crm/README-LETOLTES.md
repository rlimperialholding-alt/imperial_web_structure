# Imperial Sales CRM – telepítési útmutató

Ez a csomag az Imperial Sales CRM webes alkalmazás teljes forráskódját és a kész `dist` kiadási állományt tartalmazza.

## Helyi indítás

Előfeltétel: Node.js 22.13 vagy újabb.

```bash
npm run install:ci
npm run dev
```

A helyi fejlesztői nézet mintaadatokkal is megnyitható. A tartós éles működéshez Cloudflare D1 adatbázis szükséges `DB` kötési néven.

## Ellenőrzés és kiadás

```bash
npm run lint
npm run build
```

Az adatbázis induló sémája a `drizzle/0000_crm_core.sql` fájlban található. Az éles adminisztrátori e-mail-címet `CRM_ADMIN_EMAIL` titkos környezeti változóként kell megadni; ezt a letölthető csomag nem tartalmazza.

Az email-értesítések éles bekapcsolásához az alábbi környezeti változók szükségesek:

- `RESEND_API_KEY` – titkos API-kulcs
- `MYIMPERIAL_FROM_EMAIL` – hitelesített feladói cím, például `MyImperial <ertesites@pelda.hu>`
- `MYIMPERIAL_REPLY_TO` – opcionális válaszcím

Kulcs nélkül a rendszer biztonságosan piszkozatként kezeli az értesítéseket, és valódi emailt nem küld.

## Fő funkciók

- MiniCRM-szerű, reszponzív értékesítési felület
- Mai munkasor és teendők
- húzható Kanban pipeline
- kereshető és szűrhető adatlapok
- részletes ügyfél- és projektadatlap szerkesztés
- adatlaphoz kötött teendők létrehozása és lezárása
- tartós adatmentés, szerepkörök és auditnapló
- riportok és Sales Control Center
- Executive Dashboard napi vezetői briefinggel, profitfókuszú KPI-kkal, döntési központtal és forgatókönyv-szimulációval
- külön MyImperial ügyfélportál projektstátusszal, ütemtervvel, dokumentumokkal, fizetési mérföldkövekkel, ügyféljóváhagyásokkal és fotónaplóval
- MyImperial ChangeControl külön ChangeID-val, műszaki-, ár-, határidő- és fedezethatással, kötelező ügyféljóváhagyással
- Imperial Care garanciális ügyfélfelület külön koordinátorral, javítási bizonyítékkal és ügyfél-visszaigazolási kapuval
- egységes ügyfélteendők PlanCheck, Finance, Technical és ChangeControl forrásokból
- email-értesítési központ témánkénti beállításokkal, küldési naplóval és kötelező emberi jóváhagyással
- egyszer használható, 7 napos projektmeghívók emailes kiküldése idempotens szolgáltatói kapcsolattal

Külső e-mail, ajánlat, szerződés vagy más érzékeny üzleti művelet továbbra is emberi jóváhagyást igényel.

## ITEP és migrációs integráció

A migrációs API a fájl tényleges bájtjait az R2 `DOCUMENTS` tárban, a
csomag- és fájlmetaadatokat pedig a D1 `DB` adatbázisban tárolja. Minden
csomaghoz kötelező idempotenciakulcs tartozik, ezért egy újrapróbálkozás nem
duplikálja az adatot.

- Írás: `POST /api/integrations/migration/import`,
  `X-CRM-Migration-Token` fejléc.
- Csomagellenőrzés:
  `GET /api/integrations/migration/batches/{idempotencyKey}`.
- Tárolt fájl visszaolvasása:
  `GET /api/integrations/migration/documents/{id}`.
- ITEP read-only feed:
  `GET /api/integrations/itep/activities`,
  `X-ITEP-Token` fejléc.

Az írási és olvasási tokent kötelező külön értékre állítani. A GitHub-teszt
öt szintetikus dokumentummal ellenőrzi a tárolást, az újraindítás utáni
megmaradást, a bájtpontos visszaolvasást és a duplikációmentes újrapróbálást.
