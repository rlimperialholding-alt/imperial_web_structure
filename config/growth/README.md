# Growth operations registry

`registry.template.json` is intentionally non-runnable. It documents the exact enabled public-land
aggregate binding, but its placeholder brands and senders must never replace the active Hetzner
registry. Use `scripts/ensure_public_land_registry_binding.py` against the existing production
`registry.json`; the command is a dry run unless `--apply` is supplied, and an apply creates a
verified backup plus atomic read-back. Store each credential JSON below
`/opt/imperial-intelligence/secrets/growth` with mode `0600`. Never commit the resulting registry,
backup, or secret files.

The long-running `platform-core` and `growth-ops-worker` mounts stay read-only. Run the updater
from a one-off release-image container with only the growth registry directory temporarily mounted
read-write; first omit `--apply`, verify the reported hashes/action, then repeat with `--apply`:

```text
python scripts/ensure_public_land_registry_binding.py
python scripts/ensure_public_land_registry_binding.py --apply
```

The JSON result contains no registry or credential content. A successful apply reports the sibling
backup path, its SHA-256, the new file SHA-256, and the exact route-set SHA-256.

Production remains fail-closed until all of the following are true:

- the five brand senders match verified `tm_sending_domains` rows with SPF, DKIM and DMARC
  status `pass`;
- every enabled scheduled JSON/RSS or official-company source uses HTTPS and has
  non-expired policy evidence; the public-land aggregate instead requires its exact
  digest-bound 7/7 route readback and fresh per-request HTTPS/robots evidence;
- `GROWTH_OPS_BASE_URL` is the public HTTPS control-center URL;
- the production kill-switch file contains exactly `ALLOW_APPROVED_WRITES`;
- `/api/internal/growth-ops/readiness` returns HTTP 200.

The construction and distress motors run hourly. IVS runs once per Europe/Budapest calendar
day after 08:00. The construction target is at least 300 reviewed raw signals per UTC day; this
is an evidence metric, never an instruction to manufacture leads or bypass contact safeguards.

The public land HTML pipeline has one exact managed source binding:
`construction_public_land_html`, with `kind=public_land_listing_html`,
`fetch_mode=ingest_only`, motor `construction`, bucket `property_development`, and route-set
SHA-256 `f8f86c9a28160e1f2d919bf5f86bde7d6765bcea30945b17bba9a4364f478a1f`. It is excluded
from scheduled JSON/RSS fetches. The template contains this enabled binding but remains
non-runnable as a whole. This aggregate binding intentionally has no single URL or policy-evidence
URL: the exact digest-bound 7/7 route
readback plus fresh per-request HTTPS/robots checks are authoritative, and readiness fails closed
for any route/config/digest mismatch.

`official_company_html` is an ingest-only source kind for exact, individually enumerated
Hungarian architect-office bindings. It is never returned to the scheduled JSON/RSS fetcher.
Each enabled binding must match the mounted OWNER_APPROVED/CANONICAL real-estate source
registry bytes, exact official HTTPS context/contact URLs, public role address, verified public
organization names, fresh evidence and its deterministic binding hash. The kind is deliberately
restricted to `architect_office`; expanding it to referral partners or other recipient classes
requires a separately authorized schema change and source artifact.

## Canonical wide daily layer (2026-08-20)

The server-managed `source-ledger-manifest.json` binds the imported database revision to
Google Sheet `1ddn6e2EbuafPc_S9_eb6oetBQsp4iOO9cFuMD6sQ4H4`, sheet ID `959591161`, with
25,494 routes. The Sheet is a version source only: normal daily operation reads the Hetzner
database and requires neither Google authentication nor a workspace administrator.
The daily layer is fail-closed and reports `partial` unless all of these gates are evidenced:

- at least 800 actual route attempts;
- at least 100 new unique, source-backed leads/early signals after dedupe;
- at least 80 unique question-radar topics mapped to a brand and use case;
- one release-passed content item for each of all 19 active brands.

`BLOCKED`, `PARTIAL`, login, paywall, CAPTCHA, 403 and 429 are never counted as `NO_MATCH`.
The ETDR/OENY branch keeps both new/changed-record monitoring and the two reactivation states
`ETDR_START_NOT_VERIFIED` and `ETDR_COMPLETION_NOT_VERIFIED`.

IORA remains `internal_executive_review_only`: its complete daily package is routed only to
Právicz Anna (`ugyvezeto@imperialholding.hu`). IORA never queues or sends external outreach.
Internal handoff remains mandatory even when an independently tested publication succeeds.

Every partner-facing email body contains the owner-locked sentence:

> Szeretnénk felajánlani szakmai segítségünket és kapacitásunkat a projekthez, ha szükség van ránk.

The exact final email artifact must be inspected and HMAC-released before dispatch. The
Homes4you, HWS Home and Horizont Global no-monitoring gate remains ACTIVE / FAIL_CLOSED at
query, fetch, storage, prompt, handoff, publication and outreach boundaries.

Land-listing-agent outreach has an additional owner-mandated hard gate. Turczer József, every
GDN Ingatlanhálózat office and agent, and every Otthon Centrum II./II/A. or XII. district office
and agent are blocked before ingestion, queueing, release and SMTP dispatch. Listing-agent
records without verified organization affiliation are blocked; Otthon Centrum records also
require a verified office affiliation. Scoring, manual release and legacy queue state cannot
override these exclusions.
