#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"
load_remote_env

backup_root="${IMPERIAL_BACKUP_DIR:-/opt/imperial-intelligence/backups}"
latest_backup="$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
if [[ -z "$latest_backup" ]]; then
  echo "No backup is available under $backup_root." >&2
  exit 1
fi

run_compose() {
  local scope="$1"
  shift
  case "$scope" in
    base) base_compose "$@" ;;
    dpm) base_compose --profile digital-pm "$@" ;;
    integrated) integrated_compose "$@" ;;
    *)
      echo "Unknown compose scope: $scope" >&2
      return 64
      ;;
  esac
}

restore_database() {
  local scope="$1"
  local container="$2"
  local user="$3"
  local archive="$4"
  local restore_db="$5"

  run_compose "$scope" exec -T "$container" \
    dropdb --if-exists --force -U "$user" "$restore_db"
  run_compose "$scope" exec -T "$container" \
    createdb -U "$user" "$restore_db"
  if ! run_compose "$scope" exec -T "$container" \
    pg_restore -U "$user" -d "$restore_db" <"$archive"; then
    run_compose "$scope" exec -T "$container" \
      dropdb --if-exists --force -U "$user" "$restore_db"
    return 1
  fi

  local table_count
  if ! table_count="$(
    run_compose "$scope" exec -T "$container" \
      psql -U "$user" -d "$restore_db" -Atc \
      "select count(*) from information_schema.tables where table_schema = 'public';"
  )"; then
    run_compose "$scope" exec -T "$container" \
      dropdb --if-exists --force -U "$user" "$restore_db"
    return 1
  fi
  if [[ ! "$table_count" =~ ^[0-9]+$ || "$table_count" -eq 0 ]]; then
    echo "Restore test produced no public tables for $archive." >&2
    run_compose "$scope" exec -T "$container" \
      dropdb --if-exists --force -U "$user" "$restore_db"
    return 1
  fi

  run_compose "$scope" exec -T "$container" \
    dropdb --if-exists --force -U "$user" "$restore_db"
  echo "Restore OK: $(basename "$archive") ($table_count public tables)"
}

restore_database \
  base platform-postgres "${PLATFORM_DATABASE_USER:-imperial_platform}" \
  "$latest_backup/platform-core.dump" imperial_platform_restore_check
restore_database \
  dpm dpm-postgres "${DPM_DATABASE_USER:-imperial_dpm}" \
  "$latest_backup/digital-project-managers.dump" imperial_dpm_restore_check
restore_database \
  integrated hub-postgres imperial \
  "$latest_backup/integration-hub.dump" imperial_hub_restore_check
restore_database \
  integrated itep-postgres itep \
  "$latest_backup/itep-core.dump" imperial_itep_restore_check

crm_restore_dir="$(mktemp -d)"
trap 'rm -rf -- "$crm_restore_dir"' EXIT
tar -xzf "$latest_backup/crm-state.tar.gz" -C "$crm_restore_dir"
if ! find "$crm_restore_dir" -type f -print -quit | grep -q .; then
  echo "CRM restore test produced no files." >&2
  exit 1
fi
echo "Restore OK: crm-state.tar.gz"
echo "All isolated restore tests passed for $latest_backup."
