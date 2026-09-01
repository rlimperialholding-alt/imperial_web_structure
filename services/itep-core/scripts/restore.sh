#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
[ "$#" -ge 1 ] || { echo "Usage: restore.sh <backup.dump>" >&2; exit 2; }

BACKUP_FILE="$1"
if [ -f "${BACKUP_FILE}.sha256" ]; then
  sha256sum -c "${BACKUP_FILE}.sha256"
fi

pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --dbname="${DATABASE_URL}" \
  "${BACKUP_FILE}"

echo "Restore completed from ${BACKUP_FILE}"
