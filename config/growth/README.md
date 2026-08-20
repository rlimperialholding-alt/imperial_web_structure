# Growth operations registry

`registry.template.json` is intentionally non-runnable. Copy it to `registry.json` only on the
Hetzner deployment host, replace every placeholder, add current source-policy evidence, and
store each SMTP credential JSON below `/opt/imperial-intelligence/secrets/growth` with mode
`0600`. Never commit the resulting registry or secret files.

Production remains fail-closed until all of the following are true:

- the five brand senders match verified `tm_sending_domains` rows with SPF, DKIM and DMARC
  status `pass`;
- every enabled signal source uses HTTPS and has non-expired policy evidence;
- `GROWTH_OPS_BASE_URL` is the public HTTPS control-center URL;
- the kill-switch file contains `ALLOW_APPROVED_CANARY` for canary or
  `ALLOW_APPROVED_WRITES` for normal production operation;
- `/api/internal/growth-ops/readiness` returns HTTP 200.

The construction and distress motors run hourly. IVS runs once per Europe/Budapest calendar
day after 08:00. The construction target is at least 300 reviewed raw signals per UTC day; this
is an evidence metric, never an instruction to manufacture leads or bypass contact safeguards.

## Canonical wide daily layer (2026-08-20)

The server-managed `source-ledger-manifest.json` binds runtime state to Google Sheet
`1ddn6e2EbuafPc_S9_eb6oetBQsp4iOO9cFuMD6sQ4H4`, sheet ID `959591161`, with 25,494 routes.
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
