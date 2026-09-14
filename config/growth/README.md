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
