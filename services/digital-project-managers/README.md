# Imperial Intelligence Digital Project Managers v0.2.0

FastAPI service for Digitális Kálmán, Digitális Máté and Digitális Misi. The
service is deliberately fail-closed: it has no SQLite mode, no local bootstrap
database and no committed credential fallback.

## Architecture

- PostgreSQL is the only supported persistence layer.
- Alembic owns schema changes and deterministic seed data.
- PostgreSQL triggers audit every insert, update and delete, including seeds.
- Redis/RQ runs eligible R0-R3 tasks asynchronously.
- OIDC/JWT authenticates API calls. Project claims and scopes are enforced on
  every project-scoped endpoint.
- The repository's `platform.json` projects, customers and users stay canonical
  and are read through `PlatformModelAdapter`; the service stores only external
  references.
- Partner Control, Tender Portal, myImperial and e-mail use typed, fail-closed
  adapter interfaces. They remain disabled until both configuration and mounted
  credential files are present.
- R6 and R7 actions are blocked before queue or adapter execution. A structured
  approval/escalation record is created, but approval never turns an R6-R7 task
  into an automatically executable external action.

## Local start

Prerequisite: Docker Compose v2.

Create two untracked secret files under the repository root:

```powershell
New-Item -ItemType Directory -Path .\secrets -Force
[IO.File]::WriteAllText(
  (Join-Path (Resolve-Path .\secrets) 'dpm_db_password.txt'),
  [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
)
[IO.File]::WriteAllText(
  (Join-Path (Resolve-Path .\secrets) 'dpm_auth_hs256_secret.txt'),
  [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(64))
)
```

Then start the optional profile:

```powershell
docker compose --profile digital-pm up --detach --build --wait
```

The API is available at `http://127.0.0.1:8090`; readiness is
`GET /health/ready`. For shared staging or production, configure
`DPM_AUTH_JWKS_URL` and an existing OIDC issuer instead of the local HS256
secret.

Stop and remove local state:

```powershell
docker compose --profile digital-pm down --volumes --remove-orphans
```

## Validation

The test profile runs formatting, lint, type checking and the PostgreSQL-backed
test suite:

```powershell
docker compose --profile digital-pm-test run --rm dpm-tests
```

The GitHub workflow also starts the API and worker, checks both health endpoints,
verifies the Alembic head and confirms exactly three seeded managers.

## Required deployment credentials

No credential is committed. Deployment must provide:

- PostgreSQL password secret;
- OIDC issuer, audience and JWKS URL (or a local-only HS256 secret);
- Redis connection details if the shared queue differs from Compose;
- separate bearer-token secret files for any enabled Partner Control, Tender
  Portal, myImperial or e-mail adapter.

`EXTERNAL_WRITES_ENABLED` defaults to `false`. Enabling it does not bypass the
R6-R7 policy gate.
