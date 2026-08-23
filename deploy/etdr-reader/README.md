# ÉTDR–OÉNY authority reader staging

This deployment is deliberately isolated from every Imperial application network and volume.

## Release policy

- Bind the API only to `127.0.0.1`.
- Use an immutable image tag and verify its OCI revision label.
- Keep `AUTHORITY_READER_ENABLED=false` and
  `AUTHORITY_READER_POLICY_AUTHORIZED=false` until written bulk-reuse authorization exists.
- Enabling also requires a mounted, unexpired policy-evidence JSON with authorization reference,
  approver, a bulk-reuse scope, and `valid_until`; its SHA-256 is exposed in readiness evidence.
- Never bypass CAPTCHA, `403`, `429`, authentication, `robots.txt`, or a schema-drift block.
- The OÉNY queue and Growth Signal outbox remain `held`; no automatic outreach is generated.
- Deploy under a host-level `flock`, after a verified PostgreSQL dump and release manifest.

## Health and internal API

- `GET /health/live`
- `GET /health/ready`
- `GET /` — aggregate, non-sensitive dashboard
- Internal endpoints use `X-Internal-Job-Token`.

The database migration is a separate one-shot Compose service. The API and worker never run an
implicit migration on startup.
