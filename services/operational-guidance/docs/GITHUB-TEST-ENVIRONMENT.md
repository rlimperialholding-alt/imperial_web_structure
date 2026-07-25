# Imperial Intelligence – GitHub test environment

## Architecture

- **Integration Hub**: the existing Python/FastAPI control plane.
- **ITEP Core**: internal Node/TypeScript task enforcement service.
- **Hub PostgreSQL + Redis**: isolated synthetic test state.
- **ITEP PostgreSQL**: isolated task, evidence, connector and audit state.
- **Mock External**: Billingo and bank-compatible synthetic endpoints.
- **Imperial Sales CRM**: the only live external system; read-only access.

The CRM is intentionally not mocked. The workflow fails before the stack starts
when the real CRM URL, token or workspace identifier is missing.

## Required GitHub environment

Create a protected GitHub environment named `imperial-test`.

Secrets:

- `CRM_API_BASE_URL`
- `CRM_ACCESS_TOKEN` — read-only token
- `CRM_WORKSPACE_ID`
- `ITEP_IDENTITY_SHARED_SECRET` — at least 32 random characters

Optional environment variables:

- `CRM_ACTIVITIES_PATH`
- `CRM_AUTH_HEADER`
- `CRM_AUTH_SCHEME`
- `CRM_WORKSPACE_QUERY_PARAMETER`

## Workflow behavior

`Quality` runs the Python and TypeScript unit/static checks without live data.

`Live CRM Integration Test`:

1. validates required secrets;
2. performs a read-only contract request against the real CRM;
3. starts the integrated Docker stack;
4. migrates and seeds both databases;
5. creates only the `crm-live` connector account;
6. triggers one real CRM read sync;
7. verifies ITEP and Integration Control Room through the Hub;
8. uploads logs and diagnostics;
9. destroys all test databases and volumes.

Before the workflow exists on the default branch, add the `run-live-crm` label
to the pull request to trigger the protected pre-merge run. Removing and
re-adding the label starts a new run after secret or adapter changes.

## Safety

- no production database is mounted;
- no write request is sent to CRM;
- CRM token must be read-only;
- all non-CRM business data is synthetic;
- all test volumes are deleted after each run;
- secrets are never committed or printed.
