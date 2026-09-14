.PHONY: up down logs test lint migrate validate-brands bootstrap-directus preflight staging-gate staging-up production-preflight production-gate production-canary online-staging-uat credential-manifest production-up backup backup-verify restore-drill deploy rollback package

up:
	docker compose up -d --build

staging-up:
	docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build

production-up:
	docker compose --env-file .env -f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.production.yml up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker beat directus n8n

test:
	pytest -q

lint:
	python scripts/static_check.py

migrate:
	alembic upgrade head

validate-brands:
	python -m scripts.validate_brand_registry

bootstrap-directus:
	python scripts/bootstrap_directus.py

preflight:
	python scripts/staging_preflight.py

staging-gate:
	python scripts/staging_gate.py --output runtime/staging-gate

production-preflight:
	python scripts/production_preflight.py --env-file .env --output runtime/production-preflight.json

production-gate:
	python scripts/production_gate.py --env-file .env --output runtime/production-gate-v0.8.1.json

production-canary:
	python scripts/production_canary.py --env-file .env --base-url "$${BASE_URL:-http://127.0.0.1:8000}"

online-staging-uat:
	python scripts/online_staging_uat.py --env-file .env --base-url "$${BASE_URL:?BASE_URL is required}"

credential-manifest:
	python scripts/credential_manifest.py

backup:
	docker compose --env-file .env -f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.production.yml --profile ops run --rm backup

backup-verify:
	docker compose --env-file .env -f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.production.yml --profile ops run --rm backup-verify

restore-drill:
	docker compose --env-file .env -f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.production.yml --profile ops run --rm restore-drill

deploy:
	sh scripts/ops/deploy-production.sh .env

rollback:
	sh scripts/ops/rollback-release.sh .env

package:
	cd .. && zip -r imperial-intelligence-integration-hub-v0.8.1-staging-handoff.zip imperial-intelligence-integration-hub-v0.8.1-staging-handoff -x '*/__pycache__/*' '*/.pytest_cache/*' '*/runtime/*' '*/.release-state/*'
