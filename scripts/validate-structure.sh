#!/usr/bin/env sh
set -eu

required_sites="
imperial
danish-fabrik
bautica
prefab
casa-moderna
family-homes
everyday-homes
property-360
budapesti-magasepito-vallalat
baufreund
red-property
timberhaus
"

for site in $required_sites; do
  index_file="sites/$site/index.html"

  if [ ! -f "$index_file" ]; then
    echo "Missing required site entry point: $index_file" >&2
    exit 1
  fi

  if ! grep -q 'name="robots" content="noindex,nofollow"' "$index_file"; then
    echo "Missing noindex directive: $index_file" >&2
    exit 1
  fi
done

required_files="
.env.example
docker-compose.yml
docker/nginx/nginx.conf
docker/nginx/conf.d/staging.conf
sites/_portal/index.html
sites/_portal/data/brands.json
sites/_shared/assets/tokens.css
sites/_shared/assets/components.css
sites/_shared/assets/admin.css
sites/_shared/assets/admin.js
sites/_shared/assets/imperial.css
sites/_shared/assets/imperial.js
sites/_shared/assets/data/imperial-home.json
"

for required_file in $required_files; do
  if [ ! -f "$required_file" ]; then
    echo "Missing required file: $required_file" >&2
    exit 1
  fi
done

python3 - <<'PY'
import json
import pathlib

root = pathlib.Path(".")
required_sites = {
    "imperial",
    "danish-fabrik",
    "bautica",
    "prefab",
    "casa-moderna",
    "family-homes",
    "everyday-homes",
    "property-360",
    "budapesti-magasepito-vallalat",
    "baufreund",
    "red-property",
    "timberhaus",
}

brands = json.loads((root / "sites/_portal/data/brands.json").read_text(encoding="utf-8"))
brand_ids = {brand["id"] for brand in brands["brands"]}
if len(brands["brands"]) != 12:
    raise SystemExit(f"Expected exactly 12 brands, found {len(brands['brands'])}.")
if brand_ids != required_sites:
    raise SystemExit(f"Brand/site mismatch: {sorted(required_sites ^ brand_ids)}")

home_data = json.loads(
    (root / "sites/_shared/assets/data/imperial-home.json").read_text(encoding="utf-8")
)
if home_data["meta"]["containsCustomerData"] is not False:
    raise SystemExit("imperial-home.json must declare containsCustomerData=false.")

home_page = (root / "sites/imperial/index.html").read_text(encoding="utf-8")
for section in home_data["sections"]:
    marker = f'id="{section["id"]}"'
    if marker not in home_page:
        raise SystemExit(f"Missing stable section ID: {section['id']}")

portal_page = (root / "sites/_portal/index.html").read_text(encoding="utf-8")
for marker in (
    'id="brand-select"',
    'data-device="desktop"',
    'data-device="tablet"',
    'data-device="mobile"',
    'id="review-panel"',
    'id="site-preview"',
):
    if marker not in portal_page:
        raise SystemExit(f"Missing portal marker: {marker}")
PY

echo "Platform structure and prototype data validation passed."
