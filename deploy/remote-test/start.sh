#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"
load_remote_env

docker info >/dev/null

base_compose --profile digital-pm config --quiet
integrated_compose config --quiet

base_compose --profile digital-pm up \
  -d --build --force-recreate --wait --wait-timeout 600
integrated_compose up \
  -d --build --force-recreate --wait --wait-timeout 900

"$script_dir/healthcheck.sh"
