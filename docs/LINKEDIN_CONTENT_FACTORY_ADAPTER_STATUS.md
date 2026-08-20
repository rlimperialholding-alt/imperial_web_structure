# LinkedIn Content Factory adapter — as-built status

Status date: 2026-08-20

## Implemented capability

- `linkedin` is a first-class autonomous publishing channel in the job schema, registry,
  execution order and adapter factory.
- LinkedIn runs only after the canonical WordPress/NIM publication has a verified public
  readback. The verified canonical URL is appended to the approved LinkedIn commentary when it
  is not already present.
- The adapter uses `POST https://api.linkedin.com/rest/posts` with a pinned `Linkedin-Version`,
  `X-Restli-Protocol-Version: 2.0.0`, an organization author URN, public visibility and main-feed
  distribution.
- The create operation has one network attempt. It is not automatically retried after a timeout
  or other ambiguous outcome.
- A `201` response is not enough. The adapter requires a valid `x-restli-id` Post URN, fetches it
  with `viewContext=READER`, and verifies organization author, exact commentary, `PUBLISHED`
  lifecycle, `PUBLIC` visibility and `MAIN_FEED` distribution.
- Reverse rollback uses the idempotent Posts API delete and accepts success only when the
  subsequent readback returns `404`.
- Text posts are supported. An already registered LinkedIn image, video or document URN may be
  attached. Uploading raw media is deliberately not inferred or attempted by this change.

## Fail-closed registry requirements

An enabled brand route requires all of the following:

- exact positive numeric `organization_id`;
- `base_url` hosted only at `api.linkedin.com`;
- pinned six-digit `api_version` in `YYYYMM` form;
- optional lowercase kebab-case public slug;
- managed mode-`0600` JSON secret;
- non-empty OAuth `access_token`;
- `granted_scopes` containing `w_organization_social`;
- parseable, future `expires_at` timestamp;
- global publishing feature enabled and environment kill-switch unlocked.

A member password is neither accepted nor used by the adapter.

## Organization mapping

The non-secret mapping for all 12 registration-verified Pages is in
`config/publishing/linkedin-organizations.json`. It contains display names, organization IDs,
organization URNs, public slugs/URLs and registration state. It contains no token, password,
release token or HMAC.

## Current staging gate

The staging inspection on 2026-08-20 found:

- active image before this change: `imperial-platform-core:autonomous-growth-b1cea59`;
- `AUTONOMOUS_PUBLISHING_ENABLED=false`;
- no LinkedIn secret file in the managed publishing secret directory;
- only the existing mode-`0600` publishing kill-switch file;
- no LinkedIn channel binding enabled in the server registry.

Therefore staging cannot publish to LinkedIn until the external gates below are completed. This
is the intended state.

## External gates that code cannot supply

1. An organization-owned LinkedIn developer application with approved Community Management API
   access.
2. OAuth authorization for `w_organization_social`.
3. An authenticated member with an eligible role on each target Page.
4. A managed token file with recorded granted scope and current expiry for each enabled binding.
5. A separately approved staging canary job and its full content/release gate evidence before the
   feature flag or kill-switch is opened.

Official references:

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-access-control-by-role

Until the external gates are proven, LinkedIn channel entries must remain `enabled: false` and
`AUTONOMOUS_PUBLISHING_ENABLED=false` remains release-approved.
