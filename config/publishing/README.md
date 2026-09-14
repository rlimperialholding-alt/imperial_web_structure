# Autonomous publishing runtime registry

This directory contains only non-secret brand/channel routing. Runtime credentials live in the server-managed directory mounted at `/run/secrets/publishing` with mode `0600` per file.

Production writes are fail-closed. The kill-switch reference must contain `ALLOW_APPROVED_CANARY` or `ALLOW_APPROVED_WRITES`; staging accepts only `ALLOW_STAGING_WRITES`. A runtime emergency stop is created at `/app/runtime/publishing-kill-switch` after a rollback failure.

NIM routes are enabled only after the real API contract, HMAC header names, exact field map, readback map, endpoints, and secret reference are registered. WordPress requires an application password, never a shared account password. Forum remains `draft_only` unless dated policy evidence and an official API are separately configured.

LinkedIn routes use the official `https://api.linkedin.com/rest/posts` endpoint and are disabled
until a managed OAuth token, its non-expired expiry timestamp, and the granted
`w_organization_social` scope are all recorded. A personal LinkedIn password is never a runtime
credential. Each enabled brand binding must pin `organization_id`, a six-digit `api_version`,
`base_url: https://api.linkedin.com/`, `allowed_hosts: ["api.linkedin.com"]`, and a mode-`0600`
`secret_ref`. The non-secret, registration-verified Page mapping is stored in
`linkedin-organizations.json`.

Minimal managed secret shape (placeholder values only):

```json
{
  "access_token": "<managed-oauth-token>",
  "granted_scopes": ["w_organization_social"],
  "expires_at": "2026-12-31T23:59:59Z"
}
```
