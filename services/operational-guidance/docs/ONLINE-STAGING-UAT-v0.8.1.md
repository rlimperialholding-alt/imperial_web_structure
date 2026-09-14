# Online staging telepítés és UAT – v0.8.1

## Cél

A v0.8.1 a production candidate valós környezetben történő bizonyítására készült. A GO döntéshez nem elegendő a konténerek elindulása: a rendszernek a Directus, Google Drive, Gmail, szerepkörök, Process Cardok és checklistek teljes üzleti láncát bizonyítania kell.

## Kötelező előfeltételek

- Linux staging szerver Docker Compose-zal és Python 3-mal;
- HTTPS reverse proxy és végleges staging API URL;
- kitöltött staging `.env`;
- Google service account, Drive-hozzáférés és domain-wide delegation;
- Gmail delegált felhasználó;
- Directus static token;
- a szolgáltatásképek rögzített verziói;
- az öt valós munkakör egyedi Bearer-tokenje.

A Gmail domain-wide delegation kötelező scope-jai:

- `https://www.googleapis.com/auth/gmail.send`
- `https://www.googleapis.com/auth/gmail.readonly`

A Drive scope:

- `https://www.googleapis.com/auth/drive`

## Telepítés

```bash
export SSH_TARGET=deploy@staging.example.hu
export RELEASE_ZIP=/path/imperial-intelligence-integration-hub-v0.8.1-online-staging-uat.zip
export STAGING_ENV_FILE=/secure/path/staging.env
export GOOGLE_SERVICE_ACCOUNT_FILE=/secure/path/google-service-account.json
export BASE_URL=https://staging.example.hu
sh scripts/ops/deploy-staging-remote.sh
```

A telepítő:

1. verziózott release-mappát hoz létre;
2. felmásolja a ZIP-et és a titkokat;
3. offline preflightot futtat;
4. elindítja az infrastruktúrát;
5. migrálja az adatbázist;
6. bootstrapolja a Directust;
7. betölti a 99/99 katalógust;
8. online preflightot futtat;
9. lefuttatja a három pilotfolyamatot;
10. csak siker után állítja át a `current` symlinket.

## Három kötelező pilot

- `SAL-001`: értékesítés;
- `PRJ-001`: projektvégrehajtás;
- `FIN-001`: pénzügy.

Mindhárom pilot bizonyítja:

- Process Card generálás;
- Drive draft PDF és PNG;
- Gmail jóváhagyási levél;
- service és nem ügyvezető szerepkör approval-tiltása;
- ügyvezetői jóváhagyás;
- Drive érvényes mappa;
- checklist idempotens indítás;
- teljes IGEN ág és CLOSED kapu;
- blocking NEM ág és HOLD kapu.

## GO feltétel

Az `runtime/uat/online-staging-uat-v0.8.1.json` státusza kizárólag akkor `GO`, ha minden ellenőrzés sikeres. Bármely FAIL esetén a kiadás `NO-GO`, a `current` symlink nem módosulhat.

## Rollback

```bash
export SSH_TARGET=deploy@staging.example.hu
export ROLLBACK_RELEASE=/opt/imperial-guidance/releases/<korábbi-release>/<app-mappa>
sh scripts/ops/rollback-staging-remote.sh
```

Adatbázis-visszaállítás külön, jóváhagyott restore-eljárással történhet; alkalmazás-rollback nem jelent automatikus adatbázis-downgrade-et.

## v0.8.1 deployment correction

The remote deploy and rollback scripts execute Directus/database/Redis-dependent checks inside the API container. The deployment uses the stable `imperial-guidance` Compose project name and a release-specific Imperial image tag. Do not remove these safeguards: they preserve shared volumes across releases and make application rollback effective.
