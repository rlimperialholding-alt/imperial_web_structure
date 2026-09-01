"""Focused Gate 8 reconciliation command tests.

Proves the configured reconciliation command evaluates every probe, and exits
nonzero (fail-closed) when a checked invariant is deliberately altered in a
temporary, synthetic context. The tracked-secret probe reconciles the
canonical baseline through the *audited repository state*; the anti-masking
and tamper tests pin a small synthetic live-scan document through the direct
pytest seam and inject a
*post-audited-state* tamper (a new digest, or a duplicate occurrence of an
audited digest on a new line), which the probe must report by path, never
plaintext. There is NO snapshot or environment seam for the secret probe:
a command-level test proves the removed ``II_RECON_SECRETS_SNAPSHOT`` variable
has no effect on the fail-closed path, an in-process test proves the seam is
still not read AFTER a successful valid-baseline parse (Review 1 HIGH
remediation), and non-command-level tests exercise the secret probe
exclusively through direct pytest ``monkeypatch`` seams. Exactly ONE
dedicated canonical live-baseline evidence test runs the full command
against the real, protected canonical worktree; every other command-level
test uses an isolated, small synthetic baseline fixture (invalid or missing
JSON in a temporary directory) that fails closed before the live scan, so
the subprocess-, environment-ignore-, exception- and anti-masking semantics
stay genuinely exercised without re-scanning the whole worktree. There is
no session-scoped shared run: every command-level test owns its subprocess
runs, so no test order dependency exists. All fixtures are temporary files;
no network, no protected corpus mutation, no production write. The database
isolation tests prove the command never connects to or mutates any database
configured through ``DATABASE_URL``. The SOURCE_LOCK tests cover the
complete required top-level version-field set, and direct in-process probe
tests are isolated from ambient ``II_RECON_EXPECTED_*`` values.
"""

from __future__ import annotations

import copy
import hashlib
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
SOURCE_LOCK_PATH = PLATFORM_CORE / "SOURCE_LOCK.json"
REQUIRED_LOCK_VERSION_FIELDS = (
    "platform_version",
    "application_version",
    "partner_field_version",
    "commercial_integration_version",
)
# A reconciliation script által olvasott környezeti felülírás-kulcsok. A
# direct in-process probe tesztek ezeket mindig törlik, hogy ambient
# fejlesztői/CI értékek soha ne változtathassák meg a kanonikus várt
# értékeket (test-isolation, Review 1 LOW).
_II_RECON_EXPECTED_ENV_KEYS = (
    "II_RECON_EXPECTED_ALEMBIC_HEAD",
    "II_RECON_EXPECTED_PLATFORM_VERSION",
    "II_RECON_EXPECTED_APPLICATION_VERSION",
    "II_RECON_EXPECTED_PARTNER_FIELD_VERSION",
    "II_RECON_EXPECTED_COMMERCIAL_INTEGRATION_VERSION",
)
# A script pinelt defaultjai, exact a kanonikus SOURCE_LOCK.json ertekeivel.
# Deterministikus bizonyitek; a ket oldal csak egyutt, auditált commitban
# mozoghat, ezt a teszt kulon is vedi.
CANONICAL_PINNED_LOCK_VERSIONS = {
    "platform_version": "5.0.0",
    "application_version": "1.5.0",
    "partner_field_version": "1.0.0",
    "commercial_integration_version": "1.0.0",
}
sys.path.insert(0, str(SCRIPTS_DIR))

import check_secret_baseline  # noqa: E402


def _canonical_lock() -> dict:
    return json.loads(SOURCE_LOCK_PATH.read_text(encoding="utf-8"))


def _write_lock(tmp_path: Path, lock: dict) -> Path:
    synthetic = tmp_path / "synthetic-SOURCE_LOCK.json"
    synthetic.write_text(json.dumps(lock), encoding="utf-8")
    return synthetic


