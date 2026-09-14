#!/bin/sh
set -eu

NAME="${BACKUP_NAME:-latest}"
TARGET="/backups/${NAME}"
[ -d "$TARGET" ] || { echo "Backup not found: $TARGET" >&2; exit 2; }
DB="restore_drill_$(date -u +%Y%m%d%H%M%S)"
cleanup() {
  dropdb --if-exists "$DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
createdb "$DB"
pg_restore --no-owner --no-acl --dbname="$DB" "$TARGET/database.dump"
psql --dbname="$DB" --no-psqlrc --tuples-only --command="SELECT COUNT(*) FROM alembic_version;" >/dev/null
psql --dbname="$DB" --no-psqlrc --tuples-only --command="SELECT COUNT(*) FROM operational_processes;" >/dev/null
printf 'Database restore drill PASS: %s -> %s\n' "$NAME" "$DB"
