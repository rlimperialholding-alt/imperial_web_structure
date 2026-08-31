"""Task65 regresszió: Compose secret-deklarációk ↔ CI-provisioning egyeztetés.

A Task64 RemoteCI hiba (Staging `33420589061`, Imperial Intelligence
`33420589158`) oka az volt, hogy a Compose CI workflow-k csak a
``platform_db_password`` fájlt hozták létre, miközben a gyökér
``docker-compose.yml`` ``secrets:`` blokkja további bind-source fájlokat
deklarál. A Task65 megoldás:

- ``scripts/ci-provision-secrets.sh``: minden nem-production secret
  bind-source fájlt friss, szintetikus ``openssl rand`` értékkel provisionál
  (a repóban commitolt ``build_ca`` placeholder kivételével);
- ``scripts/check_ci_secret_provisioning.py``: a deklarációk és a
  provisioning közötti eltérést automatikusan blokkolja (drift mindkét
  irányban FAIL), és ellenőrzi, hogy a két workflow a provisioninget és az
  egyeztetést az első ``docker compose`` lépés előtt futtatja.

Ez a teszt ezeket az invariánsokat zárolja szintetikus szövegváltozatokkal
(fail-closed minden irányban), valamint a kompenzáló ellenőrző szkript
tulajdonságait.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO / "docker-compose.yml"
PROVISION_SCRIPT = REPO / "scripts" / "ci-provision-secrets.sh"
CHECKER_SCRIPT = REPO / "scripts" / "check_ci_secret_provisioning.py"
COMPENSATIONS_SCRIPT = REPO / "scripts" / "check_scan_exception_compensations.py"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
PLATFORM_CI_WORKFLOW = REPO / ".github" / "workflows" / "platform-ci.yml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _workflow_texts() -> tuple[tuple[str, str], ...]:
    return (
        (CI_WORKFLOW.name, CI_WORKFLOW.read_text(encoding="utf-8")),
        (PLATFORM_CI_WORKFLOW.name, PLATFORM_CI_WORKFLOW.read_text(encoding="utf-8")),
    )


def test_real_repository_state_reconciles_clean() -> None:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    status, message = checker.reconcile(
        COMPOSE_PATH.read_text(encoding="utf-8"),
        PROVISION_SCRIPT.read_text(encoding="utf-8"),
        _workflow_texts(),
    )
    assert status == 0, message


def test_compose_declaration_without_provisioning_fails_closed() -> None:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    # Új secret-deklaráció a Compose-ban, amely nincs a provisioning-listán.
    entry = (
        "  dpm_auth_hs256_secret:\n"
        "    file: ${DPM_AUTH_HS256_SECRET_FILE:-./secrets/dpm_auth_hs256_secret.txt}\n"
    )
    drifted = compose_text.replace(
        entry,
        entry + "  dpm_audit_log_key:\n"
        "    file: ${DPM_AUDIT_LOG_KEY_FILE:-./secrets/dpm_audit_log_key.txt}\n",
    )
    assert drifted != compose_text
    status, _ = checker.reconcile(
        drifted,
        PROVISION_SCRIPT.read_text(encoding="utf-8"),
        _workflow_texts(),
    )
    assert status == 1


def test_orphan_provisioning_entry_fails_closed() -> None:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    provisioning_text = PROVISION_SCRIPT.read_text(encoding="utf-8")
    drifted = provisioning_text.replace(
        "dpm_auth_hs256_secret\n", "dpm_auth_hs256_secret\ndpm_orphan_secret\n"
    )
    assert drifted != provisioning_text
    status, _ = checker.reconcile(
        COMPOSE_PATH.read_text(encoding="utf-8"),
        drifted,
        _workflow_texts(),
    )
    assert status == 1


def test_compose_default_path_mismatch_fails_closed() -> None:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    drifted = compose_text.replace(
        "${DPM_AUTH_HS256_SECRET_FILE:-./secrets/dpm_auth_hs256_secret.txt}",
        "${DPM_AUTH_HS256_SECRET_FILE:-./secrets/dpm_auth_hs256_secret_v2.txt}",
    )
    assert drifted != compose_text
    status, _ = checker.reconcile(
        drifted,
        PROVISION_SCRIPT.read_text(encoding="utf-8"),
        _workflow_texts(),
    )
    assert status == 1


def test_workflow_without_provisioning_invocation_fails_closed() -> None:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    workflows = list(_workflow_texts())
    name, text = workflows[0]
    drifted = (name, text.replace("sh scripts/ci-provision-secrets.sh", "true"))
    workflows[0] = drifted
    status, _ = checker.reconcile(
        COMPOSE_PATH.read_text(encoding="utf-8"),
        PROVISION_SCRIPT.read_text(encoding="utf-8"),
        tuple(workflows),
    )
    assert status == 1


def test_workflow_with_provisioning_after_compose_fails_closed() -> None:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    workflows = list(_workflow_texts())
    name, text = workflows[0]
    # A provisioning lépést egy docker compose lépés MÖGÉ tesszük
    # (sorrendsértés: a secret-fájloknak a compose előtt kell létezniük).
    line = "        run: sh scripts/ci-provision-secrets.sh\n"
    assert line in text
    removed = text.replace(line, "")
    lines = removed.splitlines(keepends=True)
    compose_line = next(
        i for i, workflow_line in enumerate(lines) if "docker compose" in workflow_line
    )
    drifted = "".join(
        lines[: compose_line + 1]
        + [
            "      - name: Generate ephemeral synthetic CI secret files (non-production)\n",
            "        shell: bash\n",
            line,
        ]
        + lines[compose_line + 1 :]
    )
    workflows[0] = (name, drifted)
    status, _ = checker.reconcile(
        COMPOSE_PATH.read_text(encoding="utf-8"),
        PROVISION_SCRIPT.read_text(encoding="utf-8"),
        tuple(workflows),
    )
    assert status == 1


def test_provisioning_script_literal_secret_assignment_fails_closed() -> None:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    provisioning_text = PROVISION_SCRIPT.read_text(encoding="utf-8")
    drifted = provisioning_text.replace(
        "for name in $CANONICAL_SECRET_NAMES; do",
        "SECRET_LITERAL=deadbeef\nfor name in $CANONICAL_SECRET_NAMES; do",
    )
    assert drifted != provisioning_text
    try:
        checker._provisioning_forbids_literal_secrets(drifted)
    except ValueError:
        return
    raise AssertionError("literal secret assignment must fail closed")


def test_provisioning_script_generates_only_openssl_rand_values() -> None:
    text = PROVISION_SCRIPT.read_text(encoding="utf-8")
    assert "openssl rand -hex 32" in text
    # Minden secret-fájlba író sor csak openssl rand generálás lehet.
    for line in text.splitlines():
        if "> \"$SECRET_DIR" in line:
            assert "openssl rand -hex 32" in line, line
    # A workflow-kban nincs inline secret-generálás (a régi blokk eltűnt).
    for _name, workflow_text in _workflow_texts():
        assert "openssl rand -hex 32 > secrets/" not in workflow_text


def test_both_workflows_wire_provisioning_and_reconciliation_before_compose() -> None:
    for path in (CI_WORKFLOW, PLATFORM_CI_WORKFLOW):
        lines = path.read_text(encoding="utf-8").splitlines()
        provision_at = next(
            i for i, line in enumerate(lines) if "ci-provision-secrets.sh" in line
        )
        check_at = next(
            i for i, line in enumerate(lines) if "check_ci_secret_provisioning.py" in line
        )
        compose_at = next(
            i for i, line in enumerate(lines) if "docker compose" in line
        )
        assert provision_at < compose_at, f"{path.name}: provisioning sorrend hiba"
        assert check_at < compose_at, f"{path.name}: reconciliation sorrend hiba"


def test_ephemeral_secret_directory_is_git_ignored() -> None:
    import subprocess

    completed = subprocess.run(
        ["git", "check-ignore", "-q", "secrets/platform_db_password.txt"],
        cwd=str(REPO),
        capture_output=True,
    )
    assert completed.returncode == 0, "secrets/ könyvtárnak git-ignoráltnak kell lennie"


def test_compensation_checker_detects_missing_integrity_violation(tmp_path) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><script src="https://cdn.example/app.js"></script></body></html>\n',
        encoding="utf-8",
    )
    violations = module._violations_for(bad)
    kinds = {kind for _line, kind in violations}
    assert "missing-integrity" in kinds


def test_compensation_checker_detects_plaintext_http_violation(tmp_path) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><a href="http://insecure.example/">link</a></body></html>\n',
        encoding="utf-8",
    )
    violations = module._violations_for(bad)
    kinds = {kind for _line, kind in violations}
    assert "plaintext-http-link" in kinds


def test_compensation_checker_accepts_clean_template(tmp_path) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    good = tmp_path / "good.html"
    good.write_text(
        '<html><body>\n'
        '<script src="/static/app.js"></script>\n'
        '<script src="https://cdn.example/lib.js" '
        'integrity="sha384-abc"></script>\n'
        '<a href="/login">login</a>\n'
        "</body></html>\n",
        encoding="utf-8",
    )
    assert module._violations_for(good) == []


def test_compensation_checker_passes_on_real_templates() -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    assert module.main() == 0


def test_enforce_script_covers_all_four_scan_parts() -> None:
    module = _load(
        "enforce_semgrep_verdict_invariants", REPO / "scripts" / "enforce_semgrep_verdict.py"
    )
    assert len(module.PARTS) == 4
    assert len(module.EXITS) == 4
    assert "semgrep-platform-core-templates.json" in module.PARTS
    assert "semgrep-platform-core-templates.exit" in module.EXITS
    assert len(set(module.PARTS)) == len(module.PARTS)
