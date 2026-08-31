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

Task66 review-remediáció (Review-1 HIGH / Review-2 CRITICAL): a Task65
változat ``umask 0177``-je a secret-könyvtárat 0600 módúvá tehette, amin a
runner nem tudott áthatolni, így az ``openssl rand > secrets/<név>.txt``
írás meghiúsult. A javítás ``umask 0077`` + explicit ``chmod 0700`` a
könyvtáron (a fájlok 0400-as minimális jogosultsága változatlan). Az
alábbi végrehajtási regressziók valódi temp könyvtárban futtatják a
szkriptet, és ellenőrzik a könyvtár traversálhatóságát, a fájlok
létrejöttét/módját és a secret-értékek logmentességét.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import subprocess
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


def test_enforce_script_covers_all_five_scan_parts() -> None:
    module = _load(
        "enforce_semgrep_verdict_invariants", REPO / "scripts" / "enforce_semgrep_verdict.py"
    )
    assert len(module.PARTS) == 5
    assert len(module.EXITS) == 5
    assert "semgrep-platform-core-templates.json" in module.PARTS
    assert "semgrep-platform-core-templates.exit" in module.EXITS
    assert "semgrep-shell-workflow.json" in module.PARTS
    assert "semgrep-shell-workflow.exit" in module.EXITS
    assert len(set(module.PARTS)) == len(module.PARTS)


def _provisioned_names() -> list[str]:
    checker = _load("check_ci_secret_provisioning", CHECKER_SCRIPT)
    return checker._parse_provisioning_list(PROVISION_SCRIPT.read_text(encoding="utf-8"))


def test_provisioning_script_uses_traversable_directory_mode() -> None:
    # Task66 Review-1 HIGH / Review-2 CRITICAL regresszió: az umask 0177 a
    # secret-könyvtárat 0600 módúvá tehette, amin a runner nem tudott
    # áthatolni (a fájlírás meghiúsult). A javítás umask 0077 + explicit
    # 0700 könyvtár-mód; a secret-fájlok 0400 jogosultsága változatlan.
    text = PROVISION_SCRIPT.read_text(encoding="utf-8")
    assert "umask 0177" not in text
    assert "umask 0077" in text
    assert 'chmod 0700 "$SECRET_DIR"' in text
    assert 'chmod 0400 "$SECRET_DIR/${name}.txt"' in text


