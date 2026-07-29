#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"
load_remote_env

cd "$repo_root"

python3 scripts/validate-platform.py
bash scripts/validate-structure.sh
python3 deploy/remote-test/route-smoke.py

integrated_compose exec -T \
  -e HUB_URL=http://hub-api:8000 \
  -e ITEP_URL=http://itep-api:3000 \
  hub-api python scripts/github_test_uat.py

integrated_compose exec -T \
  -e CRM_API_BASE_URL=http://crm:8787 \
  -e CRM_ACCESS_TOKEN="$ITEP_CRM_READ_TOKEN" \
  -e CRM_WORKSPACE_ID="${CRM_WORKSPACE_ID:-imperial-test}" \
  -e CRM_ACTIVITIES_PATH=/api/integrations/itep/activities \
  -e CRM_AUTH_HEADER=X-ITEP-Token \
  -e CRM_AUTH_SCHEME=none \
  hub-api python scripts/crm_live_contract_test.py

pilot_id="synthetic-five-document-remote-$(date -u +%Y%m%dT%H%M%S)-$$"
integrated_compose exec -T \
  -e CRM_API_BASE_URL=http://crm:8787 \
  -e CRM_MIGRATION_TOKEN="$CRM_MIGRATION_TOKEN" \
  -e ITEP_CRM_READ_TOKEN="$ITEP_CRM_READ_TOKEN" \
  -e MIGRATION_PILOT_BATCH_ID="$pilot_id" \
  -e EXPECT_NEW=5 \
  hub-api python scripts/crm_five_document_pilot.py

echo "Functional, read-only CRM contract, UAT and synthetic five-document pilot passed."
