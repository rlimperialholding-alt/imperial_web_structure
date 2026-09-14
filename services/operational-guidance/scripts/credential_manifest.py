from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.process_cards.domain import RealRole


def token() -> str:
    return secrets.token_urlsafe(48)


def build_manifest() -> dict[str, Any]:
    role_tokens = {role.value: token() for role in RealRole}
    n8n = token()
    return {
        "environment": "staging",
        "generated_secrets": {
            "API_ADMIN_TOKEN": token(),
            "DIRECTUS_WEBHOOK_SECRET": token(),
            "METRICS_TOKEN": token(),
            "HUMAN_ROLE_TOKENS_JSON": role_tokens,
            "SERVICE_TOKENS_JSON": {"n8n": n8n, "directus": token()},
            "N8N_SERVICE_TOKEN": n8n,
        },
        "external_values_required": {
            "DATABASE_URL": "PostgreSQL connection string",
            "REDIS_URL": "Redis connection string",
            "DIRECTUS_URL": "Staging Directus URL",
            "DIRECTUS_STATIC_TOKEN": "Directus static token with catalog CRUD",
            "PROCESS_CARD_DRIVE_FOLDER_ID": "Drive target folder ID",
            "PROCESS_CARD_APPROVER_EMAIL": "Managing director approval inbox",
            "PROCESS_CARD_GMAIL_DELEGATED_USER": "Delegated Google Workspace sender",
            "GOOGLE_SERVICE_ACCOUNT_FILE": "/run/secrets/google-service-account.json",
            "TRUSTED_HOSTS_JSON": ["staging.example.hu"],
            "CORS_ORIGINS_JSON": ["https://staging.example.hu"],
            "IMPERIAL_HUB_IMAGE": "registry.example.hu/imperial/hub:0.8.1",
            "DIRECTUS_IMAGE": "directus/directus:<PINNED>",
            "N8N_IMAGE": "n8nio/n8n:<PINNED>",
            "MINIO_IMAGE": "minio/minio:<PINNED>",
            "MINIO_MC_IMAGE": "minio/mc:<PINNED>",
        },
        "google_domain_wide_delegation_scopes": [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
        "warning": "Store generated secrets in a secret manager; do not commit this file.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a staging credential manifest")
    parser.add_argument("--output", default="runtime/uat/staging-credential-manifest.json")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
