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

operator_home="$(getent passwd "$operator" | cut -d: -f6)"
if [[ -z "$operator_home" || ! -d "$operator_home" ]]; then
  echo "Cannot resolve the operator home directory." >&2
  exit 1
fi

read -r -p "Paste the administrator SSH public key: " public_key
if [[ ! "$public_key" =~ ^(ssh-ed25519|sk-ssh-ed25519@openssh.com|ssh-rsa)[[:space:]]+[A-Za-z0-9+/=]+([[:space:]].*)?$ ]]; then
  echo "Invalid OpenSSH public key." >&2
  exit 1
fi

install -d -m 0700 -o "$operator" -g "$operator" "$operator_home/.ssh"
authorized_keys="$operator_home/.ssh/authorized_keys"
touch "$authorized_keys"
chown "$operator:$operator" "$authorized_keys"
chmod 0600 "$authorized_keys"

if ! grep -Fqx -- "$public_key" "$authorized_keys"; then
  printf '%s\n' "$public_key" >>"$authorized_keys"
fi
unset public_key

config_file="/etc/ssh/sshd_config.d/90-imperial-remote-test.conf"
cat >"$config_file" <<EOF
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers $operator
ListenAddress 127.0.0.1
ListenAddress ::1
EOF
chmod 0644 "$config_file"

sshd -t
systemctl restart ssh

echo "SSH key access configured for $operator."
echo "SSH listens on localhost only; no LAN or public SSH port is exposed."
echo "Test the Cloudflare SSH connection before leaving the physical console."
