from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from app.growth_ops import registry as growth_registry
from app.growth_ops.registry import GrowthRegistryError

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ensure_public_land_registry_binding as updater  # noqa: E402


def _registry(*, include_binding: bool = True) -> dict[str, object]:
    sources: dict[str, object] = {
        "construction_etdr": {
            "enabled": False,
            "motor": "construction",
            "bucket": "etdr",
        },
        "construction_public_request": {
            "enabled": False,
            "motor": "construction",
            "bucket": "public_request",
        },
        "construction_fitout_change": {
            "enabled": False,
            "motor": "construction",
            "bucket": "fitout_change",
        },
        "construction_property_development": {
            "enabled": False,
            "motor": "construction",
            "bucket": "property_development",
        },
        "construction_horeca": {
            "enabled": False,
            "motor": "construction",
            "bucket": "horeca",
        },
        "construction_contractor_capacity": {
            "enabled": False,
            "motor": "construction",
            "bucket": "contractor_capacity",
        },
        "distress_liquidation": {
            "enabled": False,
            "motor": "distress",
            "bucket": "liquidation",
        },
        "distress_bankruptcy": {
            "enabled": False,
            "motor": "distress",
            "bucket": "bankruptcy",
        },
        "distress_enforcement": {
            "enabled": False,
            "motor": "distress",
            "bucket": "enforcement",
        },
        "distress_officer_change": {
            "enabled": False,
            "motor": "distress",
            "bucket": "officer_change",
        },
        "distress_registered_office_change": {
            "enabled": False,
            "motor": "distress",
            "bucket": "registered_office_change",
        },
        "distress_construction_dispute": {
            "enabled": False,
            "motor": "distress",
            "bucket": "construction_dispute",
        },
        "ivs_existing_target_engine": {
            "enabled": False,
            "motor": "ivs",
            "bucket": "existing_target_engine",
        },
    }
    if include_binding:
        sources[updater.SOURCE_ID] = {
            "enabled": False,
            "motor": "construction",
            "bucket": "property_development",
            "legacy_note": "replace only this object",
        }
    return {
        "version": "production-fixture-v1",
        "opaque_configuration": {
            "secret_reference": "SECRET_SENTINEL_MUST_NOT_BE_PRINTED",
            "unicode": "árvíztűrő tükörfúrógép",
        },
        "motors": {
            "construction": {
                "interval_minutes": 60,
                "max_raw_signals_per_run": 500,
                "daily_raw_review_target": 300,
            },
            "distress": {
                "interval_minutes": 60,
                "max_raw_signals_per_run": 500,
            },
            "ivs": {"daily_at": "08:00", "max_raw_signals_per_run": 500},
        },
        "sources": sources,
        "brands": {
            "imperial": {
                "sender_email": "info@imperialholding.hu",
                "domain_key": "imperialholding.hu",
                "secret_ref": "gmail.json",
            }
        },
        "routing": {"residential_construction": "imperial"},
    }


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    registry_path = tmp_path / "active-growth-registry.json"
    registry_path.write_bytes(
        (json.dumps(_registry(), ensure_ascii=False, indent=4) + "\n")
        .replace("\n", "\r\n")
        .encode("utf-8")
    )
    portal_path = tmp_path / "portals.json"
    repository_portals = (
        Path(__file__).resolve().parents[3] / "config" / "land-acquisition" / "portals.json"
    )
    portal_path.write_bytes(repository_portals.read_bytes())
    fake_secret = tmp_path / "gmail.json"
    fake_secret.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(growth_registry, "_managed_secret", lambda reference: fake_secret)
    return registry_path, portal_path


def _source_member(raw: bytes) -> tuple[str, updater._JsonMember]:
    text = raw.decode("utf-8-sig")
    root_start = updater._skip_whitespace(text, 0)
    root_end = updater._skip_value(text, root_start)
    root = updater._object_members(text, root_start, root_end)
    sources = updater._only_member(root, "sources")
    assert sources is not None
    members = updater._object_members(text, sources.value_start, sources.value_end)
    target = updater._only_member(members, updater.SOURCE_ID)
    assert target is not None
    return text, target


