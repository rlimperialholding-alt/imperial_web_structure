# Autonomous growth and publishing — as-built and release runbook

Status date: 2026-08-16. This document separates implemented capability from external
production gates. A disabled adapter, missing credential, missing policy proof, stale worker,
failed sender verification or absent kill-switch approval must never be reported as live.

## Required engines

| Engine | Schedule | Implemented execution route | Mandatory evidence |
|---|---:|---|---|
| Construction acquisition | hourly | `growth-ops-worker` → managed HTTPS sources → `growth_signals` → outreach outbox | all six source buckets; attempted/succeeded/raw/schema-rejected/accepted/queued counts; at least 300 raw signals reviewed daily |
| ExitFlow–Veritas–BauShield | hourly | same worker and outbox, canonical signal-to-brand routing | liquidation, bankruptcy, enforcement, officer/seat change and construction-dispute baskets |
| IVS target engine | daily after 08:00 Europe/Budapest | same scheduler; existing engine is represented as a managed source | source contract and current policy evidence |
| Content publication | daily jobs from Content Factory | `growth-ops-worker` → independent available web/Facebook routes → per-channel readback | all mandatory content/claim/legal/visual/security/channel gates and release-token binding |

The 50 Hungarian opportunities figure is a goal, not a quota. EKR/TED procurement notices
must not be converted into leads merely to meet it. Source connectors count raw records before
schema rejection so the 300-record review evidence cannot be inflated by counting only accepted
leads.

## Safety and compliance controls

- Natural persons and named/unknown mailboxes cannot receive cold outreach. They require a
  recorded explicit request or documented consent. Public-business contact is accepted only for
  an organisation plus a role mailbox and a stored public contact URL.
- The Hungarian Advertising Act's current section 6 requires prior clear and explicit consent
  for direct advertising to a natural person. The implementation is deliberately stricter at the
  mailbox-classification boundary. Source: https://njt.hu/jogszabaly/2008-48-00-00
- A global suppression table is checked at queue and send time. Bounce, complaint and
  unsubscribe events suppress further mail. The public unsubscribe token is stored only as a
  SHA-256 hash.
- A sequence contains one initial message and no more than two multi-day follow-ups. Brand/day
  rate limits and brand/recipient cooldowns are enforced before the initial message.
- Sender identity is exact: brand registry, SMTP envelope and the verified sending-domain row
  must agree. SPF, DKIM and DMARC must all be `pass` before queueing or sending.
- SMTP transport must use TLS. A delivery-stage failure is treated as ambiguous and dead-lettered
  instead of retried, preventing an acceptance-timeout from causing duplicate mail.
- Every external source is registry-bound to a motor and basket, HTTPS-only, host-allowlisted,
  response-size-limited and backed by non-expired policy evidence.
- Content Factory evaluates web and Facebook independently. A missing route is recorded as
  skipped and never blocks an available route; every queued channel still requires its own
  successful public readback. A failed channel creates an auditable exception for that channel.
- Facebook and Instagram variants require 3–8 hashtags. Forum output remains draft-only unless
  an official API and current platform-policy evidence are registered.
- WordPress uses a per-integration Application Password over HTTPS rather than a user's primary
  password. Official reference: https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/
- Two independent controls are required for writes: feature enablement plus the host-only
  kill-switch file. Production accepts `ALLOW_APPROVED_CANARY` or `ALLOW_APPROVED_WRITES`.

These controls implement conservative operational safeguards; legal counsel remains responsible
for approving the final legitimate-interest/consent policy, privacy notice, retention schedule
and each production source.

## Secret layout

Secrets never belong in Git, Drive exports, logs or API responses.

```text
/opt/imperial-intelligence/secrets/publishing/
  kill-switch
  <brand>-wordpress.json
  <brand>-meta.json

/opt/imperial-intelligence/secrets/growth/
  kill-switch
  exitflow-smtp.json
  veritas-smtp.json
  baushield-smtp.json
  bautica-smtp.json
  prefab-smtp.json
```

Every JSON file and kill-switch file must be owned by the deployment operator/service group and
have mode `0600`. Meta Ads reporting tokens do not satisfy Page/Instagram publishing
permissions. Record Page ID, Instagram business account ID, system-user token and the granted
publishing permissions only in the managed Meta secret.

## Release sequence

1. Rebase the release on the current canonical Platform Core migration head. Do not reuse a
   revision number or deploy a branch based on an older head.
2. Run Python compilation, patch checks, targeted publishing and growth tests, a fresh-database
   Alembic upgrade, and the exact full Platform Core suite.
3. On Hetzner, record the active image ID/source commit, then create a PostgreSQL custom-format
   backup under `/opt/imperial-intelligence/backups`. Verify its SHA-256 and run `pg_restore -l`.
4. Build one immutable image tag from the exact tested commit. Apply migrations before starting
   either new worker. Core and every Platform Core worker must use that exact image ID.
5. Keep both features disabled. Recreate Platform Core, outbox worker, publishing worker,
   growth worker and then the gateway. Verify internal and public health plus recent logs.
6. Install the server-managed registries and mode-0600 secrets. Register matching verified
   sending-domain rows. Check the internal readiness endpoints.
7. Canary one synthetic, owned recipient per brand and one staging publication for each actually
   available route. Verify the public result/readback, image, delivery receipt, audit event,
   suppression and rollback. Record unavailable routes as skipped; do not invent a route.
8. Only after canary proof, change the relevant kill-switch to `ALLOW_APPROVED_WRITES` and enable
   the feature. Keep forum mode draft-only until its separate policy gate passes.

Rollback means: restore the previous pinned image for core and all workers, recreate the gateway,
and run a database downgrade only if it is proven safe and no new production rows must be
preserved. Otherwise leave the additive tables in place and disable both feature flags.

## Current external gates

- Exact sender addresses and SMTP credentials for ExitFlow, Veritas, BauShield, Bautica and
  Prefab, plus verified SPF/DKIM/DMARC evidence.
- Managed source URLs/contracts and current terms/policy evidence for every enabled basket,
  including the existing IVS engine.
- Production CMS registry for every brand and its WordPress/NIM credentials.
- Meta Page/Instagram publishing identities and permissions; existing Meta Ads read access is
  insufficient.
- Legal approval of the contact-basis policy and retention schedule.
- Exact current migration head after concurrent Platform Core work is committed.

Until every relevant gate passes, `GROWTH_OPS_ENABLED=false` and
`AUTONOMOUS_PUBLISHING_ENABLED=false` are the only release-approved settings.

## 2026-08-20 canonical-wide release delta

Revision `20260820_0073` adds a single, auditable daily run keyed to the 25,494-route Source
Coverage Ledger. It creates all 19 daily Content Factory obligations before work begins and
evaluates the 800 route / 100 lead / 80 question / 19 brand gates without manufacturing output.
Below a gate, the run is `partial`; a blocked source is never a negative finding.

The IORA path is permanently separated from the external outreach outbox. It produces an
internal executive-review package for Právicz Anna only. Publication and internal handoff are
parallel obligations: successful publication never suppresses the unchanged internal handoff.

Partner-email release is now bound to the SHA-256 of the exact inspected artifact and the
platform release HMAC. The owner-authored assistance/capacity sentence is verified again at
queue and dispatch time. SMTP/provider readiness, tested delivery/readback, suppression,
kill-switch and exact-artifact release must all pass; otherwise dispatch remains blocked.

DeepSeek is available only through a mode-0600 server secret, explicit monthly budget and
configurable input/output price rates. Every call stores model, purpose, token counts, estimated
cost and response hash. A zero budget or missing rate/key fails closed.
