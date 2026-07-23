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
compose.yaml
docker/nginx/nginx.conf
docker/nginx/conf.d/staging.conf
sites/_portal/index.html
sites/_shared/assets/site.css
"

for required_file in $required_files; do
  if [ ! -f "$required_file" ]; then
    echo "Missing required file: $required_file" >&2
    exit 1
  fi
done

echo "Structure validation passed."
