#!/bin/sh
set -eu
: "${SSH_TARGET:?Set SSH_TARGET}"
: "${ROLLBACK_RELEASE:?Set ROLLBACK_RELEASE to an absolute release application path}"
REMOTE_ROOT=${REMOTE_ROOT:-/opt/imperial-guidance}
BASE_URL=${BASE_URL:-https://staging.example.hu}
ssh "$SSH_TARGET" sh -s -- "$ROLLBACK_RELEASE" "$REMOTE_ROOT" "$BASE_URL" <<'REMOTE'
set -eu
TARGET=$1
ROOT=$2
BASE_URL=$3
[ -d "$TARGET" ] || { echo "Rollback target missing" >&2; exit 2; }
cd "$TARGET"
COMPOSE="docker compose --env-file .env -f docker-compose.yml -f docker-compose.staging.yml"
$COMPOSE config --quiet
$COMPOSE up -d postgres redis minio create-bucket directus n8n
$COMPOSE up -d api worker beat
$COMPOSE exec -T api python scripts/staging_preflight.py \
  --online --require-directus-catalog \
  --output runtime/uat/rollback-preflight.json
$COMPOSE exec -T api python scripts/production_canary.py \
  --base-url "$BASE_URL" \
  --output runtime/uat/rollback-canary.json
ln -sfn "$TARGET" "$ROOT/current"
printf '%s\n' "$TARGET" > "$ROOT/CURRENT_RELEASE"
REMOTE
