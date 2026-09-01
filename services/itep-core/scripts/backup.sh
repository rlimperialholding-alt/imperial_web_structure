#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="${BACKUP_DIR}/itep-${STAMP}.dump"

mkdir -p "${BACKUP_DIR}"
pg_dump --format=custom --no-owner --no-privileges \
  --dbname="${DATABASE_URL}" \
  --file="${FILE}"

sha256sum "${FILE}" > "${FILE}.sha256"
echo "Backup created: ${FILE}"
