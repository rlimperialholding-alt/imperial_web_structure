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
sites/_portal/data/artifacts.json
sites/_shared/assets/tokens.css
sites/_shared/assets/components.css
sites/_shared/assets/admin.css
sites/_shared/assets/admin.js
sites/_shared/assets/preview-bootstrap.css
sites/_shared/assets/review-bridge.css
sites/_shared/assets/review-bridge.js
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

artifacts = json.loads(
    (root / "sites/_portal/data/artifacts.json").read_text(encoding="utf-8")
)
if artifacts["meta"]["containsCustomerData"] is not False:
    raise SystemExit("artifacts.json must declare containsCustomerData=false.")
if artifacts["meta"]["runtimeExternalApis"] is not False:
    raise SystemExit("artifacts.json must declare runtimeExternalApis=false.")

total_test_pages = 0
for brand in brands["brands"]:
    artifact_brand = artifacts["brands"].get(brand["id"], {"pages": []})
    pages = artifact_brand["pages"]
    if brand["pageCount"] != len(pages):
        raise SystemExit(
            f"Page count mismatch for {brand['id']}: "
            f"brands.json={brand['pageCount']}, artifacts.json={len(pages)}"
        )
    total_test_pages += len(pages)

    for page in pages:
        relative_path = page["path"].lstrip("/")
        preview_file = root / "sites" / brand["id"] / (relative_path or "index.html")
        if not preview_file.is_file():
            raise SystemExit(f"Missing configured preview file: {preview_file}")

        if page["kind"].startswith("drive-"):
            if not page.get("sourceId"):
                raise SystemExit(f"Missing Drive sourceId: {brand['id']}{page['path']}")
            preview_content = preview_file.read_text(encoding="utf-8")
            if 'name="robots" content="noindex,nofollow"' not in preview_content:
                raise SystemExit(f"Missing noindex directive: {preview_file}")
            if "/assets/review-bridge.js" not in preview_content:
                raise SystemExit(f"Missing review bridge: {preview_file}")
            if "cdn.jsdelivr.net/npm/bootstrap" in preview_content:
                raise SystemExit(f"External Bootstrap dependency remains: {preview_file}")

if total_test_pages != 50:
    raise SystemExit(f"Expected 50 configured test pages, found {total_test_pages}.")

for css_file in root.glob("sites/*/drive/**/*.css"):
    css_content = css_file.read_text(encoding="utf-8")
    if "url('http://" in css_content or 'url("http://' in css_content:
        raise SystemExit(f"Imported CSS contains remote runtime asset: {css_file}")
    if "url('https://" in css_content or 'url("https://' in css_content:
        raise SystemExit(f"Imported CSS contains remote runtime asset: {css_file}")

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
    'id="page-select"',
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
