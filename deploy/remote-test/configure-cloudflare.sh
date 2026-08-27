#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed. Run install-host.sh first." >&2
  exit 1
fi

echo "Create Cloudflare Access applications before exposing tunnel hostnames."
echo "Allow only approved email addresses and require MFA or one-time PIN."
read -r -s -p "Paste the Cloudflare Tunnel token: " tunnel_token
echo

if [[ -z "$tunnel_token" ]]; then
  echo "No token supplied." >&2
  exit 1
fi

cloudflared service install "$tunnel_token"
unset tunnel_token
systemctl enable --now cloudflared
systemctl --no-pager --full status cloudflared
