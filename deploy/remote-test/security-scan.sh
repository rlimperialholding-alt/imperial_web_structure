#!/usr/bin/env bash
set -Eeuo pipefail

trivy_image="${TRIVY_IMAGE:-aquasec/trivy:0.70.0}"
images=(
  "imperial-platform-core:local"
  "imperial-digital-project-managers:local"
  "imperial-complete-test-crm:local"
  "imperial-complete-test-hub:local"
  "imperial-complete-test-itep-runtime:local"
)

for image in "${images[@]}"; do
  docker image inspect "$image" >/dev/null
  echo "Scanning $image"
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v imperial-trivy-cache:/root/.cache/trivy \
    "$trivy_image" image \
    --scanners vuln \
    --severity HIGH,CRITICAL \
    --ignore-unfixed \
    --exit-code 1 \
    --no-progress \
    "$image"
done

echo "All required runtime images passed the HIGH/CRITICAL vulnerability gate."
