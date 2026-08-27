#!/usr/bin/env sh
set -eu

BASE_URL="${BASE_URL:-http://localhost:3000}"

curl --fail --silent "${BASE_URL}/health/live" >/dev/null
curl --fail --silent "${BASE_URL}/health/ready" >/dev/null

echo "Smoke test passed for ${BASE_URL}"
