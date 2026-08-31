#!/usr/bin/env sh
# Task65 canonical ephemeral CI secret provisioning.
#
# A Compose-modell (gyökér docker-compose.yml ``secrets:`` blokkja) által
# igényelt minden nem-production secret bind-source fájlt friss, futásonkénti,
# szintetikus runner-adatként hozza létre: minden érték ``openssl rand -hex 32``,
# soha nem commitolt, nem repository/environment production secret, és a
# production adapterek/external write módok érintetlenek (OFF/fail-closed a
# Compose alapértelmezéseiben). A ``docker/no-extra-ca.pem`` (build_ca) a
# repóban commitolt nem-secret placeholder, ezért itt nem generálódik.
#
# A CANONICAL_SECRET_NAMES blokk az egyetlen igazságforrása a CI-körök által
# provisionált névkészletnek; a scripts/check_ci_secret_provisioning.py ezt a
# blokkot a Compose deklarációkkal egyezteti, és bármely eltérésnél
# fail-closed (drift-blokkoló regresszió).
set -eu

# CANONICAL_SECRET_NAMES_BEGIN
CANONICAL_SECRET_NAMES="
platform_db_password
platform_expert_review_secret
platform_marketing_review_secret
platform_copywriter_review_secret
platform_visual_review_secret
platform_campaign_package_secret
platform_release_hmac_key
market_evidence_kek
house_designer_site_kek
dpm_db_password
dpm_auth_hs256_secret
"
# CANONICAL_SECRET_NAMES_END

SECRET_DIR="${CI_SECRET_DIR:-secrets}"

# A secret-könyvtárnak a runner számára traversálhatónak kell lennie, ezért
# umask 0077 (könyvtárak 0700, fájlok 0600) + explicit chmod 0700 a már
# létező könyvtár javítására is; az egyes secret-fájlok ezután 0400-ra
# szűkülnek, így csak a tulajdonos olvashatja őket (chown-nal a
# 10001:10001 app-felhasználóé lesznek Linux runneren).
umask 0077
mkdir -p "$SECRET_DIR"
chmod 0700 "$SECRET_DIR"

for name in $CANONICAL_SECRET_NAMES; do
  openssl rand -hex 32 > "$SECRET_DIR/${name}.txt"
  chmod 0400 "$SECRET_DIR/${name}.txt"
done

# A 10001:10001 (imperial app-felhasználó) tulajdonlás a runneren szükséges a
# container-belül olvasott secret-fájlokhoz; csak Linux runneren értelmes
# (a Windows hoszton futó dry-run nem hív chown-t, a CI pedig itt fail-closed).
if [ "$(uname -s 2>/dev/null || true)" = Linux ] && command -v sudo >/dev/null 2>&1; then
  sudo chown 10001:10001 "$SECRET_DIR"/*.txt
fi

count=$(printf '%s' "$CANONICAL_SECRET_NAMES" | tr ' ' '\n' | sed '/^$/d' | wc -l | tr -d ' ')
printf 'Provisioned %s ephemeral synthetic CI secret file(s) in %s.\n' "$count" "$SECRET_DIR"
