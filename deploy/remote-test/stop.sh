#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"
load_remote_env

integrated_compose stop
base_compose --profile digital-pm stop

echo "Services stopped. Databases and Docker volumes were preserved."
