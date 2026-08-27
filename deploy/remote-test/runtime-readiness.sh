#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"
load_remote_env

mode="${1:-staging}"
if [[ "$mode" != "staging" && "$mode" != "production" ]]; then
  echo "Usage: $0 [staging|production]" >&2
  exit 2
fi

failures=0
check() {
  local description="$1"
  shift
  if "$@"; then
    echo "PASS: $description"
  else
    echo "FAIL: $description" >&2
    failures=$((failures + 1))
  fi
}

at_least_four_cpu() {
  (( $(nproc) >= 4 ))
}

at_least_eight_gib_ram() {
  local total_kib
  total_kib="$(awk '/MemTotal:/ {print $2}' /proc/meminfo)"
  (( total_kib >= 7800000 ))
}

local_postgres_running() {
  [[ "$(base_compose ps --status running --quiet platform-postgres | wc -l)" -eq 1 ]]
}

latest_backup_verified() {
  local root latest
  root="${IMPERIAL_BACKUP_DIR:-/opt/imperial-intelligence/backups}"
  latest="$(find "$root" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
  [[ -n "$latest" ]] || return 1
  (cd "$latest" && sha256sum -c SHA256SUMS >/dev/null)
}

valid_storage_quotas() {
  local crm partner
  crm="${CRM_PROJECT_DOCUMENT_QUOTA_BYTES:-5368709120}"
  partner="${PARTNER_EVIDENCE_PROJECT_QUOTA_BYTES:-5368709120}"
  [[ "$crm" =~ ^[0-9]+$ && "$partner" =~ ^[0-9]+$ ]] || return 1
  (( crm >= 15728640 && partner >= 12582912 ))
}

three_backup_locations_configured() {
  local configured="${IMPERIAL_BACKUP_REPLICA_DIRS:-}"
  [[ -n "$configured" ]] || return 1
  IFS=',' read -r -a replicas <<<"$configured"
  (( ${#replicas[@]} >= 2 ))
}

production_platform_configured() {
  [[ "${PLATFORM_ENVIRONMENT:-development}" == "production" ]] &&
    [[ "${PLATFORM_REQUIRE_HTTPS:-false}" == "true" ]] &&
    [[ -n "${PLATFORM_ALLOWED_HOSTS:-}" ]] &&
    [[ -n "${PLATFORM_CONTROL_CENTER_API_TOKEN:-}" ]]
}

check "legalább 4 vCPU" at_least_four_cpu
check "legalább 8 GB RAM" at_least_eight_gib_ram
check "Docker-alapú platform fut" base_compose ps --status running platform-core
check "a PostgreSQL ugyanazon a szerveren fut" local_postgres_running
check "a legfrissebb elsődleges mentés SHA-256 ellenőrzése sikeres" latest_backup_verified
check "projekt- és bizonyítéktár-kvóták érvényesek" valid_storage_quotas

if [[ "$mode" == "production" ]]; then
  check "három mentési hely van konfigurálva" three_backup_locations_configured
  check "a platform production/HTTPS/host/API kapui konfiguráltak" production_platform_configured
fi

if (( failures > 0 )); then
  echo "Runtime readiness: FAIL ($failures hiba)" >&2
  exit 1
fi

echo "Runtime readiness: PASS ($mode)"
