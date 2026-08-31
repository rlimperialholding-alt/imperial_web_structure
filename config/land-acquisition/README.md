# Land acquisition portal registry

The registry is deliberately fail-closed. Named property portals may be read from public
HTML only when the portal is explicitly configured with `discovery_mode=public_html` and
`respect_robots_txt=true`. The worker fetches and enforces `robots.txt`, uses an identified
Imperial user agent, does not log in, and treats CAPTCHA, access-denied, 403 and 429 pages as
blocked evidence rather than trying to bypass them. Publishing and withdrawal still require
a licensed API adapter with an immutable receipt and read-back proof.

Every live public-HTML source requires:

1. at least one enabled HTTPS source-catalog route on the configured portal domain;
2. a robots-allowed path at execution time;
3. source evidence and daily deduplication;
4. no login, CAPTCHA, paywall or technical-control bypass;
5. data minimisation and the Growth Ops recipient/contact-basis gates.

Public listing HTML is discovery evidence, not consent. Automated first contact may use a
verified, explicitly named listing agent or property owner only through the locked one-time
public-listing policy. Every accepted recipient field is persisted with its exact public source
snippet, listing snapshot SHA-256 and fetch time. Immediately before dispatch the worker fetches
the same concrete permalink again with the same HTTPS, robots.txt, identified-user-agent,
response-size and blocked-page controls. A missing, changed, inactive or unverifiable listing is
a hard NO_SEND.

An explicitly dated first-production canary may temporarily reserve one to three accepted land
emails (`LAND_OUTREACH_PRODUCTION_CANARY_MAX_TOTAL`, allowed range 1..3). It is a release gate,
not an ongoing transport quota, and is inactive when no canary date is configured. Normal account
transport has no hourly, calendar-day or recipient-domain count cap: the sole account count ceiling
is 2,000 Gmail SENT messages in the rolling 24-hour window. Recipient cooldown, suppression,
deduplication, consent/contact-basis and content-verification gates remain independent safeguards.

The seven registered category routes can be checked without writes, then idempotently upserted
with database readback:

```bash
python scripts/ensure_public_land_routes.py
python scripts/ensure_public_land_routes.py --apply
```

Every live publishing adapter activation requires, outside this repository:

1. written commercial/API authority from the platform;
2. a Data Protection Impact Assessment and approved contact-basis policy;
3. adapter credentials in managed secrets, never in this JSON file;
4. staging contract tests for publish, read-back, idempotency and withdrawal;
5. explicit registry change reviewed by Legal and Operations.

The default registry enables robots-aware public-HTML discovery for the named property
portals, but it becomes production-ready only when matching source-catalog routes exist.
All external publishing remains disabled. `imperial_plot_finder` is also disabled until
its canonical CMS contract and rollback/read-back endpoint are registered.
