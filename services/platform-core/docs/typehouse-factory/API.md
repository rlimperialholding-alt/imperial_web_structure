# API

Minden publikus végpont `X-API-Token` hitelesítést használ.

- `POST /v1/source-imports` – 1–1000 `source_urls` regisztrálása, `generator_concurrency: 1`.
- `GET /v1/source-imports/{import_id}` – sor- és itemállapot.
- `POST /v1/type-house-jobs` – pontosan egy `source_url`; kötelező `Idempotency-Key`.
- `GET /v1/type-house-jobs/{job_id}` – job, tények, artefaktumok és QA-k.
- `POST /v1/type-house-jobs/{job_id}/retry` – új revision csak javítható terminális állapotból.
- `GET /v1/type-house-jobs/{job_id}/package` – csak `COMPLETED` esetén.
- `POST /v1/catalog-streams/{id}/pause|resume` – katalógussor vezérlése.

A producer belső tokennel regisztrál artefaktumot és QA-futást a `/v1/internal/type-house-jobs/...` útvonalakon. Több forrás publikus job-payloadban `SINGLE_HOUSE_REQUIRED` hibát ad.
