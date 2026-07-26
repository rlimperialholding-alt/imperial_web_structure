# Élesítési runbook

## 1. Szerver és domainek

- külön Linux szerver vagy Kubernetes környezet;
- HTTPS reverse proxy az API, Directus és n8n előtt;
- Directus és n8n adminfelület IP/VPN vagy SSO mögött;
- PostgreSQL és Redis ne legyen publikus interneten elérhető.

## 2. Titkok

Cserélendő minden alapérték:

- `API_ADMIN_TOKEN`;
- `DIRECTUS_KEY`, `DIRECTUS_SECRET`, adminjelszó és static token;
- `DIRECTUS_WEBHOOK_SECRET`;
- `N8N_ENCRYPTION_KEY`;
- MinIO/S3 kulcsok;
- minden engedélyezett weboldal külön HMAC secretje;
- Google OAuth refresh token és ingatlan.com hozzáférés.

Élesben a `.env` helyett secret manager használata javasolt.

## 3. Adatbázis

- napi automatikus PostgreSQL-mentés;
- legalább havi visszaállítási próba;
- éles sémafrissítéshez Alembic migráció;
- napló- és metrikaadatok megőrzési szabálya.

A jelenlegi `Base.metadata.create_all()` új telepítéshez megfelelő, meglévő éles adatbázis módosítására nem helyettesíti a migrációt.

## 4. Bevezetési sorrend

1. lokális Docker Compose indulás;
2. Directus bootstrap és a teljes Brand Registry rekordjai;
3. GA4 és Search Console olvasási próba;
4. Google Business Profile account/location discovery;
5. ingatlan.com `apitest` teljes mezővalidáció;
6. egy staging weboldal HMAC publikálása;
7. minden engedélyezni kívánt staging oldal;
8. élesítés márkánként, visszaállítási próbával.

## 5. Kötelező staging tesztek

- hibás és lejárt HMAC-aláírás elutasítása;
- nem jóváhagyott tartalom blokkolása;
- több weboldalas batch részleges hibája;
- `valid_from` időzített publikálás;
- `valid_until` automatikus visszavonás;
- ingatlan.com 401 után tokenfrissítés;
- Google API kvóta- és jogosultsági hiba;
- Directus, Redis vagy célweboldal átmeneti kiesése.

## 6. Operational Guidance Engine élesítése

Kötelező környezeti változók:

- `OPERATIONAL_CATALOG_FILE`;
- `PROCESS_CATALOG_COLLECTION`;
- `CHECKLIST_TEMPLATE_COLLECTION`;
- `CHECKLIST_INSTANCE_COLLECTION`;
- `PROCESS_CARD_COLLECTION`;
- `PROCESS_CARD_DRIVE_FOLDER_ID`;
- `PROCESS_CARD_APPROVER_EMAIL`;
- `PROCESS_CARD_GMAIL_DELEGATED_USER`;
- `DIRECTUS_STATIC_TOKEN`;
- `DIRECTUS_WEBHOOK_SECRET`.

Élesítési sorrend:

1. `python scripts/bootstrap_directus.py` – kollekciók és a 99/99 katalógus betöltése;
2. `python scripts/import_operational_catalog.py` – helyi runtime egyeztetése;
3. n8n-ben az `imperial-operational-guidance-workflow.json` importja;
4. Directus webhook beállítása a process- és checklist-kollekció változásaira;
5. Google service account hozzáadása a cél Drive-mappához;
6. delegált Gmail-küldés és ügyvezetői cím tesztje;
7. egy folyamatcsaládonkénti pilot;
8. 30 napos UAT után éles státusz.

Kötelező Operational Guidance staging tesztek:

- mind a 99 sablon importja, duplikáció nélkül;
- változatlan forrás ne hozzon létre új verziót;
- folyamat- és checklist-változás is hozzon létre új draftot;
- draft ne jelenjen meg érvényes Drive-mappában;
- ügyvezetői jóváhagyás után verziózott publikálás;
- blocking NEM → HOLD;
- hiányzó evidence → beküldés blokkolva;
- CLOSED kapu előtt a külső workflow ne lépjen tovább;
- webhook kiesés után a 15 perces safety-net hozza helyre az állapotot;
- jogosulatlan API-hívás 401 választ kapjon.
- az `operational_runtime` volume az API és a worker között közös és tartós legyen;
- sikertelen Gmail-értesítés ötperces retry után eljusson az ügyvezetőhöz;
- draft Drive-mappa jóváhagyás után archívumba kerüljön.

## 7. v0.6.0 staging indítás

A staging környezethez a két Compose-fájlt együtt kell használni:

```bash
cp .env.staging.example .env
# minden REPLACE érték kitöltése

docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build
```

Az API csak akkor lesz healthy, ha:

- a konfiguráció érvényes;
- az adatbázis elérhető;
- a Redis elérhető;
- a 99/99 operatív katalógus betölthető;
- a közös runtime volume írható.

Részletes kapu: `docs/STAGING-UAT-v0.6.0.md`.

## 8. v0.7.0 production-candidate telepítés

A production környezet három Compose-fájlt használ:

```bash
docker compose --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.staging.yml \
  -f docker-compose.production.yml \
  config
```

Kötelező új változók:

- `HUMAN_ROLE_TOKENS_JSON` – pontosan az öt valós munkakör;
- `SERVICE_TOKENS_JSON` – gépi integrációs identitások;
- `N8N_SERVICE_TOKEN` – egyezzen a service token-regiszter n8n értékével;
- `METRICS_TOKEN`;
- `TRUSTED_HOSTS_JSON`;
- `REQUIRE_IDEMPOTENCY_KEYS=true`;
- `DOCS_ENABLED=false`;
- minden külső konténerhez konkrét, nem `latest` image tag/digest.

Telepítés előtt:

```bash
python scripts/production_preflight.py --env-file .env
make backup
make backup-verify
make restore-drill
```

Automatizált telepítés és canary:

```bash
BASE_URL=https://api.pelda.hu make deploy
```

Alkalmazáskép-visszaállítás:

```bash
make rollback
```

A rollback nem végez automatikus adatbázis-downgrade-ot. Részletek:

- `docs/PRODUCTION-UAT-v0.7.0.md`;
- `docs/BACKUP-RESTORE-v0.7.0.md`;
- `docs/AUTHORIZATION-MATRIX-v0.7.0.md`.
