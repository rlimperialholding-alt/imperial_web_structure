"""Focused Gate 8 reconciliation command tests.

Proves the configured reconciliation command exits 0 on the valid repository
and exits nonzero (fail-closed) when a checked invariant is deliberately
altered in a temporary, synthetic context. All fixtures are temporary files;
no network, no protected corpus mutation, no production write.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PLATFORM_CORE = Path(__file__).resolve().parents[1]
SCRIPT = PLATFORM_CORE / "scripts" / "reconciliation.py"
REPO_ROOT = PLATFORM_CORE.parents[1]
CORPUS_MANIFEST_PATH = REPO_ROOT / ".imperial-adas" / "protected-corpus-manifest.json"


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


def test_reconciliation_command_passes_on_valid_repository() -> None:
    result = _run_reconciliation()
    assert result.returncode == 0, result.stderr
    assert "reconciliation PASS: minden lokalis" in result.stdout
    # Baseline-eltérés megnevezve, nem elrejtve:
    assert "reconciliation NOTE (baseline)" in result.stdout


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
    assert "tracked-secret baseline hianyzik" in result.stderr


def test_reconciliation_fail_closed_on_source_lock_version_missing(
    tmp_path: Path,
) -> None:
    synthetic = tmp_path / "lock.json"
    synthetic.write_text(
        json.dumps({"alembic_head": "20260719_0006"}), encoding="utf-8"
    )
    result = _run_reconciliation(II_RECON_SOURCE_LOCK=str(synthetic))
    assert result.returncode != 0
    assert "SOURCE_LOCK platform_version ures" in result.stderr


def test_reconciliation_fail_closed_on_wrong_alembic_head() -> None:
    result = _run_reconciliation(II_RECON_EXPECTED_ALEMBIC_HEAD="99999999_9999")
    assert result.returncode != 0
    assert "alembic head" in result.stderr


def test_registry_probe_fail_closed_on_extra_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location(
        "reconciliation_under_test", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    isolated_engine = create_engine("sqlite://", poolclass=StaticPool)
    isolated_session = sessionmaker(
        bind=isolated_engine, autoflush=False, expire_on_commit=False, future=True
    )
    monkeypatch.setattr(module, "engine", isolated_engine)
    monkeypatch.setattr(module, "SessionLocal", isolated_session)
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
    isolated_engine.dispose()
