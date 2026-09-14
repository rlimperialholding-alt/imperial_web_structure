# Market & Creative Intelligence service API v1

## Security contract

The API is disabled unless `MARKET_SERVICE_API_ENABLED=true`. Credentials are read from
`MARKET_SERVICE_TOKENS_FILE`; raw tokens are never stored. The file contains SHA-256 digests,
expiry, an immutable service subject, tenant, brand, market and explicit permissions.

```json
{
  "version": 1,
  "tokens": [
    {
      "tokenId": "mci-consumer-01",
      "tokenSha256": "<64 lowercase hexadecimal characters>",
      "subjectId": "service:approved-consumer",
      "tenantId": "imperial-holding",
      "brandId": "imperial",
      "marketId": "HU",
      "permissions": ["read", "handoff"],
      "expiresAt": "2026-12-31T23:00:00Z"
    }
  ]
}
```

Requests use `Authorization: Bearer <raw-token>`. Missing, unknown and expired credentials are
401; missing permission is 403; the kill switch is 503. Results are always SQL-filtered to the
scope embedded in the credential. Browser session and global Control Center API credentials do
not grant access to this surface.

## Endpoints

- `GET /api/v1/market-intelligence/source-targets`
- `GET /api/v1/market-intelligence/capture-jobs`
- `GET /api/v1/market-intelligence/observations`
- `GET /api/v1/market-intelligence/assets`
- `GET /api/v1/market-intelligence/voc-signals`
- `GET /api/v1/market-intelligence/pattern-clusters`
- `GET /api/v1/market-intelligence/hypotheses`
- `GET /api/v1/market-intelligence/research-packs`
- `POST /api/v1/market-intelligence/research-packs/{pack_id}/handoff`

The handoff write requires `handoff`, `Content-Type: application/json`, and an
`Idempotency-Key` between 8 and 255 characters. It reuses the same locked, latest-revision,
hash-checked, monotonic-watermark service operation as the internal UI. It cannot publish
content, send mail, change advertising budgets or mutate CRM stages.

A successful handoff returns `status: ACCEPTED`: the immutable handoff and its internal-only
outbox event have been committed atomically. This does not claim that a downstream consumer has
already processed the event.

Interactive schemas and examples are exposed by the deployed `/docs` and `/openapi.json`.
