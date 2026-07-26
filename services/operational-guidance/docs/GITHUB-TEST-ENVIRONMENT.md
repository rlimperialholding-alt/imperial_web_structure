# Imperial Intelligence – GitHub tesztkörnyezet

## Felépítés

- **Integration Hub**: a meglévő Python/FastAPI vezérlési réteg.
- **ITEP Core**: a belső Node/TypeScript feladat- és szabálykikényszerítő szolgáltatás.
- **Imperial Sales CRM + MyImperial**: a repositoryba integrált saját CRM.
- **CRM D1 + R2**: tartós strukturált nyilvántartás és tényleges fájltárolás a
  lokális Cloudflare/Miniflare tesztkörnyezetben.
- **Hub PostgreSQL + Redis** és **ITEP PostgreSQL**: elkülönített tesztállapot.
- **Mock External**: szintetikus Billingo- és bank-kompatibilis végpontok.

A teszt nem vár egy még nem létező külső CRM URL-re. A saját CRM a Compose
stack részeként indul. A migrációs írás és az ITEP olvasás két külön
szolgáltatáskulcsot használ.

## Szükséges GitHub Environment

Az Environment neve `imperial-test`.

Egyetlen tartós GitHub Secret szükséges:

- `ITEP_IDENTITY_SHARED_SECRET` – legalább 32 véletlen karakter.

A workflow futásonként új, ideiglenes `CRM_MIGRATION_TOKEN` és
`ITEP_CRM_READ_TOKEN` értéket készít. Ezeket nem kell kézzel létrehozni, és
nem kerülnek a repositoryba.

## Az öt dokumentumos próba

Az `Internal CRM Migration Integration Test`:

1. elkészíti az elkülönített tesztkulcsokat;
2. felépíti és elindítja a teljes Compose stacket;
3. öt szintetikus PDF-et ír be a CRM migrációs API-ján;
4. ellenőrzi a D1-metaadatokat, az R2-ben tárolt bájtokat és a SHA-256
   ellenőrzőösszegeket;
5. ugyanazzal az idempotenciakulccsal megismétli a kérést, és igazolja, hogy
   nem keletkezik duplikáció;
6. újraindítja a CRM-et, majd mind az öt fájlt ismét visszaolvassa;
7. read-only ITEP contract tesztet és teljes Hub–ITEP CRM-szinkront futtat;
8. feltölti a diagnosztikát, végül törli a futás elkülönített tesztvolume-jait.

A `run-live-crm` PR-címke neve kompatibilitási okból változatlan; a mögötte
futó teszt már a repositoryban lévő saját CRM-et használja.

## Biztonsági korlátok

- Az ITEP kizárólag a read-only activities végpontot és olvasási tokent kapja.
- Írás csak a migrációs végponton, külön tokennel történhet.
- A GitHub-próba kizárólag generált, szintetikus fájlokat használ.
- Valódi ügyféladat-migráció az öt dokumentumos próba sikere után is csak
  külön emberi jóváhagyással indítható.
- A teszt nem csatlakozik production CRM-hez vagy production adatbázishoz.
- Secret nem kerül commitba vagy naplóba.
