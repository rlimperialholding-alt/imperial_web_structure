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

if git -C "$repo_root" rev-parse HEAD >"$destination/source-commit.txt" 2>/dev/null; then
  :
elif [[ -s "$repo_root/.source-commit" ]]; then
  cp "$repo_root/.source-commit" "$destination/source-commit.txt"
else
  echo "unknown" >"$destination/source-commit.txt"
fi
(
  cd "$destination"
  sha256sum ./* >SHA256SUMS
)

echo "Backup completed: $destination"
echo "Secrets were not included."

replica_count=0
if [[ -n "${IMPERIAL_BACKUP_REPLICA_DIRS:-}" ]]; then
  IFS=',' read -r -a replica_roots <<<"$IMPERIAL_BACKUP_REPLICA_DIRS"
  for replica_root in "${replica_roots[@]}"; do
    replica_root="${replica_root#"${replica_root%%[![:space:]]*}"}"
    replica_root="${replica_root%"${replica_root##*[![:space:]]}"}"
    if [[ "$replica_root" != /* || "$replica_root" == "/" ]]; then
      echo "Backup replica directory must be an absolute, non-root path: $replica_root" >&2
      exit 1
    fi
    mkdir -p "$replica_root"
    if [[ "$(readlink -f "$replica_root")" == "$(readlink -f "$backup_root")" ]]; then
      echo "Backup replica directory cannot equal the primary backup directory." >&2
      exit 1
    fi
    replica_destination="$replica_root/$stamp"
    if [[ -e "$replica_destination" ]]; then
      echo "Backup replica already exists: $replica_destination" >&2
      exit 1
    fi
    cp -a "$destination" "$replica_destination"
    (
      cd "$replica_destination"
      sha256sum -c SHA256SUMS
    )
    replica_count=$((replica_count + 1))
    echo "Verified backup replica: $replica_destination"
  done
fi

echo "Verified backup locations in this run: $((replica_count + 1))"
