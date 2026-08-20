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
| Content publication | daily jobs from Content Factory | `autonomous-publishing-worker` → web first → readback → social → attribution | all mandatory content/claim/legal/visual/security/channel gates and release-token binding |

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
- Publishing is web-first. Social and attribution channels run only after canonical web readback.
  Partial failure invokes reverse-order rollback and creates an auditable exception.
- Facebook and Instagram variants require 3–8 hashtags. Forum output remains draft-only unless
  an official API and current platform-policy evidence are registered.
- LinkedIn publication uses the versioned Posts API only after canonical web readback. The route
  requires a managed OAuth token with proven `w_organization_social` scope, a non-expired token
  timestamp, an exact organization ID, and a pinned `YYYYMM` API version. A successful `201` is
  insufficient: the returned post URN is fetched with `viewContext=READER`, and author,
  commentary, public lifecycle state and main-feed distribution must match before verification.
  The create request is attempted once; ambiguous POST outcomes are never retried automatically.
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
  <brand>-linkedin.json

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

LinkedIn secrets contain an OAuth `access_token`, its `granted_scopes` metadata and `expires_at`.
Never store or use a member's primary password. `w_organization_social` is a restricted product
permission and the authenticated member must hold an eligible Page role. Page IDs and public
slugs are non-secret and are maintained in `config/publishing/linkedin-organizations.json`.

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
7. Canary one synthetic, owned recipient per brand and one staging publication per channel.
   Verify the public result/readback, delivery receipt, audit event, suppression and rollback.
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
- LinkedIn developer-app Community Management access, a managed OAuth token with
  `w_organization_social`, and a current token-expiry record for every enabled Page. Registration
  of a Page and browser admin access alone do not grant API publication capability.
- Legal approval of the contact-basis policy and retention schedule.
- Exact current migration head after concurrent Platform Core work is committed.

Until every relevant gate passes, `GROWTH_OPS_ENABLED=false` and
`AUTONOMOUS_PUBLISHING_ENABLED=false` are the only release-approved settings.