def _run_reconciliation(
    **env_overrides: str | None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for key in (
        "II_RECON_CORPUS_MANIFEST",
        "II_RECON_SECRETS_BASELINE",
        "II_RECON_SECRETS_SNAPSHOT",
        "II_RECON_SOURCE_LOCK",
        "II_RECON_EXPECTED_ALEMBIC_HEAD",
        "II_RECON_EXPECTED_PLATFORM_VERSION",
        "II_RECON_EXPECTED_APPLICATION_VERSION",
        "II_RECON_EXPECTED_PARTNER_FIELD_VERSION",
        "II_RECON_EXPECTED_COMMERCIAL_INTEGRATION_VERSION",
    ):
        env.pop(key, None)
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
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


def _load_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for key in _II_RECON_EXPECTED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    spec = importlib.util.spec_from_file_location("reconciliation_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_live_scan_document() -> dict:
    """Synthetic live-scan document for the tamper tests: exactly one known
    finding (a non-classifiable detector type) in one known source file.

    The tamper tests pin this document into the probe's live scan through
    the direct pytest seam, so the post-audited-state tamper proof never
    runs a real full-repo scan and no session-scoped fixture exists."""
    synthetic_hash = hashlib.sha1(b"synthetic-post-audit-candidate").hexdigest()
    return {
        "results": {
            "services/platform-core/app/seed.py": [
                {
                    "type": "Secret Keyword",
                    "hashed_secret": synthetic_hash,
                    "line_number": 1,
                }
            ]
        }
    }


def _pin_canonical_scan(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, document: dict
) -> None:
    """Direct pytest-bound seam: the probe's live scan returns the pinned document."""
    monkeypatch.setattr(
        module.check_secret_baseline,
        "_live_scan",
        lambda files, repo_root: document,
    )


def _find_live_finding(document: dict) -> tuple[str, int, dict]:
    for filename, findings in document.get("results", {}).items():
        for index, finding in enumerate(findings):
            if (
                check_secret_baseline._normalized_line_number(finding) is not None
                and str(finding.get("type", ""))
                not in check_secret_baseline._STRUCTURAL_CLASSIFIERS
            ):
                return filename, index, dict(finding)
    raise AssertionError("No live, unclassifiable finding found for the tamper test.")


def _assert_no_secret_material(baseline: dict, output: str) -> None:
    for findings in baseline.get("results", {}).values():
        for finding in findings:
            hashed_secret = finding.get("hashed_secret")
            if hashed_secret:
                assert str(hashed_secret) not in output


def test_reconciliation_command_passes_on_the_canonical_secret_baseline() -> None:
    # A védett, változatlan baseline-nal a titok-probe PASS: az occurrence-aware
    # egyeztetés az auditált repository-állapothoz horgonyzott, és minden más
    # probe is lefut (anti-masking). Ez az EGYETLEN dedikált canonical
    # live-baseline bizonyíték: a parancs a valódi, védett kanonikus
    # worktree-n fut -- seam nélkül, session-fixture nélkül.
    result = _run_reconciliation()
    assert result.returncode == 0, result.stderr
    assert "reconciliation PASS: tracked-secret baseline:" in result.stdout
    assert "reconciliation PASS: vedett acceptance corpusz" in result.stdout
    assert "reconciliation PASS: SOURCE_LOCK verziok rogzitve" in result.stdout
    assert "alembic_head 20260816_0072" in result.stdout
    assert "reconciliation PASS: modulregiszter" in result.stdout
    assert "reconciliation PASS: pontosan egy alembic head" in result.stdout
    # Minden probe PASS: az összegzés is a teljes lokális egyezést jelenti.
    assert "minden lokalis" in result.stdout


def _write_invalid_json_baseline(tmp_path: Path) -> Path:
    """Izolált, kis szintetikus baseline fixture: egy érvénytelen JSON fájl.

    A titok-probe fail-closed módon, az élő scan ELŐTT megáll rajta, így a
    parancsszintű szemantikai tesztek a teljes worktree újraszkennelése
    nélkül gyakorolják a subprocess-, anti-masking- és kivétel-útvonalakat.
    (A repository-gyökéren kívüli baseline fail-closed szemantikáját a
    test_secret_tracked_scan in-process tesztjei fedik le.)"""
    baseline = tmp_path / "invalid-baseline.json"
    baseline.write_text("{ this is not valid json", encoding="utf-8")
    return baseline


def test_secret_probe_failure_cannot_mask_the_other_probe_assertions(
    tmp_path: Path,
) -> None:
    """Anti-masking: ha a titok-probe elbukik (érvénytelen baseline), a másik
    négy probe akkor is lefut és PASS-t jelent (a Task31 hibája éppen a
    maszkolás volt)."""
    baseline = _write_invalid_json_baseline(tmp_path)
    result = _run_reconciliation(II_RECON_SECRETS_BASELINE=str(baseline))
    assert result.returncode != 0
    assert "repository baseline is not valid JSON" in result.stderr
    assert "reconciliation PASS: vedett acceptance corpusz" in result.stdout
    assert "reconciliation PASS: SOURCE_LOCK verziok rogzitve" in result.stdout
    assert "alembic_head 20260816_0072" in result.stdout
    assert "reconciliation PASS: modulregiszter" in result.stdout
    assert "reconciliation PASS: pontosan egy alembic head" in result.stdout
    assert "reconciliation FAIL: 1 probe(s) sikertelen" in result.stderr
    assert "minden lokalis" not in result.stdout


def test_command_level_snapshot_environment_variable_has_no_effect(
    tmp_path: Path,
) -> None:
    """Az eltávolított snapshot seam környezeti változóval sem éleszthető újra:
    a parancs két futása (a változóval és anélkül) byte-azonos kimenetet ad,
    tehát a parancsszintű kód a változót ténylegesen nem olvassa."""
    baseline = _write_invalid_json_baseline(tmp_path)
    plain = _run_reconciliation(II_RECON_SECRETS_BASELINE=str(baseline))
    result = _run_reconciliation(
        II_RECON_SECRETS_BASELINE=str(baseline),
        II_RECON_SECRETS_SNAPSHOT=str(tmp_path / "no-such-snapshot.json"),
        PYTEST_CURRENT_TEST="test_command_level_snapshot_environment_variable_has_no_effect",
    )
    assert result.returncode == plain.returncode != 0
    assert result.stdout == plain.stdout
    assert result.stderr == plain.stderr
    assert "unavailable outside pytest" not in result.stderr
    assert "repository baseline is not valid JSON" in result.stderr
    # A többi probe mindkét futásban lefut: a titok-probe hibája nem maszkol.
    assert "reconciliation PASS: vedett acceptance corpusz" in result.stdout
    assert "reconciliation FAIL: 1 probe(s) sikertelen" in result.stderr


def _write_valid_json_baseline(tmp_path: Path) -> Path:
    """Izolált, kis szintetikus baseline fixture: ÉRVÉNYES, üres JSON dokumentum.

    A titok-probe sikeresen átjut a baseline parse-on, a pinelt élő scan
    (direct pytest seam) üres eredménye pedig determinisztikus PASS-t ad --
    így a parse UTÁNI teljes egyeztetési kódút a valós
    ``reconcile_tracked_secrets`` logikával fut, teljes-repo scan nélkül
    (Review 1 HIGH: a seam-olvasás tilalmát valid baseline parse után is
    bizonyítani kell)."""
    baseline = tmp_path / "valid-baseline.json"
    baseline.write_text(json.dumps({"results": {}}), encoding="utf-8")
    return baseline


def test_snapshot_environment_seam_is_not_read_after_valid_baseline_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tiltott snapshot seam valid baseline parse UTÁN sem olvasható (Review 1 HIGH).

    A probe érvényes szintetikus baseline-nal és pinelt élő scannel átjut a
    parse-on, és sikeresen lefut (PASS, exit nélkül); a seam környezeti
    változóval és pytest-kontextussal megismételve a futás byte-azonos
    kimenetet ad. Ha a runtime a parse után bármikor olvasná az
    ``II_RECON_SECRETS_SNAPSHOT`` változót vagy a snapshot fájlt, a kimenet
    eltérne (a snapshot fájl szándékosan érvénytelen JSON, egyedi markerrel)."""
    baseline = _write_valid_json_baseline(tmp_path)
    snapshot = tmp_path / "synthetic-snapshot.json"
    snapshot.write_text("{ synthetic snapshot seam marker: 0x5EAM53 }", encoding="utf-8")

    def run_probe(with_seam_env: bool) -> str:
        module = _load_module(monkeypatch)
        monkeypatch.setattr(module, "SECRETS_BASELINE", baseline)
        _pin_canonical_scan(module, monkeypatch, {"results": {}})
        if with_seam_env:
            monkeypatch.setenv("II_RECON_SECRETS_SNAPSHOT", str(snapshot))
            monkeypatch.setenv(
                "PYTEST_CURRENT_TEST",
                "test_snapshot_environment_seam_is_not_read_after_valid_baseline_parse",
            )
        else:
            monkeypatch.delenv("II_RECON_SECRETS_SNAPSHOT", raising=False)
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        module._secret_baseline_probe()
        captured = capsys.readouterr()
        return captured.out

    plain = run_probe(with_seam_env=False)
    # A valid baseline parse sikeresen megtörtént, a probe PASS-szal lefutott.
    assert "reconciliation PASS: tracked-secret baseline:" in plain
    assert "0 tracked candidate(s) match the audited baseline" in plain
    with_seam = run_probe(with_seam_env=True)
    assert "reconciliation PASS: tracked-secret baseline:" in with_seam
    # A seam környezeti változó jelenléte a parse utáni futást nem változtatja.
    assert with_seam == plain
    # A snapshot fájl tartalma (érvénytelen JSON, egyedi marker) sosem kerül a kimenetbe.
    assert "0x5EAM53" not in plain
    assert "synthetic snapshot seam marker" not in with_seam


def test_unexpected_probe_exception_cannot_mask_the_other_probes(
    tmp_path: Path,
) -> None:
    """Egy váratlan kivétel is csak saját probe-ját buktatja: a többi probe
    lefut, és a jelentés csak a kivételosztályt közli (sosem a tartalmát).
    A titok-probe szintetikus érvénytelen baseline-nal fut (izolált, gyors
    fail-closed a scan előtt), hogy a kivétel-semantika a teljes worktree
    újraszkennelése nélkül maradjon bizonyított."""
    broken = tmp_path / "broken-manifest.json"
    broken.write_text("{ this is not valid json", encoding="utf-8")
    baseline = _write_invalid_json_baseline(tmp_path)
    result = _run_reconciliation(
        II_RECON_CORPUS_MANIFEST=str(broken),
        II_RECON_SECRETS_BASELINE=str(baseline),
    )
    assert result.returncode != 0
    assert "_corpus_probe varatlan hiba: JSONDecodeError" in result.stderr
    assert "this is not valid json" not in result.stderr
    # A titok-probe is lefut: saját hibája önállóan megjelenik (a corpusz
    # kivétele nem maszkolja, és nem is terjed rá).
    assert "repository baseline is not valid JSON" in result.stderr
    assert "reconciliation PASS: SOURCE_LOCK verziok rogzitve" in result.stdout
    assert "reconciliation PASS: modulregiszter" in result.stdout
    assert "reconciliation PASS: pontosan egy alembic head" in result.stdout
    assert "reconciliation FAIL: 2 probe(s) sikertelen" in result.stderr
    assert "minden lokalis" not in result.stdout


def test_corpus_probe_fail_closed_on_sha_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module(monkeypatch)
    manifest = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))
    tampered = {
        "schemaVersion": "2.1",
        "files": [{"path": manifest["files"][0]["path"], "sha256": "0" * 64}],
    }
    synthetic = tmp_path / "tampered-manifest.json"
    synthetic.write_text(json.dumps(tampered), encoding="utf-8")
    monkeypatch.setattr(module, "CORPUS_MANIFEST", synthetic)
    with pytest.raises(SystemExit) as excinfo:
        module._corpus_probe()
    assert excinfo.value.code not in (0, None)
    assert "corpusz-SHA elteres" in str(excinfo.value)


@pytest.mark.parametrize(
    "document, expected",
    [
        (
            {
                "schemaVersion": "2.1",
                "files": [{"path": "does/not/exist.txt", "sha256": "0" * 64}],
            },
            "vedett corpuszfajl hianyzik",
        ),
        ({"schemaVersion": "2.1", "files": []}, "files"),
    ],
    ids=["missing-corpus-file", "empty-files-list"],
)
def test_corpus_probe_fail_closed_on_invalid_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: dict, expected: str
) -> None:
    module = _load_module(monkeypatch)
    synthetic = tmp_path / "synthetic-manifest.json"
    synthetic.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(module, "CORPUS_MANIFEST", synthetic)
    with pytest.raises(SystemExit) as excinfo:
        module._corpus_probe()
    assert excinfo.value.code not in (0, None)
    assert expected in str(excinfo.value)


def test_reconciliation_fail_closed_on_missing_secret_baseline(
    tmp_path: Path,
) -> None:
    result = _run_reconciliation(II_RECON_SECRETS_BASELINE=str(tmp_path / "no-baseline.json"))
    assert result.returncode != 0
    assert "repository baseline is missing" in result.stderr


def _introduced_digest_tamper(document: dict) -> str:
    """Új digest az auditált állapot után egy ismert forrásfájlban."""
    filename = "services/platform-core/app/seed.py"
    synthetic_hash = hashlib.sha1(b"synthetic-post-audit-candidate").hexdigest()
    document["results"].setdefault(filename, []).append(
        {"type": "Hex High Entropy String", "hashed_secret": synthetic_hash, "line_number": 10**9}
    )
    return filename


def _duplicate_occurrence_tamper(document: dict) -> str:
    """Egy auditált digest új soron ismételt másolata."""
    filename, _, finding = _find_live_finding(document)
    duplicate = dict(finding)
    duplicate["line_number"] = 10**9
    document["results"][filename].append(duplicate)
    return filename


@pytest.mark.parametrize(
    "tamper",
    [_introduced_digest_tamper, _duplicate_occurrence_tamper],
    ids=["introduced-digest", "introduced-duplicate-occurrence"],
)
def test_secret_baseline_probe_fail_closed_on_post_audited_state_tamper(
    monkeypatch: pytest.MonkeyPatch, tamper
) -> None:
    """Az auditált állapot UTÁN bevezetett jelölt (új digest, vagy auditált
    digest új soron ismételt másolata) fail-closed: a probe plaintext nélkül,
    path szerint jelenti az unclassified találatot. Az élő scan egy
    szintetikus dokumentumba van pinelve (direct pytest seam), így a
    bizonyítás teljes-repo scan és session-fixture nélkül determinisztikus."""
    module = _load_module(monkeypatch)
    tampered = copy.deepcopy(_synthetic_live_scan_document())
    filename = tamper(tampered)
    _pin_canonical_scan(module, monkeypatch, tampered)
    with pytest.raises(SystemExit) as excinfo:
        module._secret_baseline_probe()
    assert excinfo.value.code not in (0, None)
    assert "unclassified candidate(s)" in str(excinfo.value)
    assert filename in str(excinfo.value)
    baseline = json.loads(SECRETS_BASELINE_PATH.read_text(encoding="utf-8"))
    _assert_no_secret_material(baseline, str(excinfo.value))


def test_secret_baseline_probe_maps_status_zero_to_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    monkeypatch.setattr(
        module.check_secret_baseline,
        "reconcile_tracked_secrets",
        lambda baseline_path, **kwargs: (
            0,
            "7 tracked candidate(s) match the audited baseline.",
        ),
    )
    module._secret_baseline_probe()


def test_secret_baseline_probe_maps_nonzero_to_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    monkeypatch.setattr(
        module.check_secret_baseline,
        "reconcile_tracked_secrets",
        lambda baseline_path, **kwargs: (
            1,
            "3 unclassified candidate(s) in 1 tracked file(s).\n- svc/synthetic.py",
        ),
    )
    with pytest.raises(SystemExit) as excinfo:
        module._secret_baseline_probe()
    assert excinfo.value.code not in (0, None)
    assert "reconciliation FAIL" in str(excinfo.value)


def test_source_lock_probe_fail_closed_on_head_tamper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module(monkeypatch)
    synthetic = tmp_path / "lock.json"
    synthetic.write_text(
        json.dumps(
            {
                "alembic_head": "99999999_9999",
                "platform_version": "5.0.0",
                "application_version": "1.5.0",
                "partner_field_version": "1.0.0",
                "commercial_integration_version": "1.0.0",
                "release_date": "2026-07-19",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "SOURCE_LOCK", synthetic)
    with pytest.raises(SystemExit) as excinfo:
        module._source_lock_probe()
    assert excinfo.value.code not in (0, None)
    assert "alembic_head" in str(excinfo.value)
    assert "elter a migracios graf fejetol" in str(excinfo.value)


def test_source_lock_probe_passes_on_canonical_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    monkeypatch.setattr(module, "SOURCE_LOCK", SOURCE_LOCK_PATH)
    module._source_lock_probe()  # a kanonikus lock ervenyes, nem dobhat.


def test_canonical_source_lock_matches_pinned_reconciliation_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Deterministikus bizonyitek: a kanonikus SOURCE_LOCK.json negy
    # top-level verzioerteke exact egyezik a script pinelt defaultjaival;
    # egyik oldal sem frissitheto neman, kulonben ez a teszt elbukik.
    module = _load_module(monkeypatch)
    assert module.EXPECTED_LOCK_VERSIONS == CANONICAL_PINNED_LOCK_VERSIONS
    lock = _canonical_lock()
    for field in REQUIRED_LOCK_VERSION_FIELDS:
        assert lock[field] == CANONICAL_PINNED_LOCK_VERSIONS[field]


def test_source_lock_probe_ignores_conflicting_ambient_expected_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ha a szulo kornyezet konfliktusos II_RECON_EXPECTED_* ertekeket
    # allit be, a direct probe akkor is a kanonikus pinelt defaultokat
    # hasznalja: a canonical lock validalasa PASS marad (Review 1 LOW).
    monkeypatch.setenv("II_RECON_EXPECTED_ALEMBIC_HEAD", "99999999_9999")
    for field in REQUIRED_LOCK_VERSION_FIELDS:
        monkeypatch.setenv(f"II_RECON_EXPECTED_{field.upper()}", "9.9.9")
    module = _load_module(monkeypatch)
    assert module.EXPECTED_LOCK_VERSIONS == CANONICAL_PINNED_LOCK_VERSIONS
    assert module.EXPECTED_HEAD == "20260816_0072"
    monkeypatch.setattr(module, "SOURCE_LOCK", SOURCE_LOCK_PATH)
    module._source_lock_probe()  # nem dobhat a konfliktusos ambient ellenere.


@pytest.mark.parametrize("field", REQUIRED_LOCK_VERSION_FIELDS)
@pytest.mark.parametrize(
    "mutate, mutation",
    [
        (lambda lock, field: lock.pop(field), "missing"),
        (lambda lock, field: lock.__setitem__(field, ""), "empty"),
        (lambda lock, field: lock.__setitem__(field, 1.0), "wrong-type"),
    ],
)
def test_source_lock_probe_fail_closed_on_invalid_version_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    mutate,
    mutation: str,
) -> None:
    module = _load_module(monkeypatch)
    lock = _canonical_lock()
    mutate(lock, field)
    monkeypatch.setattr(module, "SOURCE_LOCK", _write_lock(tmp_path, lock))
    with pytest.raises(SystemExit) as excinfo:
        module._source_lock_probe()
    assert excinfo.value.code not in (0, None)
    assert f"SOURCE_LOCK {field} ervenytelen" in str(excinfo.value)


@pytest.mark.parametrize("field", REQUIRED_LOCK_VERSION_FIELDS)
@pytest.mark.parametrize("malformed", ["1.0", "v1.0.0", "1.0.0-beta", " 1.0.0", "1.0.0 "])
def test_source_lock_probe_fail_closed_on_malformed_version_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    malformed: str,
) -> None:
    module = _load_module(monkeypatch)
    lock = _canonical_lock()
    lock[field] = malformed
    monkeypatch.setattr(module, "SOURCE_LOCK", _write_lock(tmp_path, lock))
    with pytest.raises(SystemExit) as excinfo:
        module._source_lock_probe()
    assert excinfo.value.code not in (0, None)
    assert f"SOURCE_LOCK {field} ervenytelen" in str(excinfo.value)


@pytest.mark.parametrize("field", REQUIRED_LOCK_VERSION_FIELDS)
def test_source_lock_probe_fail_closed_on_unexpected_version_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    module = _load_module(monkeypatch)
    lock = _canonical_lock()
    lock[field] = "9.9.9"
    monkeypatch.setattr(module, "SOURCE_LOCK", _write_lock(tmp_path, lock))
    with pytest.raises(SystemExit) as excinfo:
        module._source_lock_probe()
    assert excinfo.value.code not in (0, None)
    assert f"SOURCE_LOCK {field} elter a pinelt vart ertektol" in str(excinfo.value)


def test_migration_probe_fail_closed_on_wrong_alembic_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    monkeypatch.setattr(module, "EXPECTED_HEAD", "99999999_9999")
    with pytest.raises(SystemExit) as excinfo:
        module._migration_probe()
    assert excinfo.value.code not in (0, None)
    assert "alembic head" in str(excinfo.value)


def test_registry_probe_uses_private_engine_and_ignores_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "sentinel-production.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{sentinel.as_posix()}")
    module = _load_module(monkeypatch)
    assert not hasattr(module, "engine")
    assert not hasattr(module, "SessionLocal")
    module._registry_probe()
    assert not sentinel.exists()


def test_registry_probe_fail_closed_on_extra_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
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
