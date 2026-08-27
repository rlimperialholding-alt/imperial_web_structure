#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"
load_remote_env

check_url() {
  local name="$1"
  local url="$2"
  local status
  status="$(curl -fsS -o /dev/null -w '%{http_code}' \
    --connect-timeout 5 --max-time 20 "$url")"
  if [[ "$status" != "200" ]]; then
    echo "FAIL $name returned HTTP $status: $url" >&2
    return 1
  fi
  printf 'OK   %-24s %s\n' "$name" "$url"
}

check_url "Main workspace" "http://127.0.0.1:${HTTP_PORT:-8080}/healthz"
check_url "Platform Core" "http://127.0.0.1:${PLATFORM_CORE_PORT:-8091}/health/ready"
check_url "Digital PM" "http://127.0.0.1:${DIGITAL_PM_PORT:-8090}/health/ready"
check_url "CRM" "http://127.0.0.1:${CRM_TEST_PORT:-18787}/api/health"
check_url "ITEP Core" "http://127.0.0.1:${ITEP_TEST_PORT:-13000}/health/ready"
check_url "Integration Hub" "http://127.0.0.1:${HUB_TEST_PORT:-18080}/ready"

unhealthy="$(
  docker ps --filter health=unhealthy --format '{{.Names}}' |
    sed '/^[[:space:]]*$/d'
)"
if [[ -n "$unhealthy" ]]; then
  echo "Unhealthy containers:" >&2
  echo "$unhealthy" >&2
  exit 1
fi

echo "All remote test endpoints are healthy."
