"""Focused Gate 8 reconciliation command tests.

Proves the configured reconciliation command evaluates every probe, and exits
nonzero (fail-closed) when a checked invariant is deliberately altered in a
temporary, synthetic context. The repository carries no committed secret
allowlist at all: candidates outside the protected ``.secrets.baseline`` are
cleared only by the scanner's structural classifiers (re-derived from the
working tree and proven against the scanner's own fingerprint), narrowed to
dedicated, provably static content-registry files and precise, non-generic
field names. The Task35 review remediation removed the executable
``app/seed.py`` and the generic ``sha256``/``checksum`` keys from that
allowlist, so the real content digests of ``seed.py``, ``SOURCE_LOCK.json``,
the operational process catalog and two ``manifest.json`` rows are now
*documented fail-closed* candidates: the tracked-secret probe reports them by
path (never plaintext) and exits nonzero until an R3 baseline attestation
covers them, while every other probe still evaluates and passes. The Task36
review remediation additionally made the audited identity occurrence-aware:
the comparison unit includes the finding line number, so a value baselined on
one line can no longer suppress a new occurrence of the same digest on a
different line. Against the *stale protected baseline* (whose rotation is a
separate R3 attestation and out of scope here) that strictly widens the
documented fail-closed set: values whose baseline lines no longer match the
working tree (line drift after the baseline was attested) are now reported
too, which is exactly the intended fail-closed behavior of the per-line
identity. There is NO
snapshot or environment seam for the secret probe: a
command-level test proves the ``II_RECON_SECRETS_SNAPSHOT`` variable (the
removed seam) has no effect, and non-command-level tests exercise the secret
probe exclusively through direct pytest ``monkeypatch`` seams (pytest-bound,
process-local). The baseline tamper tests compare against the live canonical
scan, pinned once per session. All fixtures are temporary files; no network,
no protected corpus mutation, no production write. The database isolation
tests prove the command never connects to or mutates any database configured
through ``DATABASE_URL``. The SOURCE_LOCK tests cover the complete required
top-level version-field set (platform/application/partner_field/
commercial_integration) with valid, missing, empty, wrong-type, malformed,
and unexpected/tampered values. Direct in-process probe tests are isolated
from ambient ``II_RECON_EXPECTED_*`` values: the module under test always
loads with the canonical pinned defaults, and a focused regression proves
canonical validation still passes when the parent environment holds
conflicting values.
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
SOURCE_LOCK_PATH = PLATFORM_CORE / "SOURCE_LOCK.json"
REQUIRED_LOCK_VERSION_FIELDS = (
    "platform_version",
    "application_version",
    "partner_field_version",
    "commercial_integration_version",
)
# A dokumentáltan fail-closed jelöltek: (1) a Task35 remediation óta a
# strukturális osztályozó által nem bizonyítható, baseline-hiányos valós
# tartalomdigestek (4 fájl), és (2) a Task36 remediation óta az
# occurrence-aware identitás miatt láthatóvá vált sor-eltolódások: a baseline
# ugyan hordozza a digestet, de a sor (path, type, hash, line) azonosság már
# nem egyezik a munkafával -- ezek az R3 baseline-attesztációig szintén
# osztályozatlanok maradnak. A védett baseline forgatása normál feladat
# részeként tilos, ezért a lista a jelenlegi dokumentált állapotot rögzíti.
_UNCLASSIFIED_CANDIDATE_FILES = (
    "services/operational-guidance/INTEGRATION-FILE-MANIFEST.json",
    "services/operational-guidance/config/operational-process-catalog-v1.0.json",
    "services/operational-guidance/config/website-targets.json",
    "services/operational-guidance/deploy/staging/staging.env.template",
    "services/operational-guidance/tests/test_brand_registry.py",
    "services/operational-guidance/tests/test_ingatlan_connector.py",
    "services/operational-guidance/tests/test_production_hardening.py",
    "services/platform-core/SOURCE_LOCK.json",
    "services/platform-core/app/seed.py",
    "services/platform-core/app/static/prevalidated-commercial-sources/manifest.json",
    "services/platform-core/docs/CANONICAL_SOURCE_VERIFICATION_COMMERCIAL_V1.json",
    "services/platform-core/tests/conftest.py",
    "services/platform-core/tests/test_canonical_sync_routes.py",
    "services/platform-core/tests/test_commercial_integration.py",
    "services/platform-core/tests/test_governance_workspace.py",
    "services/platform-core/tests/test_house_plan_execution.py",
    "services/platform-core/tests/test_market_service_api.py",
    "services/platform-core/tests/test_security.py",
    "services/platform-core/tests/test_user_administration.py",
    "services/platform-core/tests/test_website_content_control.py",
)
# A reconciliation script altal olvasott kornyezeti feluliras-kulcsok. A
# direct in-process probe tesztek ezeket mindig torlik, hogy ambient
# fejlesztoi/CI ertekek soha ne valtoztathassak meg a kanonikus vart
# ertekeket (test-isolation, Review 1 LOW).
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
    # Izolacio: minden direct probe-betoltes elott toroljuk az osszes
    # II_RECON_EXPECTED_* valtozot, igy a modul mindig a kanonikus pinelt
    # defaultokat latja, fuggetlenul a szulo kornyezettol.
    for key in _II_RECON_EXPECTED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    spec = importlib.util.spec_from_file_location("reconciliation_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def canonical_scan_document() -> dict:
    """Exactly one canonical tracked-secret scan per session.

    Both the tamper fingerprints and the direct monkeypatch seams derive from
    this single scan, so the pinned scanner runs once instead of once per
    consumer. The candidate set is derived and validated exactly as
    production does.
    """
    candidates = check_secret_baseline._validate_candidates(
        check_secret_baseline._git_tracked_candidates(REPO_ROOT, SECRETS_BASELINE_PATH),
        REPO_ROOT,
    )
    scannable, _ = check_secret_baseline._classify_candidates(candidates, REPO_ROOT)
    return check_secret_baseline._live_scan(scannable, REPO_ROOT)


@pytest.fixture(scope="session")
def live_secret_fingerprints(
    canonical_scan_document: dict,
) -> set[tuple[str, str, str, int | None]]:
    """Canonical tracked-secret fingerprints shared by the tamper tests.

    The identity is occurrence-aware: ``(path, type, fingerprint, line)``,
    exactly as ``reconcile_tracked_secrets`` compares baseline vs. live scan.
    """
    return check_secret_baseline._fingerprints(canonical_scan_document)


def _pin_canonical_scan(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, document: dict
) -> None:
    """Direct pytest-bound seam: the probe's live scan returns the pinned document.

    This is the only way the tests avoid a live scan: a process-local
    monkeypatch of the module-under-test's own reference, not an environment
    variable and not a command-level flag.
    """
    monkeypatch.setattr(
        module.check_secret_baseline,
        "_live_scan",
        lambda files, repo_root: document,
    )


def _find_live_baseline_entry(
    baseline: dict, live: set[tuple[str, str, str, int | None]]
) -> tuple[str, int, dict]:
    # Csak olyan bejegyzés alkalmas a tamper-tesztre, amely (a) valóban él a
    # live scanben (nem stale) az occurrence-aware (path, type, hash, line)
    # identitással, és (b) strukturálisan NEM osztályozható -- egy
    # content-digest/drive-id típusú bejegyzés eltávolítása után a klasszifikátor
    # tisztázná, és a probe tévesen PASS-t adna.
    for filename, findings in baseline.get("results", {}).items():
        for index, finding in enumerate(findings):
            fingerprint = (
                filename.replace("\\", "/"),
                str(finding.get("type", "")),
                str(finding.get("hashed_secret", "")),
                check_secret_baseline._normalized_line_number(finding),
            )
            if (
                fingerprint in live
                and str(finding.get("type", ""))
                not in check_secret_baseline._STRUCTURAL_CLASSIFIERS
            ):
                return filename, index, dict(finding)
    raise AssertionError("No live, unclassifiable baseline entry found for the tamper test.")


def _assert_no_secret_material(baseline: dict, output: str) -> None:
    for findings in baseline.get("results", {}).values():
        for finding in findings:
            hashed_secret = finding.get("hashed_secret")
            if hashed_secret:
                assert str(hashed_secret) not in output


def test_reconciliation_command_fails_closed_on_unclassified_digest_candidates() -> None:
    # A Task35 review-remediation óta a valós repó titok-probe-ja
    # dokumentáltan fail-closed: a strukturális osztályozó már nem ismer sem
    # futtatható forrást (app/seed.py), sem általános mezőneveket
    # (sha256/checksum), ezért a valós tartalomdigestek -- az R3
    # baseline-attesztációig -- osztályozatlanok maradnak. A Task36
    # remediation occurrence-aware identitása (sorszám a kulcsban) a védett,
    # de sor-eltolódott baseline mellett szigorúan bővíti a fail-closed
    # halmazt: a baseline-ban hordozott, de másik soron álló digestek is
    # osztályozatlanok, amíg az R3 attesztáció friss sorazonosítót nem ad.
    # A parancs pontosan ezeket a fájlokat nevezi meg (plaintext nélkül). Az
    # összesített kilépési kód nem nulla, a többi négy probe viszont lefut és
    # PASS-t jelent: egyetlen hiba sem takarhatja el a többiek állítását.
    result = _run_reconciliation()
    assert result.returncode != 0
    assert "236 unclassified candidate(s) in 20 tracked file(s)" in result.stderr
    for path in _UNCLASSIFIED_CANDIDATE_FILES:
        assert path in result.stderr
    assert "bounded hash/path-only audit report written to" in result.stderr
    assert "reconciliation FAIL: 1 probe(s) sikertelen" in result.stderr
    # A többi probe lefut és PASS-t jelent (anti-masking):
    assert "reconciliation PASS: vedett acceptance corpusz" in result.stdout
    assert "reconciliation PASS: SOURCE_LOCK verziok rogzitve" in result.stdout
    assert "alembic_head 20260816_0072" in result.stdout
    assert "reconciliation PASS: modulregiszter" in result.stdout
    assert "reconciliation PASS: pontosan egy alembic head" in result.stdout
    assert "minden lokalis" not in result.stdout


def test_secret_probe_failure_cannot_mask_the_other_probe_assertions(
    tmp_path: Path,
) -> None:
    """Anti-masking, synthetic and independent of the repository's delta.

    Task 31 failed because a platform-dependent secret scan aborted the run
    before the SOURCE_LOCK/alembic/registry/migration assertions were ever
    evaluated. Here the secret probe is forced to fail through the real live
    scan against an empty audited baseline; every other probe must still run
    and report.
    """
    baseline = tmp_path / "empty-baseline.json"
    baseline.write_text(json.dumps({"results": {}}), encoding="utf-8")
    result = _run_reconciliation(II_RECON_SECRETS_BASELINE=str(baseline))
    assert result.returncode != 0
    # A titok-probe elbukik, megnevezve, plaintext nelkul...
    assert "unclassified candidate(s)" in result.stderr
    # ...de a tobbi negy probe lefut es PASS-t jelent:
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
    """The removed snapshot seam cannot be re-enabled from the environment.

    Setting ``II_RECON_SECRETS_SNAPSHOT`` -- even next to the pytest marker
    -- must not change the command at all: the live scan still runs and the
    result is byte-identical to the no-override run (which is the documented
    fail-closed state on the unclassified digest candidates).
    """
    result = _run_reconciliation(
        II_RECON_SECRETS_SNAPSHOT=str(tmp_path / "no-such-snapshot.json"),
        PYTEST_CURRENT_TEST="test_command_level_snapshot_environment_variable_has_no_effect",
    )
    plain = _run_reconciliation()
    assert result.returncode != 0
    assert result.stdout == plain.stdout
    assert result.stderr == plain.stderr
    assert "unavailable outside pytest" not in result.stderr
    assert "unclassified candidate(s)" in result.stderr
    assert "minden lokalis" not in result.stdout


def test_unexpected_probe_exception_cannot_mask_the_other_probes(
    tmp_path: Path,
) -> None:
    """An unexpected exception is named, counted and never masks other probes.

    A malformed corpus manifest raises ``JSONDecodeError`` rather than a
    ``SystemExit``; the aggregate loop must still evaluate every remaining
    probe and must report only the exception class, never its message (which
    could echo file content).
    """
    broken = tmp_path / "broken-manifest.json"
    broken.write_text("{ this is not valid json", encoding="utf-8")
    result = _run_reconciliation(II_RECON_CORPUS_MANIFEST=str(broken))
    assert result.returncode != 0
    assert "_corpus_probe varatlan hiba: JSONDecodeError" in result.stderr
    assert "this is not valid json" not in result.stderr
    # A titok-probe is lefut: a dokumentált fail-closed állapotot jelenti az
    # osztályozatlan digestjelöltekre (nem maszkolódik el a corpuszhiba mögött).
    assert "unclassified candidate(s)" in result.stderr
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


def test_corpus_probe_fail_closed_on_missing_corpus_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module(monkeypatch)
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
    monkeypatch.setattr(module, "CORPUS_MANIFEST", synthetic)
    with pytest.raises(SystemExit) as excinfo:
        module._corpus_probe()
    assert excinfo.value.code not in (0, None)
    assert "vedett corpuszfajl hianyzik" in str(excinfo.value)


def test_corpus_probe_fail_closed_on_empty_files_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module(monkeypatch)
    synthetic = tmp_path / "empty-manifest.json"
    synthetic.write_text(json.dumps({"schemaVersion": "2.1", "files": []}), encoding="utf-8")
    monkeypatch.setattr(module, "CORPUS_MANIFEST", synthetic)
    with pytest.raises(SystemExit) as excinfo:
        module._corpus_probe()
    assert excinfo.value.code not in (0, None)
    assert "files" in str(excinfo.value)


def test_reconciliation_fail_closed_on_missing_secret_baseline(
    tmp_path: Path,
) -> None:
    result = _run_reconciliation(II_RECON_SECRETS_BASELINE=str(tmp_path / "no-baseline.json"))
    assert result.returncode != 0
    assert "repository baseline is missing" in result.stderr


def test_secret_baseline_probe_fail_closed_on_removed_baseline_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    canonical_scan_document: dict,
    live_secret_fingerprints: set[tuple[str, str, str]],
) -> None:
    module = _load_module(monkeypatch)
    _pin_canonical_scan(module, monkeypatch, canonical_scan_document)
    baseline = json.loads(SECRETS_BASELINE_PATH.read_text(encoding="utf-8"))
    filename, index, _ = _find_live_baseline_entry(baseline, live_secret_fingerprints)
    baseline["results"][filename].pop(index)
    if not baseline["results"][filename]:
        baseline["results"].pop(filename)
    synthetic = tmp_path / "removed-entry-baseline.json"
    synthetic.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(module, "SECRETS_BASELINE", synthetic)
    with pytest.raises(SystemExit) as excinfo:
        module._secret_baseline_probe()
    assert excinfo.value.code not in (0, None)
    assert "unclassified candidate(s)" in str(excinfo.value)
    _assert_no_secret_material(baseline, str(excinfo.value))


def test_secret_baseline_probe_fail_closed_on_changed_baseline_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    canonical_scan_document: dict,
    live_secret_fingerprints: set[tuple[str, str, str]],
) -> None:
    module = _load_module(monkeypatch)
    _pin_canonical_scan(module, monkeypatch, canonical_scan_document)
    baseline = json.loads(SECRETS_BASELINE_PATH.read_text(encoding="utf-8"))
    filename, index, finding = _find_live_baseline_entry(baseline, live_secret_fingerprints)
    finding["hashed_secret"] = "0" * 40
    baseline["results"][filename][index] = finding
    synthetic = tmp_path / "changed-entry-baseline.json"
    synthetic.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(module, "SECRETS_BASELINE", synthetic)
    with pytest.raises(SystemExit) as excinfo:
        module._secret_baseline_probe()
    assert excinfo.value.code not in (0, None)
    assert "unclassified candidate(s)" in str(excinfo.value)
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
def test_source_lock_probe_fail_closed_on_missing_version_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    module = _load_module(monkeypatch)
    lock = _canonical_lock()
    lock.pop(field)
    monkeypatch.setattr(module, "SOURCE_LOCK", _write_lock(tmp_path, lock))
    with pytest.raises(SystemExit) as excinfo:
        module._source_lock_probe()
    assert excinfo.value.code not in (0, None)
    assert f"SOURCE_LOCK {field} ervenytelen" in str(excinfo.value)


@pytest.mark.parametrize("field", REQUIRED_LOCK_VERSION_FIELDS)
def test_source_lock_probe_fail_closed_on_empty_version_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    module = _load_module(monkeypatch)
    lock = _canonical_lock()
    lock[field] = ""
    monkeypatch.setattr(module, "SOURCE_LOCK", _write_lock(tmp_path, lock))
    with pytest.raises(SystemExit) as excinfo:
        module._source_lock_probe()
    assert excinfo.value.code not in (0, None)
    assert f"SOURCE_LOCK {field} ervenytelen" in str(excinfo.value)


@pytest.mark.parametrize("field", REQUIRED_LOCK_VERSION_FIELDS)
def test_source_lock_probe_fail_closed_on_wrong_type_version_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    module = _load_module(monkeypatch)
    lock = _canonical_lock()
    lock[field] = 1.0
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
