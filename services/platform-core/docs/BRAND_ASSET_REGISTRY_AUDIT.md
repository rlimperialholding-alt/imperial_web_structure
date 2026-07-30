# Brand asset registry audit

Audit date: 2026-07-26

## Scope

The registry contains unmodified logo assets observed on the seven requested
live brand websites. Every registered file has a source URL, SHA-256 digest,
media type, dimensions, role, and approval status. The files are served below
`/static/brand-assets/` and resolved through the fail-closed Copy Gate brand
asset resolver.

Observed website assets are permitted for `TEST_ONLY` generation. External
publication remains blocked until the corresponding brand record has
`approval_status=approved`.

## Results

| BrandID | Website | Registered variants | Live-source issues |
|---|---|---|---|
| `imperial` | `imperialholding.hu` | primary PNG, monochrome SVG mark | referenced WebP returns 404 |
| `danish-fabrik` | `danishfabrik.hu` | primary PNG, site-icon SVG | referenced Safari pinned-tab SVG returns 404 |
| `bautica` | `bautica.hu` | primary WebP, inverse header PNG, monochrome SVG mark | none in the selected set |
| `prefab` | `prefab.hu` | primary PNG, site-icon SVG | referenced Safari pinned-tab SVG returns 404 |
| `casa-moderna` | `casa-moderna.hu` | primary vector SVG | referenced WebP and favicon SVG return 404 |
| `baufreund` | `baufreund.hu` | primary PNG, separate mascot PNG, site-icon SVG | referenced WebP returns 404 |
| `timberhaus` | `timberhaus.hu` | primary PNG, site-icon SVG | referenced Safari pinned-tab SVG returns 404 |

## Safety controls

- No screenshot crop, OCR reconstruction, or generated logo is registered.
- Partner, certification, and editorial logos discovered on the pages were
  excluded.
- Every local file is checked against its manifest SHA-256 before use.
- Missing, altered, unknown, path-traversing, or unapproved publication assets
  fail closed.
- The Casa Moderna vector contains no script, foreign object, or external
  resource reference.
- Site-icon SVG wrappers are retained as original website assets and are not
  treated as replacement primary wordmarks.

## Approval still required

The seven brands currently have
`approval_status=observed_pending_owner_approval`. A brand owner must confirm
the accepted variants and permitted contexts before publication is enabled.
