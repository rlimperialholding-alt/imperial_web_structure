#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"
load_remote_env

backup_root="${IMPERIAL_BACKUP_DIR:-/opt/imperial-intelligence/backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$backup_root/$stamp"
mkdir -p "$destination"
chmod 700 "$destination"

base_compose exec -T platform-postgres \
  pg_dump -U "${PLATFORM_DATABASE_USER:-imperial_platform}" \
  -d "${PLATFORM_DATABASE_NAME:-imperial_platform}" -Fc \
  >"$destination/platform-core.dump"

base_compose --profile digital-pm exec -T dpm-postgres \
  pg_dump -U "${DPM_DATABASE_USER:-imperial_dpm}" \
  -d "${DPM_DATABASE_NAME:-imperial_dpm}" -Fc \
  >"$destination/digital-project-managers.dump"

integrated_compose exec -T hub-postgres \
  pg_dump -U imperial -d imperial -Fc \
  >"$destination/integration-hub.dump"

integrated_compose exec -T itep-postgres \
  pg_dump -U itep -d itep -Fc \
  >"$destination/itep-core.dump"

integrated_compose exec -T crm \
  tar -C /app/.wrangler/state -czf - . \
  >"$destination/crm-state.tar.gz"

git -C "$repo_root" rev-parse HEAD >"$destination/source-commit.txt"
(
  cd "$destination"
  sha256sum ./* >SHA256SUMS
)

echo "Backup completed: $destination"
echo "Secrets were not included."
