# LinkedIn Content Factory — staging verification evidence

Verification date: 2026-08-20 (Europe/Budapest)

## Deployed artifact

- Image tag: `imperial-platform-core:linkedin-cf-20260820-988878a6ec85`
- Image ID: `sha256:3662139d2dd244af9344cecdfea69edc54e3fb6a1c568b8a5692a086e7a0a336`
- Base source commit: `b1cea593a3229eef828e3618af041b3cd37825fb`
- Bundle SHA-256 label:
  `988878a6ec850209e17fd57867b724e111339c9ec4716f583f55663c751c633f`
- Image label: `hu.imperial.linkedin-writes-enabled=false`
- Pre-deployment backup:
  `/opt/imperial-intelligence/backups/linkedin-cf-pre-20260820-988878a6ec85`

The Platform Core, outbox worker, autonomous publishing worker, growth worker and typehouse
worker all run the exact same image ID.

## Test evidence

- Python compilation: passed.
- JSON validation for registry and 12-Page mapping: passed.
- Ruff formatting and lint for changed modules/tests: passed.
- Mypy for the autonomous publishing package: passed, 8 source files checked.
- Targeted local suite: 61 passed.
- Full local Platform Core suite: 639 passed, 5 pre-existing library warnings.
- Isolated server test-image suite: 61 passed, 2 non-failing cache/deprecation warnings.
- Runtime image import smoke: passed.

## Live staging checks

- `GET http://127.0.0.1:8091/health/ready`: HTTP success.
- Platform Core container: running and healthy.
- Four workers: running.
- Error-pattern count since deployment: 0 for core and every recreated worker.
- Live image hashes for `adapters.py`, `registry.py`, `schemas.py` and `service.py` match the
  deployment manifest.
- `linkedin` is present in supported and social execution channels.
- The live mapping contains exactly 12 LinkedIn organizations.
- The live FESZEK staging LinkedIn binding is `enabled: false`.
- `AUTONOMOUS_PUBLISHING_ENABLED=false`.
- Runtime publishing kill-switch result: `writes_unlocked=false`.
- No LinkedIn credential file exists in the managed publishing secret directory.

No LinkedIn API write or browser publication was attempted during verification.

## Remaining external gates

LinkedIn publication remains correctly blocked until Community Management API access, an OAuth
token with `w_organization_social`, token-expiry metadata and eligible Page role evidence are
provided. The current staging registry also reports the pre-existing missing
`feszek-staging-wordpress.json` secret; this prevents an end-to-end web-first staging canary and
is not supplied or fabricated by this deployment.

Consequently, the software and staging image are ready, but live Content Factory publication is
not enabled. Enabling requires both the relevant canonical web route credential and the LinkedIn
external authorization evidence, followed by a separately approved canary.
