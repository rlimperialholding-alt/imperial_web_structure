#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

. /etc/os-release
if [[ ${ID:-} != "ubuntu" ]]; then
  echo "This installer supports Ubuntu Server only." >&2
  exit 1
fi

case "${VERSION_ID:-}" in
  22.04|24.04) ;;
  *)
    echo "Supported Ubuntu versions: 22.04 and 24.04." >&2
    exit 1
    ;;
esac

operator="${SUDO_USER:-}"
if [[ -z "$operator" || "$operator" == "root" ]]; then
  echo "Run with sudo from the normal operator account (not a root login)." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates curl git gnupg jq openssl python3 python-is-python3 tar unzip

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  -o /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  >/etc/apt/sources.list.d/cloudflared.list

apt-get update
apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
  docker-compose-plugin cloudflared

systemctl enable --now docker
usermod -aG docker "$operator"

install -d -m 0750 -o "$operator" -g "$operator" \
  /opt/imperial-intelligence \
  /opt/imperial-intelligence/app \
  /opt/imperial-intelligence/backups
install -d -m 0700 -o "$operator" -g "$operator" \
  /opt/imperial-intelligence/secrets

echo
echo "Host installation completed."
echo "Log out and back in once so Docker group membership becomes active."
echo "No router port forwarding was configured."
