# Többcégű connector-kezelés

Az Imperial Intelligence egy cégcsoporton belül tetszőleges számú jogi személyt
és kapcsolati fiókot kezel. A rendszer két tulajdonosi szintet különböztet meg:

- `LEGAL_ENTITY`: egy konkrét céghez tartozó Billingo-, bank- vagy
  Cégkapu/hatósági tárhely kapcsolat;
- `GROUP`: a teljes cégcsoport által közösen használt Meta Ads-, Google Ads-
  vagy belső CRM-kapcsolat.

A pénzügyi és hatósági connectorok cégszintű hozzárendelés nélkül nem
szinkronizálhatók. Az adatbázis és a futásidejű ellenőrzés is kikényszeríti ezt.
Minden beolvasott számla és tranzakció metaadata tartalmazza a
`legalEntityId` és `connectorAccountId` mezőt, így az azonos külső
azonosítók sem keverik össze a cégeket.

## Kezdő cégjegyzék

A seed 12, a tulajdonos által megadott céget hoz létre. Minden céghez egy-egy
`DISCONNECTED` állapotú Billingo-, bank- és Cégkapu-helyfoglaló tartozik.
A cégek adószáma nincs kitalálva: azt csak ellenőrzött törzsadatból szabad
kitölteni.

## Új cég hozzáadása

Új cég kódmódosítás nélkül adható hozzá a `LEGAL_ENTITIES_JSON` nem titkos
környezeti változóban. A változó JSON-tömb:

```json
[
  {
    "id": "imperial-holding:uj-ceg",
    "slug": "uj-ceg",
    "legalName": "Új Cég Kft.",
    "taxNumber": "ellenőrzött-adószám"
  }
]
```

További kapcsolatok a `BUSINESS_CONNECTOR_ACCOUNTS_JSON` nem titkos
változóban regisztrálhatók:

```json
[
  {
    "id": "billingo-uj-ceg",
    "kind": "BILLINGO",
    "scope": "LEGAL_ENTITY",
    "legalEntityId": "imperial-holding:uj-ceg",
    "externalAccountId": "all",
    "displayName": "Billingo – Új Cég Kft.",
    "status": "ACTIVE",
    "scopes": ["invoices.read"]
  }
]
```

## Titkok

A hozzáférési kulcs nem kerülhet a fenti két változóba vagy az adatbázisba.
A kulcsokat a GitHub `imperial-test` Environment
`CONNECTOR_ACCESS_TOKENS_JSON` secretjében, connector-azonosító szerint kell
tárolni. Példa csak a szerkezetre:

```json
{
  "billingo-uj-ceg": { "accessToken": "***" },
  "bank-uj-ceg": { "accessToken": "***" }
}
```

A cégkapus helyek jelenleg biztonságos nyilvántartási és monitoring-helyek.
Valódi automatikus olvasás csak a konkrét, hivatalos hozzáférési mód és
hitelesítő adatok jóváhagyása után kapcsolható be; a rendszer nem próbál
jelszavas böngészőautomatizálást.

## Állapot lekérdezése

Hitelesített belső kérés:

```text
GET /v1/companies/connectors
```

A válasz cégenként mutatja a Billingo-, bank- és Cégkapu-kapcsolat
konfiguráltságát, valamint külön a közös Meta/Google Ads kapcsolatokat.
