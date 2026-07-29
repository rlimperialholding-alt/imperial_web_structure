#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this script as the normal operator account, not root." >&2
  exit 1
fi

secret_dir="${IMPERIAL_SECRET_DIR:-/opt/imperial-intelligence/secrets}"
env_file="$secret_dir/remote-test.env"
mkdir -p "$secret_dir"
chmod 700 "$secret_dir"

random_hex() {
  openssl rand -hex 32
}

write_secret_file() {
  local destination="$1"
  if [[ ! -s "$destination" ]]; then
    random_hex >"$destination"
  fi
  chmod 600 "$destination"
}

write_secret_file "$secret_dir/platform_db_password.txt"
write_secret_file "$secret_dir/dpm_db_password.txt"
write_secret_file "$secret_dir/dpm_auth_hs256_secret.txt"

if [[ -s "$env_file" ]]; then
  chmod 600 "$env_file"
  echo "Existing environment file preserved: $env_file"
  echo "No passwords or tokens were rotated."
  exit 0
fi

cat >"$env_file" <<EOF
COMPOSE_PROJECT_NAME=imperial-staging
HTTP_PORT=8080
PLATFORM_CORE_PORT=8091
DIGITAL_PM_PORT=8090
CRM_TEST_PORT=18787
ITEP_TEST_PORT=13000
HUB_TEST_PORT=18080
MOCK_TEST_PORT=19010
BUILD_CA_CERT_FILE=./docker/no-extra-ca.pem
PLATFORM_DB_PASSWORD_FILE=$secret_dir/platform_db_password.txt
DPM_DB_PASSWORD_FILE=$secret_dir/dpm_db_password.txt
DPM_AUTH_HS256_SECRET_FILE=$secret_dir/dpm_auth_hs256_secret.txt
PLATFORM_SESSION_SECRET=$(random_hex)
CRM_MIGRATION_TOKEN=$(random_hex)
ITEP_CRM_READ_TOKEN=$(random_hex)
ITEP_IDENTITY_SHARED_SECRET=$(random_hex)
HUB_POSTGRES_PASSWORD=$(random_hex)
HUB_API_ADMIN_TOKEN=$(random_hex)
ITEP_POSTGRES_PASSWORD=$(random_hex)
AUTH_TOKEN_PEPPER=$(random_hex)
AUTH_DATA_ENCRYPTION_KEY=$(random_hex)
AUTH_BOOTSTRAP_TOKEN=$(random_hex)
WHATSAPP_APP_SECRET=$(random_hex)
WHATSAPP_VERIFY_TOKEN=$(random_hex)
WHATSAPP_DATA_ENCRYPTION_KEY=$(random_hex)
CRM_WORKSPACE_ID=imperial-test
CRM_ADMIN_EMAIL=admin@imperial.local
NPM_STRICT_SSL=true
EOF

chmod 600 "$env_file"
echo "Local test secrets created at $env_file"
echo "The file must never be committed or sent by email."
