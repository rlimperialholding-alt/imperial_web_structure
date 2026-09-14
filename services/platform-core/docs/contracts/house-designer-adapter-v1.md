# House Designer production adapter contract v1

This contract is used independently by the `pricing`, `capacity`, and `render` adapters.
An adapter revision becomes usable only after a different managing-director or owner approves
the technical author's registration. Secrets are loaded from runtime secret files and are never
stored in the database.

## Request binding

Every queued job stores canonical JSON (UTF-8, sorted keys, compact separators) and its SHA-256.
The request contains the immutable design revision, canonical design hash, geometry,
configuration, site data, and a shared `inputSha256`. Pricing and capacity results for the same
design therefore have the same input binding. Render requests also contain `geometryLockSha256`.

The background worker sends a second canonical envelope to the approved HTTPS endpoint. It
contains the request, job and request hashes, issue time, and the configured HTTPS callback URL.
The same adapter-specific key signs this outbound envelope. Redirects, credential-bearing URLs,
and DNS results that are not globally routable are rejected. A provider acknowledges only with
HTTP 202 and a non-empty `providerJobId`; until then the job is not marked dispatched. Temporary
failure uses bounded exponential retry and never creates a result snapshot.

## Signed result envelope

Providers submit canonical JSON to `POST /api/v1/house-designer/adapter-results` with headers:

- `Content-Type: application/json`
- `X-Imperial-Key-Id: <registered key id>`
- `X-Imperial-Signature: sha256=<HMAC-SHA256 of canonical body>`

Required envelope fields are `contractVersion`, `adapterType`, `jobId`, `requestSha256`,
`issuedAt`, `providerJobId`, `status`, and `result`. The contract version is
`house-designer-adapter-v1`; accepted responses use `status=SUCCEEDED`. Responses older than five
minutes, expired jobs, non-active adapters, wrong key IDs, and any request/input/geometry mismatch
fail closed. The callback `providerJobId` must match the earlier HTTP 202 acknowledgement, and a
callback for a job that was never dispatched is rejected.

Pricing results require positive `netMinHuf`, `netMaxHuf`, a VAT rate between 0 and 1,
`lineItems`, `assumptions`, `exclusions`, `inputSha256`, and a future `validUntil`. Gross values are
derived inside Imperial Intelligence rather than trusted from the provider.

Capacity results require a valid start window, positive ordered duration bounds, `phases`,
`assumptions`, `inputSha256`, and future `validUntil`.

Render results require an HTTPS or S3 `assetRef`, 64-character `assetSha256`, exact
`geometryLockSha256`, `inputSha256`, and a QA object.

Authenticated but invalid responses are retained as immutable `REJECTED` receipts. Invalid HMAC
traffic is not persisted. Exact successful replay is idempotent; a reused provider job ID with
different content is rejected.
