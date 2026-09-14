#!/bin/sh
set -eu

ENV_FILE="${1:-.env}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${IMPERIAL_API_PORT:-8000}}"
STATE_DIR="${RELEASE_STATE_DIR:-.release-state}"
COMPOSE="docker compose --env-file $ENV_FILE -f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.production.yml"

[ -f "$ENV_FILE" ] || { echo "Environment file not found: $ENV_FILE" >&2; exit 2; }
mkdir -p "$STATE_DIR"
DEPLOYING=0
rollback_on_error() {
  code=$?
  if [ "$code" -ne 0 ] && [ "$DEPLOYING" -eq 1 ] && [ -s "$STATE_DIR/previous-image" ]; then
    echo "Deployment failed; rolling back application image..." >&2
    RELEASE_STATE_DIR="$STATE_DIR" sh scripts/ops/rollback-release.sh "$ENV_FILE" || true
  fi
  exit "$code"
}
trap rollback_on_error EXIT INT TERM

python scripts/production_preflight.py --env-file "$ENV_FILE" --output "$STATE_DIR/preflight.json"

if $COMPOSE ps postgres --status running 2>/dev/null | grep -q postgres; then
  $COMPOSE --profile ops run --rm backup
fi

PREVIOUS_IMAGE=""
[ -f "$STATE_DIR/current-image" ] && PREVIOUS_IMAGE="$(cat "$STATE_DIR/current-image")"
NEW_IMAGE="$(grep '^IMPERIAL_HUB_IMAGE=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
[ -n "$NEW_IMAGE" ] || { echo "IMPERIAL_HUB_IMAGE is empty" >&2; exit 2; }
printf '%s\n' "$PREVIOUS_IMAGE" > "$STATE_DIR/previous-image"
DEPLOYING=1

$COMPOSE build migrate api worker beat
$COMPOSE up -d postgres redis minio create-bucket directus migrate api worker beat n8n

python - "$BASE_URL" <<'PY'
import json, sys, time, urllib.request
base = sys.argv[1].rstrip('/')
last = None
for _ in range(60):
    try:
        with urllib.request.urlopen(base + '/ready', timeout=5) as response:
            payload = json.load(response)
        if payload.get('status') == 'ready':
            raise SystemExit(0)
        last = payload
    except Exception as exc:
        last = str(exc)
    time.sleep(5)
print(f'Readiness failed: {last}', file=sys.stderr)
raise SystemExit(1)
PY

python scripts/production_canary.py --env-file "$ENV_FILE" --base-url "$BASE_URL" --output "$STATE_DIR/canary.json"
printf '%s\n' "$NEW_IMAGE" > "$STATE_DIR/current-image"
DEPLOYING=0
trap - EXIT INT TERM
printf 'Deployment PASS: %s\n' "$NEW_IMAGE"
