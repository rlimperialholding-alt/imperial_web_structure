#!/usr/bin/env bash

remote_test_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$remote_test_dir/../.." && pwd)"
env_file="${IMPERIAL_ENV_FILE:-/opt/imperial-intelligence/secrets/remote-test.env}"

load_remote_env() {
  if [[ ! -r "$env_file" ]]; then
    echo "Missing environment file: $env_file" >&2
    echo "Run deploy/remote-test/prepare-app.sh first." >&2
    exit 1
  fi

  set -a
  # This file is generated locally and permissioned 0600.
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

base_compose() {
  docker compose \
    --project-directory "$repo_root" \
    --env-file "$env_file" \
    -f "$repo_root/docker-compose.yml" \
    "$@"
}

integrated_compose() {
  docker compose \
    --project-directory "$repo_root" \
    --project-name imperial-intelligence-test \
    --env-file "$env_file" \
    -f "$repo_root/docker-compose.github-test.yml" \
    "$@"
}