def test_provisioning_script_executes_in_real_temp_dir(tmp_path) -> None:
    # Végrehajtási regresszió valódi temp könyvtárban: a szkript létrehozza
    # a traversálható könyvtárat és minden kanonikus secret-fájlt, a
    # fájlok 0400 (POSIX) módúak, az értékek 64 hex karakter hosszú
    # openssl rand kimenetek, és a kimenet egyetlen generált értéket sem
    # tartalmaz (logmentesség).
    names = _provisioned_names()
    secret_dir = tmp_path / "secrets"
    completed = subprocess.run(
        ["sh", "scripts/ci-provision-secrets.sh"],
        cwd=str(REPO),
        env=dict(os.environ, CI_SECRET_DIR=str(secret_dir)),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    values: dict[str, str] = {}
    for name in names:
        secret_file = secret_dir / f"{name}.txt"
        assert secret_file.is_file(), f"{name}: secret-fájl nem jött létre"
        content = secret_file.read_text(encoding="utf-8").strip()
        assert re.fullmatch(r"[0-9a-f]{64}", content), f"{name}: nem openssl rand érték"
        values[name] = content
    # Könyvtár traversálhatóság (X_OK) és minimális jogosultságok.
    assert os.access(secret_dir, os.X_OK), "a secret-könyvtár nem traversálható"
    if os.name == "posix":
        assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o700, (
            "a secret-könyvtár módja nem 0700"
        )
        for name in names:
            mode = stat.S_IMODE((secret_dir / f"{name}.txt").stat().st_mode)
            assert mode == 0o400, f"{name}: fájlmód {oct(mode)} nem 0400"
    # Logmentesség: sem a stdout, sem a stderr nem tartalmazza az értékeket.
    output = completed.stdout + completed.stderr
    for name, content in values.items():
        assert content not in output, f"{name}: secret-érték a szkript kimenetében"
    assert f"Provisioned {len(names)} ephemeral synthetic CI secret file(s)" in completed.stdout
    # A Windows proof-path-ot a chmod 0400 csak olvashatóvá teheti; a
    # takarítás előtt írhatóvá állítjuk a fájlokat (POSIX-on no-op).
    for name in names:
        (secret_dir / f"{name}.txt").chmod(0o600)


def test_provisioning_script_repairs_preexisting_restrictive_directory(tmp_path) -> None:
    # POSIX-only: a korábbi hibás 0600 könyvtár-módot a chmod 0700 javítja
    # (a Windows proof-path nem érvényesít unix módokat, ott a teszt nem
    # fut — a mkdir -p egy már létező könyvtárat nem módosítana).
    if os.name != "posix":
        return
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    secret_dir.chmod(0o600)
    completed = subprocess.run(
        ["sh", "scripts/ci-provision-secrets.sh"],
        cwd=str(REPO),
        env=dict(os.environ, CI_SECRET_DIR=str(secret_dir)),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o700
    for name in _provisioned_names():
        assert (secret_dir / f"{name}.txt").is_file()


def test_provisioning_script_is_posix_sh_syntax_valid() -> None:
    completed = subprocess.run(
        ["sh", "-n", str(PROVISION_SCRIPT)], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


def test_compensation_checker_detects_unquoted_plaintext_http(tmp_path) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><a href=http://insecure.example/>x</a></body></html>\n',
        encoding="utf-8",
    )
    kinds = {kind for _line, kind in module._violations_for(bad)}
    assert "plaintext-http-link" in kinds


def test_compensation_checker_detects_unquoted_remote_script_without_integrity(
    tmp_path,
) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><script src=https://cdn.example/app.js></script></body></html>\n',
        encoding="utf-8",
    )
    kinds = {kind for _line, kind in module._violations_for(bad)}
    assert "missing-integrity" in kinds


def test_compensation_checker_detects_jinja_expression_plaintext_http(tmp_path) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><img src="{{ \'http://\' + host + \'/x.png\' }}"></body></html>\n',
        encoding="utf-8",
    )
    kinds = {kind for _line, kind in module._violations_for(bad)}
    assert "plaintext-http-link" in kinds


def test_compensation_checker_detects_jinja_dynamic_remote_script_without_integrity(
    tmp_path,
) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><script src="https://{{ cdn_host }}/lib.js"></script></body></html>\n',
        encoding="utf-8",
    )
    kinds = {kind for _line, kind in module._violations_for(bad)}
    assert "missing-integrity" in kinds


def test_compensation_checker_detects_protocol_relative_script_without_integrity(
    tmp_path,
) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><script src="//cdn.example/app.js"></script></body></html>\n',
        encoding="utf-8",
    )
    kinds = {kind for _line, kind in module._violations_for(bad)}
    assert "missing-integrity" in kinds


def test_compensation_checker_detects_entity_obfuscated_plaintext_http(tmp_path) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><body><a href="http&#58;//evil.example/">x</a></body></html>\n',
        encoding="utf-8",
    )
    kinds = {kind for _line, kind in module._violations_for(bad)}
    assert "plaintext-http-link" in kinds


def test_compensation_checker_accepts_jinja_local_urls(tmp_path) -> None:
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    good = tmp_path / "good.html"
    good.write_text(
        '<html><body>\n'
        '<script src="{{ url_for(\'static\', filename=\'app.js\') }}"></script>\n'
        '<a href="{{ url_for(\'login\') }}">login</a>\n'
        '<form action="{{ url_for(\'submit\') }}" method="post"></form>\n'
        "</body></html>\n",
        encoding="utf-8",
    )
    assert module._violations_for(good) == []


def test_compensation_checker_accepts_https_with_integrity_and_local_paths(
    tmp_path,
) -> None:
    # Positive kontroll: a remote https script/link integrity attribútummal
    # és a helyi útvonalak nem sértenek.
    module = _load("check_scan_exception_compensations", COMPENSATIONS_SCRIPT)
    good = tmp_path / "good.html"
    good.write_text(
        '<html><body>\n'
        '<script src="https://cdn.example/lib.js" integrity="sha384-abc"></script>\n'
        '<link href="https://fonts.example/x.css" rel="stylesheet" '
        'integrity="sha384-def">\n'
        '<a href="/login">login</a>\n'
        '<img src="/static/logo.png">\n'
        "</body></html>\n",
        encoding="utf-8",
    )
    assert module._violations_for(good) == []
