# ÉTDR–OÉNY authority reader staging

The reader database, API and worker remain isolated from Imperial application networks and
volumes. A separate bridge container joins the platform database network solely to execute one
audited database function through a dedicated role with no direct table privileges.

## Release policy

- Bind the API only to `127.0.0.1`.
- Use an immutable image tag and verify its OCI revision label.
- Keep `AUTHORITY_READER_ENABLED=false` and
  `AUTHORITY_READER_POLICY_AUTHORIZED=false` until written bulk-reuse authorization exists.
- Schedule, detail reads and lead export each require a separate explicit `true`; all four runtime
  switches default to closed independently.
- Enabling also requires a mounted, unexpired policy-evidence JSON with authorization reference,
  approver, a bulk-reuse scope, and `valid_until`; its SHA-256 is exposed in readiness evidence.
- Never bypass CAPTCHA, `403`, `429`, authentication, `robots.txt`, or a schema-drift block.
- The OÉNY queue and lead outbox remain `held` until all source-policy gates pass; exported leads
  are still `blocked` for internal review and can never create automatic outreach.
- The detail reader stores the public procedure subject, status, authority, decisions and document
  links, but never downloads the linked files automatically.
- The lead bridge writes project-only, `blocked` and `internal_review_only` signals through a
  dedicated least-privilege PostgreSQL role. It has no delete permission and cannot create
  outreach records.
- The platform-side extension has its own `20260824_0003` schema ledger and immutable delivery
  ledger. Its `SECURITY DEFINER` owner is a separate `NOLOGIN` role; runtime startup verifies the
  owner, function hash, fixed search path, ACLs and role attributes before processing anything.
- Deploy under a host-level `flock`, after a verified PostgreSQL dump and release manifest.

## Health and internal API

- `GET /health/live`
- `GET /health/ready`
- `GET /` — aggregate, non-sensitive dashboard
- `POST /api/internal/authority-reader/details/run`
- `GET /api/internal/authority-reader/lead-feed`
- Internal endpoints use `X-Internal-Job-Token`.

The database migration is a separate one-shot Compose service. The API and worker never run an
implicit migration on startup.

`platform-bridge-rollback.sql` disables the bridge but intentionally retains its version and
delivery ledgers. The global `project` constraint is narrowed again only when no project rows
exist, so rollback never destroys or invalidates audit evidence.
