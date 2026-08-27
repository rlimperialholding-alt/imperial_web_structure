# Billingo, Meta és Google Ads – biztonságos bekötés

## Tesztfelület

- Közös Imperial Intelligence munkatér: `http://localhost:8080/workspace/`
- CRM: `http://localhost:18787/`
- Digital Project Managers: `http://localhost:8080/digital-project-managers/`

A helyi CRM a tesztkörnyezetben a `developer@terminal.local` felhasználót
adminisztrátorként kezeli. Ez csak a helyi teszt Compose-ra vonatkozik.

## Biztonsági mód

A három kapcsolat kizárólag olvasó műveleteket tartalmaz:

- Billingo: meglévő számlák listázása;
- Meta: kampánystatisztikák és lead-konverziók olvasása;
- Google Ads: kampánystatisztikák olvasása.

Nincs implementálva számlakiállítás, kampánylétrehozás, kampánymódosítás,
licitmódosítás vagy költési művelet. A betöltött pillanatképek az ITEP
`SourceEvent` táblájába kerülnek `READ_ONLY` megjelöléssel.

## GitHub Environment

Helye:

`Repository → Settings → Environments → imperial-test`

Secrets:

- `BILLINGO_API_KEY`
- `META_ADS_ACCESS_TOKEN`
- `GOOGLE_ADS_DEVELOPER_TOKEN`
- `GOOGLE_ADS_CLIENT_ID`
- `GOOGLE_ADS_CLIENT_SECRET`
- `GOOGLE_ADS_REFRESH_TOKEN`

Nem titkos változók:

- `BILLINGO_EXTERNAL_ACCOUNT_ID` – általában `all`
- `META_ADS_AD_ACCOUNT_ID` – például `act_123456789`
- `GOOGLE_ADS_CUSTOMER_ID` – kötőjelek nélkül
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID` – csak kezelői fióknál, kötőjelek nélkül

A Google Ads API ugyanazt az OAuth scope-ot használja olvasáshoz és íráshoz,
ezért a csatlakoztatott Google Ads felhasználónak a Google Ads felületén is
`Read only` szerepkört kell adni. A kód ettől függetlenül kizárólag a
`searchStream` riportvégpontot hívja, mutate műveletet nem tartalmaz.

A valódi kapcsolat ellenőrzése a GitHub Actions oldalon a
`Business connectors read-only contract` munkafolyamattal indítható. A napló
csak a beolvasott tételek darabszámát írja ki, ügyféladatot és titkot nem.
