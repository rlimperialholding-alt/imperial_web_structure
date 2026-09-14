from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_staging_deploy_runs_network_checks_inside_api_container() -> None:
    text = (ROOT / "scripts/ops/deploy-staging-remote.sh").read_text(encoding="utf-8")
    assert "production_preflight.py" not in text
    assert "exec -T api python scripts/bootstrap_directus.py" in text
    assert "exec -T api python scripts/staging_preflight.py" in text
    assert "exec -T api python scripts/online_staging_uat.py" in text


def test_staging_deploy_uses_stable_project_and_release_image() -> None:
    text = (ROOT / "scripts/ops/deploy-staging-remote.sh").read_text(encoding="utf-8")
    assert "COMPOSE_PROJECT_NAME=imperial-guidance" in text
    assert "imperial-intelligence-integration-hub-staging:$RELEASE_NAME" in text
    assert "pull postgres redis minio create-bucket directus n8n" in text
    assert "build migrate api worker beat" in text


def test_staging_rollback_validates_old_release_inside_container() -> None:
    text = (ROOT / "scripts/ops/rollback-staging-remote.sh").read_text(encoding="utf-8")
    assert "exec -T api python scripts/staging_preflight.py" in text
    assert "exec -T api python scripts/production_canary.py" in text


def test_base_compose_images_are_parameterized() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for variable in ("POSTGRES_IMAGE", "REDIS_IMAGE", "DIRECTUS_IMAGE", "N8N_IMAGE", "MINIO_IMAGE", "MINIO_MC_IMAGE"):
        assert variable in text