def test_cli_is_dry_run_by_default_and_apply_is_explicit(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path, portal_path = files
    original = registry_path.read_bytes()

    result = updater.main(
        [
            "--registry-file",
            str(registry_path),
            "--portal-registry-file",
            str(portal_path),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "dry_run"
    assert summary["dry_run"] is True
    assert summary["applied"] is False
    assert summary["action"] == "would_update"
    assert summary["backup_path"] is None
    assert registry_path.read_bytes() == original
    assert not list(registry_path.parent.glob("*.backup-*"))

    result = updater.main(
        [
            "--registry-file",
            str(registry_path),
            "--portal-registry-file",
            str(portal_path),
            "--apply",
        ]
    )

    assert result == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["status"] == "applied"
    assert applied["dry_run"] is False
    assert applied["applied"] is True
    assert applied["action"] == "update"


def test_cli_defaults_registry_inputs_from_runtime_settings(
    files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_path, portal_path = files
    original = registry_path.read_bytes()
    monkeypatch.setenv("GROWTH_OPS_REGISTRY_FILE", str(registry_path))
    monkeypatch.setenv("LAND_ACQUISITION_PORTAL_REGISTRY_FILE", str(portal_path))

    result = updater.main([])

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["registry_file"] == str(registry_path.resolve())
    assert summary["portal_registry_file"] == str(portal_path.resolve())
    assert summary["dry_run"] is True
    assert registry_path.read_bytes() == original


def test_apply_preserves_all_bytes_outside_binding_and_creates_exact_backup(
    files: tuple[Path, Path]
) -> None:
    registry_path, portal_path = files
    original = registry_path.read_bytes()
    original_text, original_member = _source_member(original)

    summary = updater.ensure_public_land_registry_binding(
        registry_file=registry_path,
        portal_registry_file=portal_path,
        apply=True,
    )

    updated = registry_path.read_bytes()
    updated_text, updated_member = _source_member(updated)
    assert original_text[: original_member.value_start] == updated_text[
        : updated_member.value_start
    ]
    assert original_text[original_member.value_end :] == updated_text[updated_member.value_end :]
    expected = updater._expected_binding(summary["route_set_sha256"])
    assert json.loads(
        updated_text[updated_member.value_start : updated_member.value_end]
    ) == expected
    assert summary["before_sha256"] == updater._sha256(original)
    assert summary["proposed_sha256"] == updater._sha256(updated)
    assert summary["readback_sha256"] == summary["proposed_sha256"]
    backup = Path(summary["backup_path"])
    assert backup.parent == registry_path.parent
    assert backup.read_bytes() == original
    assert summary["backup_sha256"] == updater._sha256(original)
    if os.name == "posix":
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert "SECRET_SENTINEL_MUST_NOT_BE_PRINTED" not in json.dumps(summary)


def test_apply_inserts_missing_binding_without_rewriting_existing_registry_data(
    files: tuple[Path, Path]
) -> None:
    registry_path, portal_path = files
    raw = (
        json.dumps(_registry(include_binding=False), ensure_ascii=False, indent=2) + "\n"
    ).encode(
        "utf-8",
    )
    registry_path.write_bytes(raw)

    summary = updater.ensure_public_land_registry_binding(
        registry_file=registry_path,
        portal_registry_file=portal_path,
        apply=True,
    )

    assert summary["action"] == "insert"
    updated = json.loads(registry_path.read_text(encoding="utf-8"))
    assert updated["sources"][updater.SOURCE_ID] == updater._expected_binding(
        summary["route_set_sha256"]
    )
    without_binding = dict(updated)
    without_binding["sources"] = dict(updated["sources"])
    without_binding["sources"].pop(updater.SOURCE_ID)
    assert without_binding == _registry(include_binding=False)


def test_failed_post_replace_readback_rolls_back_from_hash_verified_backup(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path, portal_path = files
    original = registry_path.read_bytes()

    def fail_readback(*args: object, **kwargs: object) -> str:
        raise GrowthRegistryError("simulated readback failure")

    monkeypatch.setattr(updater, "_readback", fail_readback)

    with pytest.raises(updater.RegistryBindingUpdateError) as raised:
        updater.ensure_public_land_registry_binding(
            registry_file=registry_path,
            portal_registry_file=portal_path,
            apply=True,
        )

    summary = raised.value.summary
    assert summary["status"] == "error"
    assert summary["error_code"] == "post_replace_readback_failed"
    assert summary["rollback_performed"] is True
    assert summary["applied"] is False
    assert registry_path.read_bytes() == original
    assert Path(summary["backup_path"]).read_bytes() == original
    assert "simulated readback failure" not in json.dumps(summary)
    assert "SECRET_SENTINEL_MUST_NOT_BE_PRINTED" not in json.dumps(summary)


def test_corrupt_backup_fails_before_any_target_replace(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path, portal_path = files
    original = registry_path.read_bytes()
    real_write_exclusive = updater._write_exclusive
    replace_calls = 0

    def corrupt_backup(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        real_write_exclusive(path, data, mode=mode)
        path.write_bytes(b"corrupt-backup")

    def forbidden_replace(*args: object, **kwargs: object) -> None:
        nonlocal replace_calls
        replace_calls += 1
        raise AssertionError("target replacement must not run")

    monkeypatch.setattr(updater, "_write_exclusive", corrupt_backup)
    monkeypatch.setattr(updater, "_atomic_replace", forbidden_replace)

    with pytest.raises(updater.RegistryBindingUpdateError) as raised:
        updater.ensure_public_land_registry_binding(
            registry_file=registry_path,
            portal_registry_file=portal_path,
            apply=True,
        )

    summary = raised.value.summary
    assert summary["error_code"] == "backup_hash_readback_failed"
    assert summary["backup_sha256"] == updater._sha256(b"corrupt-backup")
    assert summary["rollback_performed"] is False
    assert replace_calls == 0
    assert registry_path.read_bytes() == original


def test_registry_symlink_is_rejected_before_resolution_and_mutation(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path, portal_path = files

    class SymlinkPath:
        def expanduser(self) -> SymlinkPath:
            return self

        def is_symlink(self) -> bool:
            return True

        def resolve(self, *, strict: bool = False) -> Path:
            raise AssertionError("symlink must be rejected before resolve")

    monkeypatch.setattr(updater, "_resolve_registry_path", lambda path: SymlinkPath())

    with pytest.raises(GrowthRegistryError, match="symlinks are not allowed"):
        updater.ensure_public_land_registry_binding(
            registry_file=registry_path,
            portal_registry_file=portal_path,
            apply=True,
        )

    assert registry_path.read_text(encoding="utf-8").find(
        "SECRET_SENTINEL_MUST_NOT_BE_PRINTED"
    ) >= 0
    assert not list(registry_path.parent.glob("*.backup-*"))


def test_unchanged_apply_does_not_create_backup(files: tuple[Path, Path]) -> None:
    registry_path, portal_path = files
    updater.ensure_public_land_registry_binding(
        registry_file=registry_path,
        portal_registry_file=portal_path,
        apply=True,
    )
    backups_before = sorted(registry_path.parent.glob("*.backup-*"))

    summary = updater.ensure_public_land_registry_binding(
        registry_file=registry_path,
        portal_registry_file=portal_path,
        apply=True,
    )

    assert summary["status"] == "unchanged"
    assert summary["action"] == "unchanged"
    assert summary["applied"] is False
    assert summary["backup_path"] is None
    assert sorted(registry_path.parent.glob("*.backup-*")) == backups_before


def test_runtime_digest_drift_fails_before_backup_or_mutation(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path, portal_path = files
    original = registry_path.read_bytes()
    monkeypatch.setattr(
        updater,
        "managed_public_land_route_set_sha256",
        lambda registry: "0" * 64,
    )

    with pytest.raises(GrowthRegistryError, match="conflicts with the runtime growth gate"):
        updater.ensure_public_land_registry_binding(
            registry_file=registry_path,
            portal_registry_file=portal_path,
            apply=True,
        )

    assert registry_path.read_bytes() == original
    assert not list(registry_path.parent.glob("*.backup-*"))
