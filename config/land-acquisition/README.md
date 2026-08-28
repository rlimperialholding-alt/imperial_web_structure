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
verified real-estate-office role mailbox; a natural-person agent or owner requires an explicit
request or documented prior consent before any message is queued or dispatched.

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
