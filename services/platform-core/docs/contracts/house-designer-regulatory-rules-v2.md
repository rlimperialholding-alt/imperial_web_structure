# House Designer regulatory rules v2 contract

Status: internal contract; production legal content is not approved by this document.

The `regulatory-rules-v2` schema extends the legacy `maxStoreys`,
`maxGrossAreaM2`, and `allowedRoofTypes` fields with a bounded declarative rule
list. It is deterministic, side-effect free, and does not execute expressions or
arbitrary JSON paths.

## Envelope

```json
{
  "schemaVersion": "regulatory-rules-v2",
  "checks": []
}
```

`checks` contains 1–500 items. Codes are unique in a merged ruleset. An
interpretation is bound to one immutable source snapshot; the service writes and
verifies each check's `sourceRef`. Conflicting checks with the same code fail
closed while rulesets are assembled or reviewed.

## Check

```json
{
  "code": "MAX_BUILDING_HEIGHT",
  "category": "height_storeys",
  "fact": "building.height_m",
  "operator": "lte",
  "expected": "7.5",
  "severity": "BLOCKER",
  "sourceRef": "SRC-...",
  "ruleRef": "12. § (3)",
  "explanation": "Az épület magassága meghaladja a megengedett értéket.",
  "remediation": "Csökkentse az épület teljes magasságát.",
  "geometryPath": "levels"
}
```

Required categories mirror the frozen HD-001 minimum groups:

- `zoning_use`
- `parcel_building_mode`
- `site_coverage`
- `green_area`
- `floor_area_ratio`
- `setbacks_buildable_area`
- `height_storeys`
- `roof_townscape`
- `parking_access_utilities`
- `room_environment`
- `circulation_stairs`
- `accessibility`
- `protection_special`
- `fire_energy_handoff`

Each category has an explicit fact allowlist. A check cannot claim category
coverage by relabelling an unrelated fact. Production coverage counts only
mandatory `BLOCKER` or `ERROR` checks, not informational or warning-only rows.

A production activation manifest accepts a ruleset only when every category is
represented by at least one valid v2 check and the source/interpretation binding
is current and approved. Legacy rulesets remain reproducible but cannot satisfy
this production coverage gate.

## Facts and operators

Numeric facts use `lte`, `gte`, or `eq`:

- `building.storeys`, `building.footprint_area_m2`,
  `building.gross_area_m2`, `building.height_m`
- `building.site_coverage_percent`, `building.floor_area_ratio`
- `rooms.count`, `rooms.min_area_m2`, `rooms.min_height_m`
- `roof.min_pitch_deg`, `roof.max_pitch_deg`
- `site.green_area_percent`, `site.front_setback_m`,
  `site.side_setback_m`, `site.rear_setback_m`, `site.parking_spaces`

String facts use `eq` or `in`: `site.zoning_code`,
`site.building_mode`.

Collection facts use `subset`, `contains`, or `contains_any`:
`roof.types`, `site.allowed_uses`.

Boolean facts use `eq`: `site.access_verified`,
`site.utilities_verified`, `site.protection_clear`,
`building.stair_data_complete`, `building.accessibility_data_complete`,
`handoff.fire_data_complete`, and `handoff.energy_data_complete`.

Geometry facts are computed by the server. Site regulatory facts are read only
from the trusted `verifiedFacts` payload produced by an approved source adapter;
customer draft fields are not regulatory evidence. When a fact is unavailable,
the check returns `UNKNOWN`, never PASS. A mandatory (`BLOCKER` or `ERROR`)
UNKNOWN keeps the whole run UNKNOWN; a mandatory failure makes it FAIL.

Every declarative check is persisted as a finding, including PASS, so the UI and
audit can show rule-by-rule evidence. PASS findings do not increase blocker,
error, or warning counts.

## Governance boundary

The regulatory admin UI accepts v2 checks and test vectors, but the existing
source capture, security review, four-eyes interpretation approval, ruleset
approval, effective-date selection, revoke, supersede, and concurrent binding
checks remain mandatory. This contract supplies execution mechanics only. It
does not assert that any TÉKA, OTÉK, HÉSZ, TKR, or TAK content is legally correct,
licensed, current, or professionally approved.
