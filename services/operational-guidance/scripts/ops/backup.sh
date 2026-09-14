#!/bin/sh
set -eu

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="/backups/${STAMP}"
mkdir -p "$TARGET"

pg_dump --format=custom --no-owner --no-acl --file="$TARGET/database.dump"
tar -C /runtime -czf "$TARGET/operational-runtime.tar.gz" .
cp /config/operational-process-catalog-v1.0.json "$TARGET/operational-process-catalog-v1.0.json"
(
  cd "$TARGET"
  sha256sum database.dump operational-runtime.tar.gz operational-process-catalog-v1.0.json > manifest.sha256
)
ln -sfn "$STAMP" /backups/latest

find /backups -mindepth 1 -maxdepth 1 -type d -mtime "+${BACKUP_RETENTION_DAYS:-30}" -exec rm -rf {} +
printf 'Backup completed: %s\n' "$STAMP"
