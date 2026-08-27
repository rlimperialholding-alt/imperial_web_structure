#!/bin/sh
set -eu

: "${SSH_TARGET:?Set SSH_TARGET, for example deploy@staging.example.hu}"
: "${RELEASE_ZIP:?Set RELEASE_ZIP to the local release ZIP}"
: "${STAGING_ENV_FILE:?Set STAGING_ENV_FILE to the completed staging .env file}"
: "${GOOGLE_SERVICE_ACCOUNT_FILE:?Set GOOGLE_SERVICE_ACCOUNT_FILE to the service-account JSON}"

REMOTE_ROOT=${REMOTE_ROOT:-/opt/imperial-guidance}
RELEASE_NAME=${RELEASE_NAME:-v0.8.1-$(date -u +%Y%m%dT%H%M%SZ)}
BASE_URL=${BASE_URL:-https://staging.example.hu}
REMOTE_RELEASE="$REMOTE_ROOT/releases/$RELEASE_NAME"

case "$RELEASE_NAME" in *[!A-Za-z0-9._-]*) echo "Unsafe RELEASE_NAME" >&2; exit 2;; esac
[ -f "$RELEASE_ZIP" ] || { echo "Release ZIP not found" >&2; exit 2; }
[ -f "$STAGING_ENV_FILE" ] || { echo "Staging env file not found" >&2; exit 2; }
[ -f "$GOOGLE_SERVICE_ACCOUNT_FILE" ] || { echo "Service-account JSON not found" >&2; exit 2; }

ssh "$SSH_TARGET" "mkdir -p '$REMOTE_RELEASE/secrets' '$REMOTE_ROOT/releases'"
scp "$RELEASE_ZIP" "$SSH_TARGET:$REMOTE_RELEASE/release.zip"
scp "$STAGING_ENV_FILE" "$SSH_TARGET:$REMOTE_RELEASE/.env"
scp "$GOOGLE_SERVICE_ACCOUNT_FILE" "$SSH_TARGET:$REMOTE_RELEASE/secrets/google-service-account.json"

ssh "$SSH_TARGET" sh -s -- "$REMOTE_RELEASE" "$REMOTE_ROOT" "$BASE_URL" "$RELEASE_NAME" <<'REMOTE'
set -eu
RELEASE_DIR=$1
ROOT=$2
BASE_URL=$3
RELEASE_NAME=$4
cd "$RELEASE_DIR"
unzip -q release.zip
APP_DIR=$(find . -mindepth 1 -maxdepth 1 -type d | head -n 1)
[ -n "$APP_DIR" ] || { echo "Application directory missing" >&2; exit 3; }
cd "$APP_DIR"
cp ../.env .env
mkdir -p secrets
cp ../secrets/google-service-account.json secrets/google-service-account.json
chmod 600 .env secrets/google-service-account.json

# Stable Compose project name keeps volumes, networks and service identities consistent across releases.
if grep -q '^COMPOSE_PROJECT_NAME=' .env; then
  sed -i 's/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=imperial-guidance/' .env
else
  printf '\nCOMPOSE_PROJECT_NAME=imperial-guidance\n' >> .env
fi
# Release-specific image tag makes application rollback real, not just a source-directory switch.
if grep -q '^IMPERIAL_HUB_IMAGE=' .env; then
  sed -i "s#^IMPERIAL_HUB_IMAGE=.*#IMPERIAL_HUB_IMAGE=imperial-intelligence-integration-hub-staging:$RELEASE_NAME#" .env
else
  printf 'IMPERIAL_HUB_IMAGE=imperial-intelligence-integration-hub-staging:%s\n' "$RELEASE_NAME" >> .env
fi

COMPOSE="docker compose --env-file .env -f docker-compose.yml -f docker-compose.staging.yml"
$COMPOSE config --quiet
# Pull only third-party infrastructure images; the Imperial image is built and tagged per release.
$COMPOSE pull postgres redis minio create-bucket directus n8n
$COMPOSE build migrate api worker beat
# Offline application/config/catalog/service-account validation runs inside the built container,
# where /run/secrets and the runtime volume match the real service environment.
$COMPOSE run --rm --no-deps api python scripts/staging_preflight.py \
  --output runtime/uat/pre-deploy.json
$COMPOSE up -d postgres redis minio create-bucket directus n8n
$COMPOSE run --rm migrate
$COMPOSE up -d api worker beat
# Internal service names resolve only inside the Compose network, therefore all integration checks run in api.
$COMPOSE exec -T api python scripts/bootstrap_directus.py
$COMPOSE exec -T api python scripts/staging_preflight.py \
  --online --require-directus-catalog \
  --output runtime/uat/staging-preflight-online-after-import.json
$COMPOSE exec -T api python scripts/online_staging_uat.py \
  --base-url "$BASE_URL" \
  --output runtime/uat/online-staging-uat-v0.8.1.json
ln -sfn "$RELEASE_DIR/$APP_DIR" "$ROOT/current"
printf '%s\n' "$RELEASE_DIR/$APP_DIR" > "$ROOT/CURRENT_RELEASE"
REMOTE

echo "Deployment and online UAT completed: $RELEASE_NAME"
