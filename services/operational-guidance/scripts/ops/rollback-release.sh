#!/bin/sh
set -eu

ENV_FILE="${1:-.env}"
STATE_DIR="${RELEASE_STATE_DIR:-.release-state}"
[ -f "$STATE_DIR/previous-image" ] || { echo "No previous image recorded" >&2; exit 2; }
PREVIOUS_IMAGE="$(cat "$STATE_DIR/previous-image")"
[ -n "$PREVIOUS_IMAGE" ] || { echo "Previous image is empty" >&2; exit 2; }

export IMPERIAL_HUB_IMAGE="$PREVIOUS_IMAGE"
docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f docker-compose.staging.yml \
  -f docker-compose.production.yml \
  up -d --no-build migrate api worker beat
printf '%s\n' "$PREVIOUS_IMAGE" > "$STATE_DIR/current-image"
printf 'Application image rollback completed: %s\n' "$PREVIOUS_IMAGE"
printf 'Database was not downgraded. Use the verified backup and a maintenance window for destructive restore.\n'
