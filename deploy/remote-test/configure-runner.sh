#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

operator="${SUDO_USER:-}"
if [[ -z "$operator" || "$operator" == "root" ]]; then
  echo "Run with sudo from the normal operator account." >&2
  exit 1
fi

read -r -p "GitHub repository URL: " repo_url
read -r -p "Runner version shown by GitHub (for example 2.327.1): " version
read -r -p "SHA-256 shown by GitHub for actions-runner-linux-x64: " expected_sha
read -r -s -p "One-hour GitHub runner registration token: " runner_token
echo

if [[ -z "$repo_url" || -z "$version" || -z "$expected_sha" || -z "$runner_token" ]]; then
  echo "Every value is required." >&2
  exit 1
fi
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid runner version." >&2
  exit 1
fi
if [[ ! "$expected_sha" =~ ^[a-fA-F0-9]{64}$ ]]; then
  echo "Invalid SHA-256 value." >&2
  exit 1
fi

runner_dir="/opt/actions-runner"
archive="/tmp/actions-runner-linux-x64-${version}.tar.gz"
download_url="https://github.com/actions/runner/releases/download/v${version}/actions-runner-linux-x64-${version}.tar.gz"

if [[ -e "$runner_dir/.runner" ]]; then
  echo "A runner is already configured at $runner_dir." >&2
  exit 1
fi

install -d -m 0750 -o "$operator" -g "$operator" "$runner_dir"
curl -fL --retry 3 -o "$archive" "$download_url"
echo "${expected_sha,,}  $archive" | sha256sum -c -
tar -xzf "$archive" -C "$runner_dir"
rm -f "$archive"
chown -R "$operator:$operator" "$runner_dir"

sudo -u "$operator" "$runner_dir/config.sh" \
  --url "$repo_url" \
  --token "$runner_token" \
  --name "imperial-test-$(hostname -s)" \
  --labels "imperial-test" \
  --work "_work" \
  --unattended \
  --replace
unset runner_token

(
  cd "$runner_dir"
  ./svc.sh install "$operator"
  ./svc.sh start
  ./svc.sh status
)
