import json
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_PATCH_ROOT = SERVICE_ROOT.parents[1]


def test_integration_targets_existing_repository_and_isolated_branch() -> None:
    payload = json.loads((SERVICE_ROOT / "UPSTREAM-INTEGRATION.json").read_text(encoding="utf-8"))
    assert payload["target_repository"] == "rlimperialholding-alt/imperial_web_structure"
    assert payload["target_base_branch"] == "staging"
    assert payload["integration_branch"] == "agent/operational-guidance-v0.8.1"
    assert payload["integration_mode"] == "additive-isolated-service"


def test_compose_namespace_and_ports_do_not_collide_with_web_staging() -> None:
    env = (SERVICE_ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (SERVICE_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "COMPOSE_PROJECT_NAME=imperial-oge" in env
    for port in ("18080", "18055", "15678", "19000", "19001"):
        assert port in env
        assert port in compose
    assert ":8080" not in compose


def test_parallel_codex_workstreams_are_explicitly_protected() -> None:
    payload = json.loads((SERVICE_ROOT / "COORDINATION.json").read_text(encoding="utf-8"))
    branches = {item["branch"] for item in payload["parallel_workstreams"]}
    assert "feature/platform-foundation" in branches
    assert "agent/migration-engine-v1" in branches
    assert payload["merge_policy"] == "draft-pr-only"
    assert payload["direct_merge"] is False


def test_ci_is_path_scoped_and_has_no_deploy_job() -> None:
    workflow = (REPO_PATCH_ROOT / ".github" / "workflows" / "operational-guidance-ci.yml").read_text(
        encoding="utf-8"
    )
    assert 'services/operational-guidance/**' in workflow
    assert "agent/operational-guidance-v0.8.1" in workflow
    assert "check_changed_paths.py" in workflow
    assert "permissions:\n  contents: read" in workflow
    lowered = workflow.casefold()
    assert "ssh" not in lowered
    assert "deploy" not in lowered
