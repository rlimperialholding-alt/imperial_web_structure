"""Focused Gate 8 reconciliation command tests.

Proves the configured reconciliation command exits 0 on the valid repository
and exits nonzero (fail-closed) when a checked invariant is deliberately
altered in a temporary, synthetic context. All fixtures are temporary files;
no network, no protected corpus mutation, no production write. The database
isolation tests prove the command never connects to or mutates any database
configured through ``DATABASE_URL``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

PLATFORM_CORE = Path(__file__).resolve().parents[1]
SCRIPT = PLATFORM_CORE / "scripts" / "reconciliation.py"
SCRIPTS_DIR = PLATFORM_CORE / "scripts"
REPO_ROOT = PLATFORM_CORE.parents[1]
CORPUS_MANIFEST_PATH = REPO_ROOT / ".imperial-adas" / "protected-corpus-manifest.json"
SECRETS_BASELINE_PATH = REPO_ROOT / ".secrets.baseline"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_secret_baseline  # noqa: E402


def _run_reconciliation(**env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for key in (
        "II_RECON_CORPUS_MANIFEST",
        "II_RECON_SECRETS_BASELINE",
        "II_RECON_SOURCE_LOCK",
        "II_RECON_EXPECTED_ALEMBIC_HEAD",
    ):
        env.pop(key, None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(PLATFORM_CORE),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("reconciliation_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def live_secret_fingerprints() -> set[tuple[str, str, str]]:
    """One live tracked-secret scan shared by the baseline tamper tests."""
    completed = check_secret_baseline._live_scan()
    assert completed.returncode == 0, completed.stderr
    return check_secret_baseline._fingerprints(json.loads(completed.stdout))


def _find_live_baseline_entry(
    baseline: dict, live: set[tuple[str, str, str]]
) -> tuple[str, int, dict]:
    for filename, findings in baseline.get("results", {}).items():
        for index, finding in enumerate(findings):
            fingerprint = (
                filename.replace("\\", "/"),
                str(finding.get("type", "")),
                str(finding.get("hashed_secret", "")),
            )
            if fingerprint in live:
                return filename, index, dict(finding)
    raise AssertionError("No live baseline entry found for the tamper test.")


def _assert_no_secret_material(
    baseline: dict, output: str
) -> None:
    for findings in baseline.get("results", {}).values():
        for finding in findings:
            hashed_secret = finding.get("hashed_secret")
            if hashed_secret:
                assert str(hashed_secret) not in output


def test_reconciliation_command_passes_on_valid_repository() -> None:
    result = _run_reconciliation()
    assert result.returncode == 0, result.stderr
    assert "reconciliation PASS: minden lokalis" in result.stdout
    assert "reconciliation PASS: tracked-secret baseline:" in result.stdout
    # Megnevezett baseline-megfigyelés (stale-only bejegyzések), nem elrejtve:
    assert "stale baseline entry/entries" in result.stdout
    assert "reconciliation PASS: SOURCE_LOCK verziok rogzitve" in result.stdout
    assert "alembic_head 20260824_0075" in result.stdout


def test_reconciliation_fail_closed_on_corpus_sha_tamper(tmp_path: Path) -> None:
    manifest = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))
    tampered = {
        "schemaVersion": "2.1",
        "files": [
            {"path": manifest["files"][0]["path"], "sha256": "0" * 64}
        ],
    }
    synthetic = tmp_path / "tampered-manifest.json"
    synthetic.write_text(json.dumps(tampered), encoding="utf-8")
    result = _run_reconciliation(II_RECON_CORPUS_MANIFEST=str(synthetic))
    assert result.returncode != 0
    assert "corpusz-SHA elteres" in result.stderr
    assert "minden lokalis" not in result.stdout


def test_reconciliation_fail_closed_on_missing_corpus_file(tmp_path: Path) -> None:
    synthetic = tmp_path / "missing-manifest.json"
    synthetic.write_text(
        json.dumps(
            {
                "schemaVersion": "2.1",
                "files": [{"path": "does/not/exist.txt", "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )
    result = _run_reconciliation(II_RECON_CORPUS_MANIFEST=str(synthetic))
    assert result.returncode != 0
    assert "vedett corpuszfajl hianyzik" in result.stderr


def test_reconciliation_fail_closed_on_empty_files_list(tmp_path: Path) -> None:
    synthetic = tmp_path / "empty-manifest.json"
    synthetic.write_text(
        json.dumps({"schemaVersion": "2.1", "files": []}), encoding="utf-8"
    )
    result = _run_reconciliation(II_RECON_CORPUS_MANIFEST=str(synthetic))
    assert result.returncode != 0
    assert "files" in result.stderr


def test_reconciliation_fail_closed_on_missing_secret_baseline(
    tmp_path: Path,
) -> None:
    result = _run_reconciliation(
        II_RECON_SECRETS_BASELINE=str(tmp_path / "no-baseline.json")
    )
    assert result.returncode != 0
    assert "repository baseline is missing" in result.stderr


def test_reconciliation_fail_closed_on_removed_baseline_entry(
    tmp_path: Path, live_secret_fingerprints: set[tuple[str, str, str]]
) -> None:
    baseline = json.loads(SECRETS_BASELINE_PATH.read_text(encoding="utf-8"))
    filename, index, _ = _find_live_baseline_entry(baseline, live_secret_fingerprints)
    baseline["results"][filename].pop(index)
    if not baseline["results"][filename]:
        baseline["results"].pop(filename)
    synthetic = tmp_path / "removed-entry-baseline.json"
    synthetic.write_text(json.dumps(baseline), encoding="utf-8")
    result = _run_reconciliation(II_RECON_SECRETS_BASELINE=str(synthetic))
    assert result.returncode != 0
    assert "new candidate(s)" in result.stderr
    assert "minden lokalis" not in result.stdout
    _assert_no_secret_material(baseline, result.stdout)
    _assert_no_secret_material(baseline, result.stderr)


def test_reconciliation_fail_closed_on_changed_baseline_entry(
    tmp_path: Path, live_secret_fingerprints: set[tuple[str, str, str]]
) -> None:
    baseline = json.loads(SECRETS_BASELINE_PATH.read_text(encoding="utf-8"))
    filename, index, finding = _find_live_baseline_entry(
        baseline, live_secret_fingerprints
    )
    finding["hashed_secret"] = "0" * 40
    baseline["results"][filename][index] = finding
    synthetic = tmp_path / "changed-entry-baseline.json"
    synthetic.write_text(json.dumps(baseline), encoding="utf-8")
    result = _run_reconciliation(II_RECON_SECRETS_BASELINE=str(synthetic))
    assert result.returncode != 0
    assert "new candidate(s)" in result.stderr
    assert "minden lokalis" not in result.stdout
    _assert_no_secret_material(baseline, result.stdout)
    _assert_no_secret_material(baseline, result.stderr)


def test_secret_baseline_probe_maps_status_zero_to_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.check_secret_baseline,
        "reconcile_tracked_secrets",
        lambda baseline_path: (0, "7 tracked candidate(s) match the audited baseline."),
    )
    module._secret_baseline_probe()


def test_secret_baseline_probe_maps_nonzero_to_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.check_secret_baseline,
        "reconcile_tracked_secrets",
        lambda baseline_path: (
            1,
            "3 new candidate(s) in 1 tracked file(s).\n- svc/synthetic.py",
        ),
    )
    with pytest.raises(SystemExit) as excinfo:
        module._secret_baseline_probe()
    assert excinfo.value.code not in (0, None)
    assert "reconciliation FAIL" in str(excinfo.value)


def test_reconciliation_fail_closed_on_source_lock_head_tamper(
    tmp_path: Path,
) -> None:
    synthetic = tmp_path / "lock.json"
    synthetic.write_text(
        json.dumps(
            {
                "alembic_head": "99999999_9999",
                "platform_version": "5.0.0",
                "application_version": "1.5.0",
                "release_date": "2026-07-19",
            }
        ),
        encoding="utf-8",
    )
    result = _run_reconciliation(II_RECON_SOURCE_LOCK=str(synthetic))
    assert result.returncode != 0
    assert "alembic_head" in result.stderr
    assert "elter a migracios graf fejetol" in result.stderr


def test_reconciliation_fail_closed_on_source_lock_version_missing(
    tmp_path: Path,
) -> None:
    synthetic = tmp_path / "lock.json"
    synthetic.write_text(
        json.dumps({"alembic_head": "20260824_0075"}), encoding="utf-8"
    )
    result = _run_reconciliation(II_RECON_SOURCE_LOCK=str(synthetic))
    assert result.returncode != 0
    assert "SOURCE_LOCK platform_version ervenytelen" in result.stderr


def test_reconciliation_fail_closed_on_source_lock_malformed_version(
    tmp_path: Path,
) -> None:
    synthetic = tmp_path / "lock.json"
    synthetic.write_text(
        json.dumps(
            {
                "alembic_head": "20260824_0075",
                "platform_version": "5.0.0",
                "application_version": "release-candidate",
                "release_date": "2026-07-19",
            }
        ),
        encoding="utf-8",
    )
    result = _run_reconciliation(II_RECON_SOURCE_LOCK=str(synthetic))
    assert result.returncode != 0
    assert "application_version ervenytelen" in result.stderr


def test_reconciliation_fail_closed_on_source_lock_malformed_date(
    tmp_path: Path,
) -> None:
    synthetic = tmp_path / "lock.json"
    synthetic.write_text(
        json.dumps(
            {
                "alembic_head": "20260824_0075",
                "platform_version": "5.0.0",
                "application_version": "1.5.0",
                "release_date": "2026.07.19",
            }
        ),
        encoding="utf-8",
    )
    result = _run_reconciliation(II_RECON_SOURCE_LOCK=str(synthetic))
    assert result.returncode != 0
    assert "release_date ervenytelen" in result.stderr


def test_reconciliation_fail_closed_on_wrong_alembic_head() -> None:
    result = _run_reconciliation(II_RECON_EXPECTED_ALEMBIC_HEAD="99999999_9999")
    assert result.returncode != 0
    assert "alembic head" in result.stderr


def test_reconciliation_ignores_external_database_url_sentinels(
    tmp_path: Path,
) -> None:
    # Valós-külsejű, elérhetetlen file-URL: ha a script az app engine-t
    # használná, a drop_all/create_all kapcsolódási kísérletnél elbukna;
    # a privát in-memory motor mellett a parancs érintetlenül lefut.
    unreachable = _run_reconciliation(
        DATABASE_URL="sqlite:///Z:/ii-recon-no-such-drive/sentinel.db"
    )
    assert unreachable.returncode == 0, unreachable.stderr
    assert "minden lokalis" in unreachable.stdout

    # Valós-külsejű írható file-URL: ha bármely művelet a konfigurált URL-re
    # irányulna, a sentinel adatbázisfájl létrejönne; így soha.
    sentinel = tmp_path / "sentinel-production.db"
    file_url = _run_reconciliation(
        DATABASE_URL=f"sqlite:///{sentinel.as_posix()}"
    )
    assert file_url.returncode == 0, file_url.stderr
    assert "minden lokalis" in file_url.stdout
    assert not sentinel.exists()


def test_registry_probe_uses_private_engine_and_ignores_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "sentinel-production.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{sentinel.as_posix()}")
    module = _load_module()
    assert not hasattr(module, "engine")
    assert not hasattr(module, "SessionLocal")
    module._registry_probe()
    assert not sentinel.exists()


def test_registry_probe_fail_closed_on_extra_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    synthetic_extra = (
        "zz_synthetic_module",
        "Synthetic Module",
        "0.0.0",
        "Synthetic Owner",
        "low",
    )
    monkeypatch.setattr(module, "MODULES", list(module.MODULES) + [synthetic_extra])
    with pytest.raises(SystemExit) as excinfo:
        module._registry_probe()
    assert excinfo.value.code not in (0, None)
    assert "regiszter-elteres" in str(excinfo.value)
