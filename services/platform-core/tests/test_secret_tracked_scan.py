"""Cross-platform regression tests for the canonical tracked-secret scan.

Covers the tracked-file contract of ``check_secret_baseline.py``: only
Git-tracked regular files are candidates; decoding is identical on every
host locale (the Task 31 cp1250/UTF-8 divergence); every candidate is
accounted for (scanned or scanner-exempt); the audit artifact is write-only
evidence; the audited state is anchored to git history (unchanged repeats
and line drift reconcile, post-audited-state values fail closed unless a
structural classifier proves them on their exact line); the audited
identity is occurrence-aware and content-bearing, and U+2028/U+2029 line
separators never shift scanner versus classifier numbering; git/driver
failure, malformed output, duplicate/ambiguous paths and driver output
outside the canonical set fail closed (status 2), with the documented
bounded Windows transient-start retry only. All synthetic values are
assembled at runtime from non-secret-looking fragments; fixtures are
temporary synthetic git repositories; no network, no production write.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from detect_secrets.settings import default_settings

PLATFORM_CORE = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLATFORM_CORE / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _detect_secrets_scan_driver  # noqa: E402
import check_secret_baseline  # noqa: E402

REPO_ROOT = check_secret_baseline.REPO_ROOT

# These fixtures are assembled at runtime from short fragments so that no
# secret-like plaintext literal exists in this file, and so the committed
# source cannot trip generic credential-pattern scanners itself.
_SYNTHETIC_VALUE = "Synthetic" + "PlaintextValue" + "-1234567890-ABC"
# A hozzárendelési kulcsszó futásidőben áll össze, hogy a committed tesztforrás
# se hordozzon credential-hozzárendelési literált (Task44 Gate 5 regressziós őr).
_ASSIGNMENT_KEY = "pass" + "word"
PASSWORD_LINE = _ASSIGNMENT_KEY + " = '" + _SYNTHETIC_VALUE + "'\n"
_SIGNATURE_HEX = hashlib.md5(b"synthetic-signature-hex-probe").hexdigest()
HEX_LINE = 'SIGNATURE = "' + _SIGNATURE_HEX + '"\n'
# "ELŐKÉSZÍTÉS": U+0150 encodes to C5 90 in UTF-8, and byte 0x90 is undefined
# in cp1250. A bare locale-encoding ``open()`` therefore raises on a Hungarian
# Windows host and the pinned scanner silently drops the whole file, while a
# UTF-8 Linux runner scans it -- the exact Task 31 divergence.
_CP1250_HOSTILE_LINE = "# ELŐKÉSZÍTÉS (synthetic)\n"

# A strukturális osztályozók dokumentált, exact útvonalkontextusa: a szintetikus
# repókban ugyanezen relatív utak alatt jönnek létre a tartalomregiszter- és
# Drive-index fájlok, így a path-szűkítés maga is tesztelhető.
_DIGEST_MANIFEST_PATH = (
    "services/platform-core/app/static/prevalidated-commercial-sources/manifest.json"
)
_DRIVE_TEMPLATES_PATH = "services/platform-core/app/canonical_documents/templates.json"
_DRIVE_ARTIFACTS_PATH = "sites/_portal/data/artifacts.json"


def _git(repo: Path, *args: str, input_text: str | None = None) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=str(repo),
        input=input_text,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Synthetic Test")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    return repo


def _commit(repo: Path, message: str = "synthetic commit") -> None:
    _git(repo, "commit", "-q", "-m", message)


def _tracked_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Egy ártalmatlan tracked.py-val és üres baseline-nal commitolt szintetikus repó."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
    return repo, baseline


def _write_tracked(repo: Path, relative_path: str, content: str) -> Path:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _empty_baseline(repo: Path, name: str = "synthetic-baseline.json") -> Path:
    baseline = repo / name
    baseline.write_text(json.dumps({"results": {}}), encoding="utf-8")
    return baseline


def _expected_probe_entry() -> dict:
    expected_type, expected_hash, expected_line = check_secret_baseline._expected_probe_fingerprint()
    return {
        "type": expected_type,
        "hashed_secret": expected_hash,
        "line_number": expected_line,
    }


def _driver_fake(
    returncode: int = 0,
    payload: dict | None = None,
    include_probe: bool = True,
    skip_accounting: set[str] | None = None,
):
    """Canned ``_run_driver_scan`` that satisfies the sentinel probe contract."""

    def _fake(files: list[str], repo_root: Path) -> subprocess.CompletedProcess[bytes]:
        results = dict(payload or {})
        # Probes are identified by basename: they live in the per-run
        # runtime subdirectory, so their full path no longer starts with
        # the prefix, exactly like the module's own detection contract.
        probe_names = [
            name
            for name in files
            if Path(name).name.startswith(check_secret_baseline._PROBE_PREFIX)
        ]
        if include_probe:
            for probe_name in probe_names:
                results[probe_name] = [_expected_probe_entry()]
        accounted = [
            f"[scan]\tINFO\t{check_secret_baseline._CHECKING_FILE_PREFIX}{name}"
            for name in files
            if Path(name).name not in {Path(probe).name for probe in probe_names}
            and name not in (skip_accounting or set())
        ]
        stdout = json.dumps({"results": results}).encode("utf-8")
        stderr = ("\n".join(accounted) + "\n").encode("utf-8")
        return subprocess.CompletedProcess(
            args=["scan-driver"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return _fake


def test_candidate_set_contains_only_tracked_regular_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    (repo / "script.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    _git(repo, "add", "tracked.py", "script.sh")
    _git(repo, "update-index", "--chmod=+x", "script.sh")
    (repo / "untracked.py").write_text(PASSWORD_LINE, encoding="utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "out.py").write_text(HEX_LINE, encoding="utf-8")
    blob_sha = _git(repo, "hash-object", "-w", "--stdin", input_text="target/path\n").strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob_sha},link_name")
    (repo / "link_name").write_text("target/path\n", encoding="utf-8")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{blob_sha},submodule_dir")
    baseline = _empty_baseline(repo)
    _git(repo, "add", baseline.name)
    _commit(repo)

    candidates = check_secret_baseline._git_tracked_candidates(repo, baseline)
    assert candidates == ["script.sh", "tracked.py"]
    tracked = _git(repo, "ls-files").splitlines()
    assert set(tracked) - set(candidates) == {
        baseline.name,
        "link_name",
        "submodule_dir",
    }


def test_tab_in_git_ls_files_record_parses_safely() -> None:
    """A tab inside a filename survives ``-s -z`` parsing intact."""
    raw = (
        b"100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0\ttab\tname.py\0"
        b"100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0\tplain.py\0"
    )
    assert check_secret_baseline._parse_git_ls_files(raw) == [
        "tab\tname.py",
        "plain.py",
    ]


def test_unreadable_candidate_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate that cannot be read is unaccountable, so it fails closed."""
    repo, baseline = _tracked_repo(tmp_path)

    def _unreadable(target: Path) -> bytes:
        raise OSError("synthetic unreadable candidate")

    monkeypatch.setattr(check_secret_baseline, "_read_candidate_bytes", _unreadable)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "cannot be read" in message


@pytest.mark.parametrize(
    "record, expected",
    [
        (b"100700 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391\tx.py\0", "unexpected git index entry mode"),
        (b"100644 not-a-sha1\tx.py\0", "malformed git ls-files record"),
    ],
    ids=["unknown-mode", "malformed-record"],
)
def test_invalid_index_record_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record: bytes,
    expected: str,
) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline, "_run_git_ls_files", lambda repo_root: record
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert expected in message


def test_fingerprint_normalization_matches_windows_and_posix_separators() -> None:
    finding = {"type": "Secret Keyword", "hashed_secret": "0" * 40, "line_number": 7}
    windows = check_secret_baseline._fingerprints(
        {"results": {"services\\platform-core\\tests\\x.py": [finding]}}
    )
    posix = check_secret_baseline._fingerprints(
        {"results": {"services/platform-core/tests/x.py": [finding]}}
    )
    assert windows == posix
    assert windows == {("services/platform-core/tests/x.py", "Secret Keyword", "0" * 40, 7)}
    # Sorszám nélküli találat ``None``-ra normalizálódik: soha nem egyezhet
    # meg egy valódi sorszámú élő találattal, így fail-closed marad.
    without_line = dict(finding)
    without_line.pop("line_number")
    assert check_secret_baseline._fingerprints(
        {"results": {"services/platform-core/tests/x.py": [without_line]}}
    ) == {("services/platform-core/tests/x.py", "Secret Keyword", "0" * 40, None)}


def test_untracked_build_cache_and_runtime_files_cannot_influence_reconciliation(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic, no secrets\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
    (repo / "untracked.py").write_text(PASSWORD_LINE, encoding="utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "out.py").write_text(HEX_LINE, encoding="utf-8")
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "CACHEDIR.TAG").write_text(HEX_LINE, encoding="utf-8")
    (repo / "runtime").mkdir()
    (repo / "runtime" / "manifest.json").write_text(PASSWORD_LINE, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "0 tracked candidate(s) match the audited baseline." in message

    # A runtime-jelölt tracked-re emelése (az audited commit UTÁN, csak az
    # indexben) azonnal megjelenik — fail-closed, plaintext nélkül,
    # hash/path-only audit-artefaktummal:
    _git(repo, "add", "runtime/manifest.json")
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1
    assert "- runtime/manifest.json" in message
    assert _SYNTHETIC_VALUE not in message
    assert "untracked.py" not in message
    assert "build/out.py" not in message
    assert ".pytest_cache" not in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    assert "bounded hash/path-only audit report written to" in message
    assert audit.is_file()
    document = json.loads(audit.read_text(encoding="utf-8"))
    rows = document["rows"]
    assert {row["path"] for row in rows} == {"runtime/manifest.json"}
    assert all(row["classification"] == "unclassified" for row in rows)
    assert {row["type"] for row in rows} == {
        "Secret Keyword",
        "Base64 High Entropy String",
    }
    fingerprint = hashlib.sha1(_SYNTHETIC_VALUE.encode("utf-8")).hexdigest()
    assert all(row["hashes"] == [fingerprint] for row in rows)
    # A sorszám az occurrence-aware identitás része, ezért az audit sorai is
    # hordozzák; a sorok kizárólag path/type/classification/count/hash/line
    # mezőket hordozhatnak: bármely további kulcs plaintext szivárgás
    # kockázata lenne.
    assert all(
        set(row)
        <= {
            "path",
            "type",
            "classification",
            "findingCount",
            "hashes",
            "lineNumbers",
            "hashesOmitted",
        }
        for row in rows
    )
    assert all(row["lineNumbers"] == [1] for row in rows)
    assert all(row["findingCount"] == 1 for row in rows)
    assert _SYNTHETIC_VALUE not in audit.read_text(encoding="utf-8")


def test_baseline_file_excluded_exactly(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic, no secrets\n", encoding="utf-8")
    baseline = repo / "synthetic-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "results": {},
                "note": PASSWORD_LINE.strip(),
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)

    candidates = check_secret_baseline._git_tracked_candidates(repo, baseline)
    assert candidates == ["tracked.py"]
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "synthetic-baseline.json" not in message
    assert _SYNTHETIC_VALUE not in message


def test_new_tracked_candidate_fails_closed_without_revealing_plaintext(
    tmp_path: Path,
) -> None:
    """A candidate introduced after the audited state fails closed, plaintext-free."""
    repo, baseline = _tracked_repo(tmp_path)
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1
    assert "- tracked.py" in message
    assert _SYNTHETIC_VALUE not in message
    hashed = hashlib.sha1(_SYNTHETIC_VALUE.encode("utf-8")).hexdigest()
    assert hashed not in message


def test_cp1250_undecodable_tracked_file_is_still_scanned(tmp_path: Path) -> None:
    """A Hungarian UTF-8 file must not be skipped on a cp1250 host."""
    payload = _CP1250_HOSTILE_LINE + HEX_LINE
    raw = payload.encode("utf-8")
    # A fixture csak akkor bizonyít, ha tényleg cp1250-ellenálló:
    assert b"\xc5\x90" in raw
    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp1250")
    assert raw.decode("utf-8") == payload

    repo = _init_repo(tmp_path / "repo")
    # ASCII kontroll ugyanazzal a jelölttel: minden locale alatt detektálható,
    # így a teszt a dekódolást méri, nem a detektor hiányát. Mindkét jelölt az
    # audited commit UTÁN kerül a munkafába (a commit csak ártalmatlan
    # tartalmat hordoz), hogy az élő scannek addition-ként kelljen látnia őket.
    (repo / "ascii_control.py").write_text("# synthetic\n", encoding="utf-8")
    (repo / "hungarian.py").write_bytes(b"# synthetic\n")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "ascii_control.py", "hungarian.py", baseline.name)
    _commit(repo)
    (repo / "ascii_control.py").write_text(HEX_LINE, encoding="utf-8")
    (repo / "hungarian.py").write_bytes(raw)

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "- ascii_control.py" in message, "a kontroll jelölt nem detektálható"
    assert "- hungarian.py" in message, (
        "a cp1250-ellenálló fájlt a scanner kihagyta (dekódolási regresszió)"
    )
    assert "2 unclassified candidate(s) in 2 tracked file(s)" in message
    hashed = hashlib.sha1(_SIGNATURE_HEX.encode("utf-8")).hexdigest()
    assert hashed not in message


def test_driver_scan_pins_utf8_environment_and_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scanner subprocess gets the pinned decoding env and documented args."""
    captured: dict[str, str] = {}
    captured_calls: list[dict] = []

    def _capture(args, **kwargs):
        captured_calls.append(
            {
                "args": list(args),
                "input": kwargs["input"],
                "cwd": kwargs["cwd"],
            }
        )
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(
            args=["scan-driver"],
            returncode=0,
            stdout=b'{"results": {}}',
            stderr=(
                b"[scan]\tINFO\t"
                + check_secret_baseline._CHECKING_FILE_PREFIX.encode("utf-8")
                + b"tracked.py\n"
            ),
        )

    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1250")
    monkeypatch.setattr(check_secret_baseline.subprocess, "run", _capture)
    check_secret_baseline._run_driver_scan(["tracked.py"], check_secret_baseline.REPO_ROOT)
    assert captured["PYTHONUTF8"] == "1"
    assert captured["PYTHONIOENCODING"] == "utf-8"
    call = captured_calls[0]
    assert call["args"] == [sys.executable, str(check_secret_baseline._DRIVER_PATH)]
    assert call["cwd"] == str(check_secret_baseline.REPO_ROOT)
    assert call["input"].decode("utf-8") == "tracked.py\n"


def test_scanner_version_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(check_secret_baseline.metadata, "version", lambda _name: "1.4.0")
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "is not the pinned 1.5.0" in message


def test_missing_scanner_distribution_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)

    def _absent(_name: str) -> str:
        raise check_secret_baseline.metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(check_secret_baseline.metadata, "version", _absent)
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "is not installed" in message


def test_pinned_scanner_version_matches_requirements() -> None:
    """The pinned constant and requirements-dev.txt cannot drift apart."""
    requirements = (PLATFORM_CORE / "requirements-dev.txt").read_text(encoding="utf-8")
    expected = (
        f"{check_secret_baseline._SCANNER_DISTRIBUTION}=="
        f"{check_secret_baseline._PINNED_SCANNER_VERSION}"
    )
    assert expected in requirements


def test_scanner_failure_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _driver_fake(returncode=1))
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "scan driver exit code 1" in message


def test_malformed_scanner_output_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)

    def _broken(files, repo_root):
        return subprocess.CompletedProcess(
            args=["scan-driver"], returncode=0, stdout=b"not json", stderr=b""
        )

    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _broken)
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "scan driver output is not valid JSON" in message


def test_git_failure_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _empty_baseline(tmp_path)

    def _broken_ls_files(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "git ls-files")

    monkeypatch.setattr(check_secret_baseline.subprocess, "check_output", _broken_ls_files)
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "git ls-files failed" in message


def test_missing_tracked_candidate_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline,
        "_git_tracked_candidates",
        lambda repo_root, baseline_path: ["does/not/exist.txt"],
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "missing or non-regular" in message


def test_duplicate_normalized_paths_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline,
        "_git_tracked_candidates",
        lambda repo_root, baseline_path: [
            "services/platform-core/app/seed.py",
            "services\\platform-core\\app\\seed.py",
        ],
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "duplicate tracked paths" in message


def test_case_ambiguity_check_is_platform_dependent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Két út, amelyek casefold-ja ütközik: Windows-on (case-insensitive)
    # determinisztikusan fail-closed, Linuxon (case-sensitive) legális pár.
    paths = ["a/Module.py", "A/module.py"]
    monkeypatch.setattr(check_secret_baseline, "_is_case_insensitive_platform", lambda: True)
    with pytest.raises(check_secret_baseline.ScanFailure, match="differing only by case"):
        check_secret_baseline._validate_candidate_names(paths)
    monkeypatch.setattr(check_secret_baseline, "_is_case_insensitive_platform", lambda: False)
    check_secret_baseline._validate_candidate_names(paths)


def test_case_ambiguous_paths_fail_closed_on_case_insensitive_platforms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline,
        "_git_tracked_candidates",
        lambda repo_root, baseline_path: ["Module.py", "module.py"],
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    if check_secret_baseline._is_case_insensitive_platform():
        assert "differing only by case" in message
    else:
        # Case-sensitive platform (Linux): legal paths, so validation proceeds
        # to the on-disk check and fails for a different, deterministic reason.
        assert "differing only by case" not in message


def test_scanner_output_outside_canonical_set_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, baseline = _tracked_repo(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline,
        "_run_driver_scan",
        _driver_fake(payload={"evil/outside.py": [{"type": "t", "hashed_secret": "0" * 40}]}),
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "outside the canonical tracked set" in message


def test_missing_sentinel_probe_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chunk whose probe never comes back is an unaccounted scanner run."""
    repo, baseline = _tracked_repo(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline, "_run_driver_scan", _driver_fake(include_probe=False)
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "sentinel probe was not detected" in message


def test_live_scan_feeds_exactly_the_bounded_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact bounded set: every requested path is fed exactly once, in
    bounded chunks, and every chunk carries exactly this process's own
    sentinel probe -- a parallel or earlier scan's probe file can never
    enter the exact-set input. The set comparison is order-insensitive,
    because chunk completion order on the worker pool is not a security
    property; the exact-set and per-chunk coverage accounting are enforced
    fail-closed inside ``_scan_file_set`` itself."""
    fed: list[list[str]] = []
    files = [f"services/platform-core/f{f:04d}.py" for f in range(250)]
    probe_prefix = check_secret_baseline._PROBE_PREFIX

    def _recording_driver(chunk: list[str], repo_root: Path) -> subprocess.CompletedProcess[bytes]:
        fed.append(list(chunk))
        return _driver_fake()(chunk, repo_root)

    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _recording_driver)
    result = check_secret_baseline._live_scan(files, check_secret_baseline.REPO_ROOT)
    assert result == {"results": {}}
    fed_paths = sorted(
        path
        for chunk in fed
        for path in chunk
        if not Path(path).name.startswith(probe_prefix)
    )
    assert fed_paths == files
    assert all(len(chunk) < len(files) for chunk in fed)
    # Probe isolation: exactly one probe per chunk, and the probe set is
    # exactly this process's own per-chunk basenames.
    expected_probes = {
        check_secret_baseline._probe_basename(index) for index in range(len(fed))
    }
    seen_probes: set[str] = set()
    for chunk in fed:
        probes = [path for path in chunk if Path(path).name.startswith(probe_prefix)]
        assert len(probes) == 1
        seen_probes.add(Path(probes[0]).name)
    assert seen_probes == expected_probes


def test_reconcile_has_no_snapshot_or_environment_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No command-level snapshot seam and no env-toggled bypass exists."""
    parameters = inspect.signature(check_secret_baseline.reconcile_tracked_secrets).parameters
    assert set(parameters) == {"baseline_path", "repo_root"}

    repo, baseline = _tracked_repo(tmp_path)

    calls: list[int] = []

    def _counting_driver(files: list[str], repo_root: Path) -> subprocess.CompletedProcess[bytes]:
        calls.append(1)
        return _driver_fake()(files, repo_root)

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_reconcile_has_no_snapshot_or_environment_seam")
    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _counting_driver)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert calls, "az élő scan lefutott: a környezeti változó nem kapcsol ki semmit"


def test_readable_file_the_scanner_skips_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A readable, UTF-8-decodable file the scanner never opens fails closed."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    (repo / "readable_but_skipped.py").write_text("# synthetic, readable\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", "readable_but_skipped.py", baseline.name)
    _commit(repo)

    monkeypatch.setattr(
        check_secret_baseline,
        "_run_driver_scan",
        _driver_fake(skip_accounting={"readable_but_skipped.py"}),
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "scanner did not account for requested file(s)" in message
    assert "readable_but_skipped.py" in message
    assert "tracked.py" not in message


def test_probe_write_error_fails_closed_and_leaves_no_probe_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe write failure is a controlled fail-closed error with cleanup."""
    repo, baseline = _tracked_repo(tmp_path)

    original_write = Path.write_text

    def _refuse_probe_write(self: Path, *args, **kwargs) -> None:
        if self.name.startswith(check_secret_baseline._PROBE_PREFIX):
            raise OSError("synthetic probe write failure")
        original_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _refuse_probe_write)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "sentinel probe could not be written" in message
    assert list(repo.glob(check_secret_baseline._PROBE_PREFIX + "*")) == []
    # The failed run leaves no probe remnant in its private runtime tree either.
    probe_root = repo.joinpath(*check_secret_baseline._PROBE_RELATIVE_DIR)
    assert not probe_root.exists() or list(probe_root.iterdir()) == []


def test_probe_delete_error_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A probe that cannot be removed is a controlled fail-closed error."""
    repo, baseline = _tracked_repo(tmp_path)

    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _driver_fake())
    original_unlink = Path.unlink

    def _refuse_probe_unlink(self: Path, *args, **kwargs) -> None:
        if self.name.startswith(check_secret_baseline._PROBE_PREFIX):
            raise OSError("synthetic probe delete failure")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _refuse_probe_unlink)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "sentinel probe could not be removed" in message


def test_separator_probe_text_carries_separators_and_models_line_two() -> None:
    """Az U+2028/U+2029-tartalmú szentinel probe a titkot a 2. sorra helyezi a
    universal-newline modell szerint; a splitlines() modell mindkét separatornál
    tördelne (4. sorra tolva a titkot) -- a probe a két modell közötti eltérést
    minden futásban érzékeli."""
    text = check_secret_baseline._probe_text()
    assert check_secret_baseline._UNICODE_LINE_SEPARATOR in text
    assert check_secret_baseline._UNICODE_PARAGRAPH_SEPARATOR in text
    lines = check_secret_baseline._universal_newline_lines(text)
    assert len(lines) == 2
    assert check_secret_baseline._probe_secret_value() in lines[1]
    assert check_secret_baseline._expected_probe_line_number() == 2
    splitlines_model = text.splitlines()
    secret_on_splitlines_line = next(
        index
        for index, line in enumerate(splitlines_model, start=1)
        if check_secret_baseline._probe_secret_value() in line
    )
    assert secret_on_splitlines_line == 4, "a splitlines() modell eltérése nélkül a probe nem őrködik"


def test_separator_probe_line_identity_matches_real_driver(tmp_path: Path) -> None:
    """A valódi pinned driver ugyanazon a sorszámon jelenti a probe titkát,
    mint az ``_expected_probe_line_number`` -- a live parity ellenőrzés
    közvetlen bizonyítéka (nem csak a fake kontraktus)."""
    repo = _init_repo(tmp_path / "repo")
    probe = repo / "probe-parity.txt"
    probe.write_text(check_secret_baseline._probe_text(), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "_detect_secrets_scan_driver.py")],
        cwd=str(repo),
        input="probe-parity.txt\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    findings = json.loads(completed.stdout)["results"]["probe-parity.txt"]
    reported_lines = [
        finding["line_number"]
        for finding in findings
        if finding["type"] == "Secret Keyword"
        and finding["hashed_secret"]
        == check_secret_baseline._expected_probe_fingerprint()[1]
    ]
    assert reported_lines == [check_secret_baseline._expected_probe_line_number()]


def test_probe_source_carries_no_credential_assignment_literal() -> None:
    """Task44 regressziós őr: a scanner és saját tesztjeinek committed forrása
    nem tartalmaz credential-hozzárendelési literált -- sem a determinisztikus
    Gate 5 credential-mintát, sem jelszó-hozzárendelési literált --, miközben a
    futásidejű szentinel probe megtartja a detektálandó hozzárendelést. A kettő
    együtt bizonyítja, hogy az önellenőrzés valódi maradt, a forrás tiszta."""
    credential_pattern = re.compile(
        r"(?i)(api[_-]?key|secret|token|password|passwd|private[_-]?key)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-\./+=]{16,}"
    )
    exclusion = re.compile(
        r"(?i)(example|placeholder|dummy|changeme|your[_-]|<[^>]+>|"
        r"process\.env|os\.environ|environment|getenv)"
    )
    assignment_literal = re.compile(r"(?i)password\s*[:=]")
    for path in (SCRIPTS_DIR / "check_secret_baseline.py", Path(__file__)):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not (credential_pattern.search(line) and not exclusion.search(line)), (
                f"credential-pattern literal in {path.name} line {number}"
            )
            assert not assignment_literal.search(line), (
                f"credential-assignment literal in {path.name} line {number}"
            )
    runtime_probe = check_secret_baseline._probe_text()
    assert assignment_literal.search(runtime_probe), (
        "a futásidejű probe elvesztette a detektálandó hozzárendelést"
    )


def test_real_probe_run_leaves_no_scratch_file(tmp_path: Path) -> None:
    """A valódi pinned driverrel lefutott szentinel probe észlelődik és nyom
    nélkül távozik: a scan végén egyetlen ``.secrets-scan-probe-*`` fájl sem
    marad a repositoryban. A sikeres scan maga bizonyítja az észlelést, mert
    a hiányzó probe-finding minden futásban fail-closed (status 2)."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")
    _git(repo, "add", "tracked.py")
    _commit(repo)
    result = check_secret_baseline._live_scan(["tracked.py"], repo)
    assert "tracked.py" in result["results"]
    assert list(repo.glob(check_secret_baseline._PROBE_PREFIX + "*")) == []
    # A sikeres scan a privát probe-könyvtárat is nyom nélkül hagyja.
    probe_root = repo.joinpath(*check_secret_baseline._PROBE_RELATIVE_DIR)
    assert not probe_root.exists() or list(probe_root.iterdir()) == []


def test_scanner_exempt_candidates_are_accounted_deterministically(
    tmp_path: Path,
) -> None:
    """Files the pinned scanner exempts by design must be accounted, not silent."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    (repo / "data.blob").write_bytes(b"\x00\x01\x02\xff\xfe\x89\x90 binary")
    (repo / "style.css").write_text(PASSWORD_LINE, encoding="utf-8")
    (repo / "package-lock.json").write_text(
        '{"name": "synthetic", "lockfileVersion": 3}\n', encoding="utf-8"
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "swagger.json").write_text(PASSWORD_LINE, encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", "data.blob", "style.css", "package-lock.json", baseline.name)
    _git(repo, "add", "docs/swagger.json")
    _commit(repo)

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "4 tracked candidate file(s) scanner-exempt" in message
    assert "data.blob (not-utf-8)" in message
    assert "style.css (ignored-extension)" in message
    assert "package-lock.json (lock-file)" in message
    assert "docs/swagger.json (swagger-path)" in message
    assert "unclassified candidate" not in message


def _digest_line(key: str, seed: bytes) -> tuple[str, str]:
    """A ``<key>: "<64 hex>"`` content-digest line plus its SHA-1 fingerprint."""
    digest = hashlib.sha256(seed).hexdigest()
    line = '  "' + key + '": "' + digest + '",\n'
    return line, hashlib.sha1(digest.encode("utf-8")).hexdigest()


def _baselined_digest_repo(
    tmp_path: Path, seed: bytes, path: str | None = None
) -> tuple[Path, Path, Path, str, str]:
    """Commitolt repó, digest-sor a 2. soron baselined.

    Visszaadja: (repo, baseline, célfájl, digest-sor, SHA-1 fingerprint).
    """
    repo = _init_repo(tmp_path / "repo")
    digest_line, hashed = _digest_line("reference_sha256", seed)
    target_path = _DIGEST_MANIFEST_PATH if path is None else path
    target = _write_tracked(repo, target_path, "{\n" + digest_line + '  "x": 1\n}\n')
    baseline = repo / "synthetic-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "results": {
                    target_path: [
                        {
                            "type": "Hex High Entropy String",
                            "hashed_secret": hashed,
                            "line_number": 2,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", target_path, baseline.name)
    _commit(repo)
    return repo, baseline, target, digest_line, hashed


def _drive_id_line(key: str, seed: bytes) -> tuple[str, str, str]:
    """A Drive-shaped ``<key>: "1<32 chars>"`` line, its id and fingerprint."""
    tail = base64.urlsafe_b64encode(hashlib.sha256(seed).digest()).decode("ascii")
    resource_id = "1" + tail[:32]
    line = '  "' + key + '": "' + resource_id + '",\n'
    return line, resource_id, hashlib.sha1(resource_id.encode("utf-8")).hexdigest()


def test_runtime_audit_output_is_never_read_back_as_suppression_input(
    tmp_path: Path,
) -> None:
    """The audit artifact is a report, not an allowlist."""
    repo, baseline = _tracked_repo(tmp_path)
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")

    fingerprint = hashlib.sha1(_SYNTHETIC_VALUE.encode("utf-8")).hexdigest()
    planted = check_secret_baseline._unmatched_audit_path(repo)
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(
        json.dumps(
            {
                "schemaVersion": "3.0",
                "kind": "tracked-secret-delta-audit",
                "rows": [
                    {
                        "path": "tracked.py",
                        "type": "Secret Keyword",
                        "classification": "synthetic-demo-credential",
                        "hashes": [fingerprint],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "unclassified candidate(s)" in message


def test_audit_output_path_is_excluded_from_the_candidate_set(tmp_path: Path) -> None:
    """The scanner never re-scans the fingerprints it just wrote."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "clean.py").write_text("# synthetic, no candidates\n", encoding="utf-8")
    audit = check_secret_baseline._unmatched_audit_path(repo)
    audit.parent.mkdir(parents=True, exist_ok=True)
    planted_hashes = [hashlib.sha1(f"synthetic-{index}".encode()).hexdigest() for index in range(6)]
    audit.write_text(json.dumps({"rows": [{"hashes": planted_hashes}]}), encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "clean.py", baseline.name)
    _git(repo, "add", "-f", check_secret_baseline._audit_output_relative_path())
    _commit(repo)

    tracked = check_secret_baseline._git_tracked_candidates(repo, baseline)
    assert check_secret_baseline._audit_output_relative_path() not in tracked

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    for fingerprint in planted_hashes:
        assert fingerprint not in message


def test_content_digest_classifier_clears_a_bound_sha256_value(tmp_path: Path) -> None:
    """A bound 64-hex value introduced after the audited state is proven per
    line by the structural classifier -- the audited commit itself carries
    only benign content, so the finding really is an addition."""
    repo = _init_repo(tmp_path / "repo")
    line, _ = _digest_line("reference_sha256", b"synthetic-content-digest")
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, '{\n  "x": 1\n}\n')
    baseline = _empty_baseline(repo)
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + line + '  "x": 1\n}\n')

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "content-digest: 1" in message


@pytest.mark.parametrize(
    "payload",
    [
        b"line-one\nline-two\n",
        b"line-one\r\nline-two\r\n",
        b"line-one\rline-two\r",
        "header\u2028continues\ncandidate-line\n".encode("utf-8"),
        "header\u2029continues\ncandidate-line\n".encode("utf-8"),
        b"",
        b"only-one-line",
        b"trailing\n",
        b"a\n\n",
    ],
)
def test_universal_newline_split_matches_text_mode_line_numbering(
    tmp_path: Path, payload: bytes
) -> None:
    """The split reproduces text-mode ``readlines()`` numbering exactly."""
    target = tmp_path / "candidate.txt"
    target.write_bytes(payload)
    with open(target, encoding="utf-8") as handle:
        expected = [line.rstrip("\n") for line in handle.readlines()]
    assert check_secret_baseline._universal_newline_lines(
        target.read_text(encoding="utf-8")
    ) == expected


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_unicode_line_separators_never_shift_scanner_line_identity(
    tmp_path: Path, separator: str
) -> None:
    """U+2028/U+2029 must not drift scanner versus classifier line numbers."""
    repo = _init_repo(tmp_path / "repo")
    line, _ = _digest_line("reference_sha256", b"synthetic-separator-regression")
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, '{\n  "x": 1\n}\n')
    baseline = _empty_baseline(repo)
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    _write_tracked(
        repo,
        _DIGEST_MANIFEST_PATH,
        '{\n  "title": "fejezet' + separator + 'folytatás",\n' + line + '  "x": 1\n}\n',
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "content-digest: 1" in message


@pytest.mark.parametrize("separator", [" ", " "])
def test_real_driver_and_classifier_agree_on_line_identity_across_separators(
    tmp_path: Path, separator: str
) -> None:
    """A valódi driver sorszáma és a classifier digestsorai U+2028/U+2029
    tartalom mellett is azonos sort azonosítanak (közvetlen cross-check)."""
    repo = _init_repo(tmp_path / "repo")
    secret_line = PASSWORD_LINE.rstrip("\n")
    _write_tracked(repo, "tracked.py", "header" + separator + "continues\n" + PASSWORD_LINE)
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "_detect_secrets_scan_driver.py")],
        cwd=str(repo),
        input="tracked.py\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    findings = json.loads(completed.stdout)["results"]["tracked.py"]
    line_number = next(
        finding["line_number"] for finding in findings if finding["type"] == "Secret Keyword"
    )
    lines = check_secret_baseline._read_text_for_classification(repo / "tracked.py")
    digests = check_secret_baseline._live_line_content_digests(repo, ["tracked.py"])
    assert lines[line_number - 1] == secret_line
    assert digests["tracked.py"][line_number] == hashlib.sha256(
        secret_line.encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("separator", [" ", " "])
def test_same_line_substitution_with_separator_content_fails_closed(
    tmp_path: Path, separator: str
) -> None:
    """U+2028/U+2029 tartalom mellett az azonos soros contextuscsere sem
    tisztázható: a separator nem tolhatja el a scanner és a classifier
    sorszámozását, a helyettesített sor marad addition és fail-closed."""
    repo, baseline, target, _, hashed = _baselined_digest_repo(
        tmp_path, b"synthetic-same-line-separator"
    )
    digest = hashlib.sha256(b"synthetic-same-line-separator").hexdigest()
    target.write_text(
        '{"title": "fejezet' + separator + 'folytatás",\n  "unbound": "'
        + digest
        + '",\n  "x": 1\n}\n',
        encoding="utf-8",
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "1 unclassified candidate(s) in 1 tracked file(s)" in message
    assert "content-digest" not in message
    assert "reconcile with the audited repository state" not in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    document = json.loads(audit.read_text(encoding="utf-8"))
    row = document["rows"][0]
    assert row["hashes"] == [hashed]
    assert row["lineNumbers"] == [2]
    anchor = check_secret_baseline._baseline_anchor_commit(repo, baseline)
    audited_digests = check_secret_baseline._audited_line_content_digests(
        repo, anchor, [_DIGEST_MANIFEST_PATH]
    )
    live_digests = check_secret_baseline._live_line_content_digests(repo, [_DIGEST_MANIFEST_PATH])
    assert audited_digests[_DIGEST_MANIFEST_PATH][2] != live_digests[_DIGEST_MANIFEST_PATH][2]


@pytest.mark.parametrize("separator", [" ", " "])
def test_moved_line_substitution_with_separator_content_fails_closed(
    tmp_path: Path, separator: str
) -> None:
    """U+2028/U+2029 tartalom mellett a sor-áthelyezés is fail-closed: a
    digest az új (3.) soron, kötetlen kulcshoz kötve marad addition, a
    separator semmilyen sorszám-eltolódást nem okozhat."""
    repo, baseline, target, _, hashed = _baselined_digest_repo(
        tmp_path, b"synthetic-moved-line-separator"
    )
    digest = hashlib.sha256(b"synthetic-moved-line-separator").hexdigest()
    target.write_text(
        '{\n  "title": "fejezet' + separator + 'folytatás",\n  "unbound": "'
        + digest
        + '",\n  "x": 1\n}\n',
        encoding="utf-8",
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "1 unclassified candidate(s) in 1 tracked file(s)" in message
    assert "content-digest" not in message
    assert "reconcile with the audited repository state" not in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    document = json.loads(audit.read_text(encoding="utf-8"))
    row = document["rows"][0]
    assert row["hashes"] == [hashed]
    assert row["lineNumbers"] == [3]
    anchor = check_secret_baseline._baseline_anchor_commit(repo, baseline)
    audited_state = check_secret_baseline._audited_occurrence_identities(
        repo, anchor, [_DIGEST_MANIFEST_PATH]
    )
    assert {line for _, _, _, line in audited_state} == {2}
    assert row["findingCount"] == 1


def test_content_digest_classifier_rejects_an_unbound_hex_value(tmp_path: Path) -> None:
    """The same 64-hex value fails closed when it is not bound to a digest key."""
    repo = _init_repo(tmp_path / "repo")
    digest = hashlib.sha256(b"synthetic-content-digest").hexdigest()
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, '{\n  "x": 1\n}\n')
    baseline = _empty_baseline(repo)
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, '{\n  "api_value": "' + digest + '"\n}\n')

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "unclassified candidate(s)" in message


def test_content_digest_classifier_rejects_exact_key_outside_registry_files(
    tmp_path: Path,
) -> None:
    """The exact digest key in any other file stays unclassified (path context)."""
    repo = _init_repo(tmp_path / "repo")
    line, _ = _digest_line("reference_sha256", b"synthetic-content-digest")
    (repo / "manifest.json").write_text('{\n  "x": 1\n}\n', encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "manifest.json", baseline.name)
    _commit(repo)
    (repo / "manifest.json").write_text("{\n" + line + '  "x": 1\n}\n', encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "unclassified candidate(s)" in message


def test_content_digest_classifier_rejects_a_lookalike_key(tmp_path: Path) -> None:
    """A secret stored under a key merely ending in ``sha256`` is not cleared."""
    repo = _init_repo(tmp_path / "repo")
    digest = hashlib.sha256(b"synthetic-lookalike-key").hexdigest()
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, '{\n  "x": 1\n}\n')
    baseline = _empty_baseline(repo)
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, '{\n  "api_sha256": "' + digest + '"\n}\n')

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "unclassified candidate(s)" in message


def test_real_secret_in_a_classified_file_still_fails_closed(tmp_path: Path) -> None:
    """Clearance is per-value, never per-file."""
    repo = _init_repo(tmp_path / "repo")
    line, _ = _digest_line("fragment_sha256", b"synthetic-content-digest")
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + line + '  "x": 1\n}\n')
    baseline = _empty_baseline(repo)
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message

    _write_tracked(
        repo, _DIGEST_MANIFEST_PATH, "{\n" + line + "  " + PASSWORD_LINE.strip() + "\n}\n"
    )
    _git(repo, "add", _DIGEST_MANIFEST_PATH)
    _commit(repo)

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "unclassified candidate(s)" in message
    assert _DIGEST_MANIFEST_PATH in message


def test_drive_resource_id_requires_corroborating_provenance(tmp_path: Path) -> None:
    """A Drive-shaped identifier alone is not enough; the file must prove it."""
    repo = _init_repo(tmp_path / "repo")
    line, resource_id, _ = _drive_id_line("sourceId", b"synthetic-drive-resource")
    _write_tracked(repo, _DRIVE_ARTIFACTS_PATH, '{\n  "x": 1\n}\n')
    baseline = _empty_baseline(repo)
    _git(repo, "add", _DRIVE_ARTIFACTS_PATH, baseline.name)
    _commit(repo)
    _write_tracked(repo, _DRIVE_ARTIFACTS_PATH, "{\n" + line + '  "x": 1\n}\n')

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    if status == 0:
        pytest.skip("the synthetic identifier stayed under the detector entropy threshold")
    assert status == 1, message
    assert "unclassified candidate(s)" in message

    _write_tracked(
        repo,
        _DRIVE_ARTIFACTS_PATH,
        "{\n"
        + line
        + '  "url": "https://docs.google.com/document/d/'
        + resource_id
        + '/edit"\n}\n',
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "drive-resource-id" in message


def test_drive_resource_id_rejected_outside_drive_index_files(tmp_path: Path) -> None:
    """The exact Drive key with corroboration in another file stays unclassified."""
    repo = _init_repo(tmp_path / "repo")
    line, resource_id, _ = _drive_id_line("id", b"synthetic-drive-outside")
    (repo / "artifacts.json").write_text('{\n  "x": 1\n}\n', encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "artifacts.json", baseline.name)
    _commit(repo)
    (repo / "artifacts.json").write_text(
        "{\n"
        + line
        + '  "url": "https://docs.google.com/document/d/'
        + resource_id
        + '/edit"\n}\n',
        encoding="utf-8",
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    if status == 0:
        pytest.skip("the synthetic identifier stayed under the detector entropy threshold")
    assert status == 1, message
    assert "unclassified candidate(s)" in message


def test_unclassifiable_detector_type_fails_closed(tmp_path: Path) -> None:
    """``Secret Keyword`` has no structural classifier at all."""
    assert "Secret Keyword" not in check_secret_baseline._STRUCTURAL_CLASSIFIERS
    repo, baseline = _tracked_repo(tmp_path)
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "unclassified candidate(s)" in message


def test_emitted_audit_report_is_bounded_and_states_its_truncation(tmp_path: Path) -> None:
    """The artifact stays short without ever understating the failure."""
    rows = check_secret_baseline._AUDIT_MAX_ROWS
    per_row = check_secret_baseline._AUDIT_MAX_HASHES_PER_ROW
    additions = {
        (
            f"path/file-{index}.json",
            "Hex High Entropy String",
            hashlib.sha1(f"synthetic-{index}-{offset}".encode()).hexdigest(),
            offset + 1,
        )
        for index in range(rows + 4)
        for offset in range(per_row + 3)
    }
    written = check_secret_baseline._emit_unmatched_audit(additions, tmp_path)
    document = json.loads(written.read_text(encoding="utf-8"))

    assert len(document["rows"]) == rows
    assert document["rowsOmitted"] == 4
    assert document["findingTotal"] == len(additions)
    assert document["rowTotal"] == rows + 4
    for row in document["rows"]:
        assert len(row["hashes"]) <= per_row
        assert len(row["lineNumbers"]) == len(row["hashes"])
        # A sorszámok az azonos sorban álló hash-ekhez tartoznak, 1-től a
        # szintetikus offset-tartományig.
        assert set(row["lineNumbers"]) <= set(range(1, per_row + 4))
        assert row["findingCount"] == per_row + 3
        assert row["hashesOmitted"] == 3
        assert row["classification"] == "unclassified"
    assert len(json.dumps(document)) < 12_000, "the audit report must stay reviewable"


@pytest.mark.parametrize("line_number", [0, -1, 9_999, None])
def test_out_of_range_line_number_never_wraps_to_another_line(
    tmp_path: Path, line_number: int | None
) -> None:
    """A finding whose line number is absent or bogus stays unclassified."""
    digest_line, _ = _digest_line("reference_sha256", b"synthetic-content-digest")
    _write_tracked(tmp_path, _DIGEST_MANIFEST_PATH, '{\n  "x": 1,\n' + digest_line + "}\n")
    hashed = hashlib.sha1(
        hashlib.sha256(b"synthetic-content-digest").hexdigest().encode("utf-8")
    ).hexdigest()
    document = {
        "results": {
            _DIGEST_MANIFEST_PATH: [
                {
                    "type": "Hex High Entropy String",
                    "hashed_secret": hashed,
                    "line_number": line_number,
                }
            ]
        }
    }
    additions = {(_DIGEST_MANIFEST_PATH, "Hex High Entropy String", hashed, line_number)}

    classified, unclassified = check_secret_baseline._classify_additions(
        document, additions, tmp_path
    )
    assert classified == {}
    assert unclassified == additions


def test_same_fingerprint_on_several_classified_lines_is_counted_per_line(
    tmp_path: Path,
) -> None:
    """Az azonos digest minden új sor-előfordulása saját identitás, soronként
    értékelve és számolva: két kötött digest-sor két classified bejegyzés."""
    digest_line, hashed = _digest_line("reference_sha256", b"synthetic-content-digest")
    _write_tracked(
        tmp_path,
        _DIGEST_MANIFEST_PATH,
        "{\n" + digest_line + digest_line + '  "x": 1\n}\n',
    )
    document = {
        "results": {
            _DIGEST_MANIFEST_PATH: [
                {"type": "Hex High Entropy String", "hashed_secret": hashed, "line_number": 2},
                {"type": "Hex High Entropy String", "hashed_secret": hashed, "line_number": 3},
            ]
        }
    }
    additions = {
        (_DIGEST_MANIFEST_PATH, "Hex High Entropy String", hashed, 2),
        (_DIGEST_MANIFEST_PATH, "Hex High Entropy String", hashed, 3),
    }

    classified, unclassified = check_secret_baseline._classify_additions(
        document, additions, tmp_path
    )
    assert classified == {"content-digest": 2}
    assert unclassified == set()


def test_pinned_driver_preserves_one_entry_per_line_for_the_same_digest(
    tmp_path: Path,
) -> None:
    """A driver sosem lapítja össze az azonos digestű, különböző soros találatokat."""
    digest = hashlib.sha256(b"synthetic-per-line-driver").hexdigest()
    target = tmp_path / "tracked.json"
    target.write_text(
        '{\n  "reference_sha256": "' + digest + '",\n  "unbound": "' + digest + '",\n}\n',
        encoding="utf-8",
    )
    hashed = hashlib.sha1(digest.encode("utf-8")).hexdigest()
    with default_settings():
        entries = _detect_secrets_scan_driver._scan_and_dedupe(str(target))
    hex_entries = [
        entry
        for entry in entries
        if entry.get("type") == "Hex High Entropy String" and entry.get("hashed_secret") == hashed
    ]
    assert {entry.get("line_number") for entry in hex_entries} == {2, 3}


def test_identical_digest_on_classified_and_unclassified_lines_fails_closed(
    tmp_path: Path,
) -> None:
    """Azonos digestű, eltérő sorokon szereplő classified és unclassified találat."""
    repo = _init_repo(tmp_path / "repo")
    digest = hashlib.sha256(b"synthetic-mixed-line").hexdigest()
    _write_tracked(
        repo, _DIGEST_MANIFEST_PATH, '{\n  "reference_sha256": "' + digest + '",\n  "x": 1\n}\n'
    )
    baseline = _empty_baseline(repo)
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    _write_tracked(
        repo,
        _DIGEST_MANIFEST_PATH,
        '{\n  "reference_sha256": "' + digest + '",\n  "unbound": "' + digest + '",\n  "x": 1\n}\n',
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "unclassified candidate(s)" in message
    assert _DIGEST_MANIFEST_PATH in message
    assert "content-digest" not in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    assert audit.is_file()
    document = json.loads(audit.read_text(encoding="utf-8"))
    assert document["classification"] == "unclassified"


def test_baselined_digest_on_a_new_unclassified_line_fails_closed(tmp_path: Path) -> None:
    """A classified soron baselined érték nem fedhet el új, osztályozatlan sort."""
    repo = _init_repo(tmp_path / "repo")
    digest_line, hashed = _digest_line("reference_sha256", b"synthetic-baselined-line")
    digest = hashlib.sha256(b"synthetic-baselined-line").hexdigest()
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + digest_line + '  "x": 1\n}\n')
    baseline = repo / "synthetic-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "results": {
                    _DIGEST_MANIFEST_PATH: [
                        {
                            "type": "Hex High Entropy String",
                            "hashed_secret": hashed,
                            "line_number": 2,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    _write_tracked(
        repo,
        _DIGEST_MANIFEST_PATH,
        "{\n" + digest_line + '  "unbound": "' + digest + '",\n  "x": 1\n}\n',
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "1 unclassified candidate(s) in 1 tracked file(s)" in message
    assert _DIGEST_MANIFEST_PATH in message
    assert "content-digest" not in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    assert audit.is_file()
    document = json.loads(audit.read_text(encoding="utf-8"))
    assert document["classification"] == "unclassified"
    row = document["rows"][0]
    assert row["path"] == _DIGEST_MANIFEST_PATH
    assert row["hashes"] == [hashed]
    assert row["lineNumbers"] == [3]


def test_baselined_digest_on_a_new_classified_line_is_proven_per_line(
    tmp_path: Path,
) -> None:
    """Az új sor-előfordulást a classifiernek kell bizonyítania -- és tudja is."""
    repo = _init_repo(tmp_path / "repo")
    digest_line, hashed = _digest_line("reference_sha256", b"synthetic-new-classified-line")
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + digest_line + '  "x": 1\n}\n')
    baseline = repo / "synthetic-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "results": {
                    _DIGEST_MANIFEST_PATH: [
                        {
                            "type": "Hex High Entropy String",
                            "hashed_secret": hashed,
                            "line_number": 2,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", _DIGEST_MANIFEST_PATH, baseline.name)
    _commit(repo)
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + digest_line + digest_line + '  "x": 1\n}\n')

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "1 tracked candidate(s) match the audited baseline" in message
    assert "content-digest: 1" in message


def test_baselined_classified_line_still_matches_the_audited_set_exactly(
    tmp_path: Path,
) -> None:
    """Az occurrence-aware identitás nem törte meg a baselined sor egyezését."""
    repo, baseline, _, _, _ = _baselined_digest_repo(tmp_path, b"synthetic-exact-line-match")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "1 tracked candidate(s) match the audited baseline" in message
    assert "structural classifier" not in message


def test_unchanged_canonical_repeat_occurrences_reconcile(tmp_path: Path) -> None:
    """Iránymutató 1: a kanonikus, deduplikált baseline változatlan ismétlődő
    előfordulásokkal is sikeresen egyeztet.
    """
    repo = _init_repo(tmp_path / "repo")
    placeholder = "not-a-" + "real-" + "secret-" + "value"
    content = (
        "{\n"
        '  "brand_a": {"secret": "' + placeholder + '"},\n'
        '  "brand_b": {"secret": "' + placeholder + '"},\n'
        '  "brand_c": {"secret": "' + placeholder + '"},\n'
        '  "brand_d": {"secret": "' + placeholder + '"}\n'
        "}\n"
    )
    _write_tracked(repo, "config/website-targets.json", content)
    hashed = hashlib.sha1(placeholder.encode("utf-8")).hexdigest()
    baseline = repo / "synthetic-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "results": {
                    "config/website-targets.json": [
                        {
                            "type": "Secret Keyword",
                            "hashed_secret": hashed,
                            "line_number": 2,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "config/website-targets.json", baseline.name)
    _commit(repo)

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "1 tracked candidate(s) match the audited baseline" in message
    assert "3 candidate(s) reconcile with the audited repository state" in message
    assert "structural classifier" not in message


def test_line_drifted_existing_occurrence_reconciles(tmp_path: Path) -> None:
    """Iránymutató 1 (sor-eltolódás): egy auditált érték eltolódott sora nem
    addition -- az előfordulásszám nem haladja meg az auditáltat."""
    repo, baseline, target, digest_line, _ = _baselined_digest_repo(
        tmp_path, b"synthetic-line-drift"
    )
    # Az auditált sor fölé kerülő, független szerkesztés: az érték a 2. sorról
    # a 4. sorra csúszik -- az előfordulásszám nem nő, így nem addition.
    drifted = '{\n  "added": 1,\n  "added": 2,\n' + digest_line + '  "x": 1\n}\n'
    target.write_text(drifted, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "1 candidate(s) reconcile with the audited repository state" in message
    assert "structural classifier" not in message


def test_duplicated_audited_value_blocks_without_structural_proof(tmp_path: Path) -> None:
    """Iránymutató 2: az auditált digest ÚJ soron ismételt másolata addition."""
    repo, baseline, target, digest_line, hashed = _baselined_digest_repo(
        tmp_path, b"synthetic-duplicated"
    )
    digest = hashlib.sha256(b"synthetic-duplicated").hexdigest()
    target.write_text(
        "{\n" + digest_line + '  "unbound": "' + digest + '",\n  "x": 1\n}\n',
        encoding="utf-8",
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "1 unclassified candidate(s) in 1 tracked file(s)" in message
    assert _DIGEST_MANIFEST_PATH in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    assert audit.is_file()
    document = json.loads(audit.read_text(encoding="utf-8"))
    row = document["rows"][0]
    assert row["path"] == _DIGEST_MANIFEST_PATH
    assert row["hashes"] == [hashed]
    assert row["lineNumbers"] == [3]


def test_audited_digest_moved_to_an_unclassified_line_fails_closed(tmp_path: Path) -> None:
    """A Task38 review HIGH közvetlen regressziója: sor-helyettesítés fail-closed."""
    repo, baseline, target, _, hashed = _baselined_digest_repo(
        tmp_path, b"synthetic-line-substitution"
    )
    digest = hashlib.sha256(b"synthetic-line-substitution").hexdigest()
    # A classified 2. sor törölve; ugyanaz a digest a 3. soron, kötetlen
    # kulcshoz rendelve. Az előfordulásszám marad 1.
    target.write_text(
        '{\n  "x": 1,\n  "unbound": "' + digest + '",\n  "y": 2\n}\n',
        encoding="utf-8",
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "1 unclassified candidate(s) in 1 tracked file(s)" in message
    assert _DIGEST_MANIFEST_PATH in message
    # Semmilyen classifier-engedmény és semmilyen audited-state egyeztetés nem
    # tisztázhatta a helyettesített sort.
    assert "content-digest" not in message
    assert "reconcile with the audited repository state" not in message
    assert digest not in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    document = json.loads(audit.read_text(encoding="utf-8"))
    row = document["rows"][0]
    assert row["path"] == _DIGEST_MANIFEST_PATH
    assert row["hashes"] == [hashed]
    assert row["lineNumbers"] == [3]
    # A premissza rögzítése: pontosan EGY auditált előfordulás állt a 2. soron,
    # és pontosan EGY élő előfordulás van -- az összesített darabszám tehát
    # valóban változatlan, a fail-closed kizárólag a soronkénti tartalmi
    # egyenértékűség hiányából ered.
    anchor = check_secret_baseline._baseline_anchor_commit(repo, baseline)
    audited_state = check_secret_baseline._audited_occurrence_identities(
        repo, anchor, [_DIGEST_MANIFEST_PATH]
    )
    assert {line for _, _, _, line in audited_state} == {2}
    assert row["findingCount"] == 1


def test_same_line_classified_to_unclassified_substitution_fails_closed(
    tmp_path: Path,
) -> None:
    """A Task39 review HIGH közvetlen regressziója: azonos soron kontextuscsere."""
    repo, baseline, target, _, hashed = _baselined_digest_repo(
        tmp_path, b"synthetic-same-line-context"
    )
    digest = hashlib.sha256(b"synthetic-same-line-context").hexdigest()
    # A digest a helyén marad (2. sor), csak a classified kötés tűnik el.
    target.write_text(
        '{\n  "unbound": "' + digest + '",\n  "x": 1\n}\n',
        encoding="utf-8",
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "1 unclassified candidate(s) in 1 tracked file(s)" in message
    assert _DIGEST_MANIFEST_PATH in message
    # Sem classifier-engedmény, sem audited-state egyeztetés nem tisztázta.
    assert "content-digest" not in message
    assert "reconcile with the audited repository state" not in message
    assert digest not in message
    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    document = json.loads(audit.read_text(encoding="utf-8"))
    row = document["rows"][0]
    assert row["path"] == _DIGEST_MANIFEST_PATH
    assert row["hashes"] == [hashed]
    # A premissza rögzítése: az osztályozatlanul maradt élő előfordulás
    # pontosan a baseline saját során (2.) áll, ugyanazzal a fingerprinttel --
    # a négyrészes identitás tehát azonos, kizárólag a sortartalom más.
    assert row["lineNumbers"] == [2]
    baseline_document = json.loads(baseline.read_text(encoding="utf-8"))
    assert check_secret_baseline._fingerprints(baseline_document) == {
        (_DIGEST_MANIFEST_PATH, "Hex High Entropy String", hashed, 2)
    }
    anchor = check_secret_baseline._baseline_anchor_commit(repo, baseline)
    audited_digests = check_secret_baseline._audited_line_content_digests(
        repo, anchor, [_DIGEST_MANIFEST_PATH]
    )
    live_digests = check_secret_baseline._live_line_content_digests(repo, [_DIGEST_MANIFEST_PATH])
    assert audited_digests[_DIGEST_MANIFEST_PATH][2] != live_digests[_DIGEST_MANIFEST_PATH][2]


def test_baseline_subtraction_requires_byte_identical_line_content() -> None:
    """``_split_baseline_matches``: a baseline-kivonás is tartalmi bizonyítékot kér."""
    path = _DIGEST_MANIFEST_PATH
    value = (path, "Hex High Entropy String", "a" * 40)
    observed = {(*value, 2)}
    audited = {(*value, 2)}
    audited_digests = {path: {2: "1" * 64}}

    matched, additions = check_secret_baseline._split_baseline_matches(
        observed, audited, audited_digests, {path: {2: "2" * 64}}
    )
    assert matched == set()
    assert additions == observed
    # Ellenpróba: byte-azonos sortartalom mellett -- és csak ilyenkor -- egyezik.
    matched, additions = check_secret_baseline._split_baseline_matches(
        observed, audited, audited_digests, {path: {2: "1" * 64}}
    )
    assert matched == observed
    assert additions == set()
    # Hiányzó bizonyíték bármelyik oldalon: nincs egyezés.
    for audited_side, live_side in (
        ({}, {path: {2: "1" * 64}}),
        (audited_digests, {}),
    ):
        matched, additions = check_secret_baseline._split_baseline_matches(
            observed, audited, audited_side, live_side
        )
        assert matched == set()
        assert additions == observed
    # Használható sorszám nélküli identitás sosem egyezik.
    matched, additions = check_secret_baseline._split_baseline_matches(
        {(*value, None)}, {(*value, None)}, audited_digests, {path: {2: "1" * 64}}
    )
    assert matched == set()
    assert additions == {(*value, None)}


def test_bare_line_number_never_seats_an_occurrence() -> None:
    """``_match_occurrences``: nincs puszta sorszám-alapú compatibility path."""
    assert check_secret_baseline._match_occurrences([2], [2], {2: "a" * 64}, {2: "b" * 64}) == {}
    assert check_secret_baseline._match_occurrences([2], [2], {}, {}) == {}
    assert check_secret_baseline._match_occurrences([2], [2], {2: "a" * 64}, {2: "a" * 64}) == {
        2: 2
    }


# A ``_split_additions`` tartalmi-bizonyíték szerződésének egység-esetei;
# a leírások a korábbi bypass-t/regressziót magyarázzák, a várt eredmények
# bitre pontosak.
_MANIFEST = _DIGEST_MANIFEST_PATH
_USER_ADMIN = "services/platform-core/tests/test_user_administration.py"


def _hex_ident(path: str, fingerprint: str, line: int | None) -> tuple:
    """Egy ``Hex High Entropy`` találat négyrészes identitása."""
    return (path, "Hex High Entropy String", fingerprint, line)


_SPLIT_CASES = [
    (
        "azonos darabszám, bizonyíték nélkül: az auditált 2. sor, az élő 7. sor "
        "más tartalommal -- az eltávolított count-alapú bypass nem ültet",
        {_hex_ident(_MANIFEST, "f" * 40, 7)},
        {_hex_ident(_MANIFEST, "f" * 40, 7)},
        {_hex_ident(_MANIFEST, "f" * 40, 2)},
        {_MANIFEST: {2: "a" * 64}},
        {_MANIFEST: {7: "b" * 64}},
        set(),
        {_hex_ident(_MANIFEST, "f" * 40, 7)},
    ),
    (
        "ellenpróba: ugyanaz az eltolódott előfordulás byte-azonos tartalommal "
        "-- ilyenkor és csak ilyenkor egyeztet",
        {_hex_ident(_MANIFEST, "f" * 40, 7)},
        {_hex_ident(_MANIFEST, "f" * 40, 7)},
        {_hex_ident(_MANIFEST, "f" * 40, 2)},
        {_MANIFEST: {2: "a" * 64}},
        {_MANIFEST: {7: "a" * 64}},
        {_hex_ident(_MANIFEST, "f" * 40, 7)},
        set(),
    ),
    (
        "injektivitás: egy auditált előfordulás legfeljebb egy élőt fed -- két "
        "azonos tartalmú élőből pontosan a rendezett első (7.) tisztázható",
        {_hex_ident(_MANIFEST, "e" * 40, 7), _hex_ident(_MANIFEST, "e" * 40, 9)},
        {_hex_ident(_MANIFEST, "e" * 40, 7), _hex_ident(_MANIFEST, "e" * 40, 9)},
        {_hex_ident(_MANIFEST, "e" * 40, 2)},
        {_MANIFEST: {2: "a" * 64}},
        {_MANIFEST: {7: "a" * 64, 9: "a" * 64}},
        {_hex_ident(_MANIFEST, "e" * 40, 7)},
        {_hex_ident(_MANIFEST, "e" * 40, 9)},
    ),
    (
        "lefoglalt auditált sor nem fedhet elcsúszott másolatot: a 2. sor élőben "
        "is ott áll, a 9. soron megjelenő azonos tartalom új előfordulás",
        {_hex_ident(_MANIFEST, "d" * 40, 9)},
        {_hex_ident(_MANIFEST, "d" * 40, 2), _hex_ident(_MANIFEST, "d" * 40, 9)},
        {_hex_ident(_MANIFEST, "d" * 40, 2)},
        {_MANIFEST: {2: "a" * 64}},
        {_MANIFEST: {2: "a" * 64, 9: "a" * 64}},
        set(),
        {_hex_ident(_MANIFEST, "d" * 40, 9)},
    ),
    (
        "eltolódott blokk: a 41./42. auditált sorok tartalma élőben a 42./43. "
        "soron -- a 42. sorszám véletlen egybeesése MÁS tartalommal nem zavar, "
        "mindkettő egyeztet (valós regresszió a test_user_administration.py-ból)",
        {(_USER_ADMIN, "Secret Keyword", "0" * 40, 43)},
        {(_USER_ADMIN, "Secret Keyword", "0" * 40, 42), (_USER_ADMIN, "Secret Keyword", "0" * 40, 43)},
        {(_USER_ADMIN, "Secret Keyword", "0" * 40, 41), (_USER_ADMIN, "Secret Keyword", "0" * 40, 42)},
        {_USER_ADMIN: {41: "a" * 64, 42: "b" * 64}},
        {_USER_ADMIN: {42: "a" * 64, 43: "b" * 64}},
        {(_USER_ADMIN, "Secret Keyword", "0" * 40, 43)},
        set(),
    ),
    (
        "hiányzó auditált bizonyíték (a fájl nem létezett az anchoron) vagy "
        "használható sorszám nélküli identitás: minden addition marad",
        {_hex_ident("late.json", "c" * 40, 4), _hex_ident("late.json", "c" * 40, None)},
        {_hex_ident("late.json", "c" * 40, 4), _hex_ident("late.json", "c" * 40, None)},
        {_hex_ident("late.json", "c" * 40, 2)},
        {},
        {"late.json": {4: "a" * 64}},
        set(),
        {_hex_ident("late.json", "c" * 40, 4), _hex_ident("late.json", "c" * 40, None)},
    ),
    (
        "hiányzó élő bizonyíték (tartományon kívüli sor): addition marad",
        {_hex_ident("late.json", "c" * 40, 4), _hex_ident("late.json", "c" * 40, None)},
        {_hex_ident("late.json", "c" * 40, 4), _hex_ident("late.json", "c" * 40, None)},
        {_hex_ident("late.json", "c" * 40, 2)},
        {"late.json": {2: "a" * 64}},
        {"late.json": {}},
        set(),
        {_hex_ident("late.json", "c" * 40, 4), _hex_ident("late.json", "c" * 40, None)},
    ),
]


@pytest.mark.parametrize(
    "description, additions, observed, audited_state, audited_digests, live_digests, "
    "expected_resolved, expected_remaining",
    _SPLIT_CASES,
    ids=[case[0] for case in _SPLIT_CASES],
)
def test_split_additions_content_contract(
    description: str,
    additions: set,
    observed: set,
    audited_state: set,
    audited_digests: dict,
    live_digests: dict,
    expected_resolved: set,
    expected_remaining: set,
) -> None:
    """``_split_additions``: csak bizonyított tartalmi egyezés ültet le, injektíven."""
    resolved, remaining = check_secret_baseline._split_additions(
        additions, observed, audited_state, audited_digests, live_digests
    )
    assert resolved == expected_resolved, description
    assert remaining == expected_remaining, description
    assert resolved | remaining == additions, description


def test_new_tracked_file_after_the_audited_state_fails_closed(tmp_path: Path) -> None:
    """Az audited commit után létrejött fájlnak nincs auditált állapota."""
    repo, baseline = _tracked_repo(tmp_path)
    (repo / "late.py").write_text(PASSWORD_LINE, encoding="utf-8")
    _git(repo, "add", "late.py")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1
    assert "- late.py" in message
    assert _SYNTHETIC_VALUE not in message


def test_uncommitted_baseline_fails_closed_on_the_audited_anchor(tmp_path: Path) -> None:
    """Commit nélküli baseline nem horgonyozhat auditált állapotot."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py")
    _commit(repo)

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "baseline anchor commit" in message


def test_baseline_outside_repository_root_fails_closed(tmp_path: Path) -> None:
    """A reconciled gyökéren kívüli baseline fail-closed: nincs auditált állapot."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")
    _git(repo, "add", "tracked.py")
    _commit(repo)
    outside = tmp_path / "outside-baseline.json"
    outside.write_text(json.dumps({"results": {}}), encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(outside, repo_root=repo)
    assert status == 2
    assert "outside the reconciled repository root" in message


def test_audited_state_scan_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Az auditált állapot scan hibája fail-closed (status 2), nem PASS."""
    repo, baseline = _tracked_repo(tmp_path)
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")
    monkeypatch.setattr(check_secret_baseline, "_run_audited_driver", _driver_fake(returncode=1))

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "scan driver exit code 1" in message


def test_faked_live_scan_cannot_fabricate_audited_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Az auditált állapot a saját seamjén fut: egy hamisított élő scan nem
    gyárthat auditált lefedettséget -- a hamis találat addition marad."""
    repo, baseline = _tracked_repo(tmp_path)
    synthetic_hash = hashlib.sha1(_SYNTHETIC_VALUE.encode("utf-8")).hexdigest()

    def _fake_live(files: list[str], repo_root: Path) -> subprocess.CompletedProcess[bytes]:
        return _driver_fake(
            payload={
                "tracked.py": [
                    {
                        "type": "Secret Keyword",
                        "hashed_secret": synthetic_hash,
                        "line_number": 1,
                    }
                ]
            }
        )(files, repo_root)

    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _fake_live)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    # A valódi auditált scan az ártalmatlan commitot látja: a hamis találatnak
    # nincs auditált állapota, így osztályozatlan marad.
    assert status == 1, message
    assert "- tracked.py" in message


def test_audited_state_scan_leaves_no_temp_copies(tmp_path: Path) -> None:
    """Az auditált állapot átmeneti másolatai mindig törlődnek a futás végén."""
    repo, baseline = _tracked_repo(tmp_path)
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    historical = repo.joinpath(*check_secret_baseline._HISTORICAL_SCAN_RELATIVE_DIR)
    assert list(historical.glob("*")) == []


def test_classifier_allowlist_has_no_executable_source_or_generic_keys() -> None:
    """A strukturális osztályozó engedménye sehol sem érinthet futtatható
    forrást, és nem ismerhet általános mezőneveket."""
    paths = check_secret_baseline._CONTENT_DIGEST_PATHS
    assert "services/platform-core/app/seed.py" not in paths
    assert all(path.endswith(".json") for path in paths)
    assert check_secret_baseline._CONTENT_DIGEST_KEYS == frozenset(
        {
            "reference_sha256",
            "fragment_sha256",
            "claim_snapshot_sha256",
            "source_sha256",
        }
    )
    assert "services/platform-core/app/seed.py" not in (
        check_secret_baseline._DRIVE_RESOURCE_ID_PATHS
    )
    assert all(path.endswith(".json") for path in check_secret_baseline._DRIVE_RESOURCE_ID_PATHS)


def test_real_seed_source_digest_values_stay_unclassified() -> None:
    """A valódi ``app/seed.py`` digestértékei fail-closed módon osztályozatlanok."""
    seed_path = REPO_ROOT / "services" / "platform-core" / "app" / "seed.py"
    source_text = seed_path.read_text(encoding="utf-8")
    digest_match = re.search(r'"([0-9a-f]{64})"', source_text)
    assert digest_match is not None, "seed.py továbbra is tartalmaz digestet"
    value = digest_match.group(1)
    line_number = source_text[: digest_match.start()].count("\n") + 1
    hashed = hashlib.sha1(value.encode("utf-8")).hexdigest()
    document = {
        "results": {
            "services/platform-core/app/seed.py": [
                {
                    "type": "Hex High Entropy String",
                    "hashed_secret": hashed,
                    "line_number": line_number,
                }
            ]
        }
    }
    additions = {
        ("services/platform-core/app/seed.py", "Hex High Entropy String", hashed, line_number)
    }
    classified, unclassified = check_secret_baseline._classify_additions(
        document, additions, REPO_ROOT
    )
    assert classified == {}
    assert unclassified == additions


def test_driver_spawn_oserror_becomes_secret_free_scan_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A driver indítási OSError-ja titokmentes ScanFailure, nem traceback."""

    def _broken_spawn(args, **kwargs):
        raise OSError("synthetic spawn failure")

    monkeypatch.setattr(check_secret_baseline.subprocess, "run", _broken_spawn)
    with pytest.raises(check_secret_baseline.ScanFailure) as excinfo:
        check_secret_baseline._run_driver_scan(["synthetic.py"], check_secret_baseline.REPO_ROOT)
    message = str(excinfo.value)
    assert "could not start" in message
    assert "synthetic spawn failure" not in message
    assert "synthetic.py" not in message


def test_runtime_audit_directory_is_git_ignored_and_absent_from_git_status() -> None:
    """A runtime audit könyvtár git-ignored, az artifact sosem jelenik meg a
    git státuszban.
    """
    audit_relative = check_secret_baseline._audit_output_relative_path()
    runtime_dir = audit_relative.rsplit("/", 1)[0]
    for target in (runtime_dir, audit_relative):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", target],
            cwd=str(REPO_ROOT),
            capture_output=True,
        ).returncode
        assert ignored == 0, f"{target} must be git-ignored"
    # Az artifact létezzen is a lemezen, hogy a státuszellenőrzés valóban az
    # ignore-szabályt bizonyítsa, ne csak a hiányát.
    audit_path = check_secret_baseline._unmatched_audit_path(REPO_ROOT)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps({"kind": "tracked-secret-delta-audit", "rows": []}),
        encoding="utf-8",
    )
    status_output = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
    )
    assert "tracked-secret-delta-audit" not in status_output


def test_unreadable_candidate_fails_closed_during_classification(tmp_path: Path) -> None:
    """A candidate that cannot be re-read is never silently cleared."""
    additions = {("missing.json", "Hex High Entropy String", "a" * 40, 1)}
    with pytest.raises(check_secret_baseline.ScanFailure):
        check_secret_baseline._classify_additions(
            {"results": {"missing.json": []}}, additions, tmp_path
        )


def test_repository_carries_no_tracked_secret_delta_artifact() -> None:
    """Regression: sem a régi allowlist, sem az új runtime-audit nem követett."""
    tracked = subprocess.check_output(
        ["git", "ls-files"], cwd=str(REPO_ROOT), text=True, encoding="utf-8"
    ).splitlines()
    assert [path for path in tracked if "audited-delta" in path] == []
    assert [path for path in tracked if "tracked-secret-delta-audit" in path] == []
    assert [path for path in tracked if path.startswith("services/platform-core/runtime/")] == []


def test_live_scan_smoke_runs_the_real_scanner_on_a_trivial_repository(
    tmp_path: Path,
) -> None:
    """Real end-to-end proof; nothing in this test is monkeypatched."""
    repo = _init_repo(tmp_path / "smoke-repo")
    # A jelölt az audited commit UTÁN kerül a munkafába (a commit csak
    # ártalmatlan tartalmat hordoz), hogy az élő scannel, a driverrel, a
    # szondákkal és az accountinggel együtt a teljes addition-utat mérje.
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    (repo / "clean.py").write_text("# synthetic, no candidates\n", encoding="utf-8")
    (repo / "nulbytes.py").write_bytes(
        b"# synthetic header\x00with nul bytes\nplain text, no candidates\n"
    )
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", "clean.py", "nulbytes.py", baseline.name)
    _commit(repo)
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    assert "2 unclassified candidate(s) in 1 tracked file(s)" in message
    assert "- tracked.py" in message
    assert "- clean.py" not in message
    assert "- nulbytes.py" not in message
    assert "did not account for requested file(s)" not in message
    assert _SYNTHETIC_VALUE not in message
    fingerprint = hashlib.sha1(_SYNTHETIC_VALUE.encode("utf-8")).hexdigest()
    assert fingerprint not in message

    audit = repo / "services" / "platform-core" / "runtime" / "tracked-secret-delta-audit.json"
    assert audit.is_file()
    document = json.loads(audit.read_text(encoding="utf-8"))
    rows = document["rows"]
    assert {row["path"] for row in rows} == {"tracked.py"}
    assert {row["type"] for row in rows} == {
        "Secret Keyword",
        "Base64 High Entropy String",
    }
    assert all(row["hashes"] == [fingerprint] for row in rows)
    assert all(row["classification"] == "unclassified" for row in rows)
    assert _SYNTHETIC_VALUE not in audit.read_text(encoding="utf-8")


def test_scan_driver_preserves_logger_state_and_accounting_on_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review 1 MEDIUM direct regression: the scan driver must never corrupt
    the pinned scanner logger state, neither on the success path nor on the
    exception path, and the per-file ``Checking file:`` accounting must
    survive both. Importing the driver mutates nothing; ``main`` raises the
    level for the accounting and restores the exact previous level in a
    ``finally``. Records are captured through an explicitly attached
    ``logging.Handler`` on the real pinned logger (the supported capture
    mechanism), never through root propagation -- so the test cannot
    silently pass or fail on the logger's ``propagate`` setting."""
    import io
    import logging

    from detect_secrets.core import log as scanner_log
    from detect_secrets.core import scan as scan_module

    repo = _init_repo(tmp_path / "logger-repo")
    (repo / "first.py").write_text("# synthetic\n", encoding="utf-8")
    (repo / "second.py").write_text("# synthetic\n", encoding="utf-8")
    paths = ["first.py", "second.py"]
    level_before = scanner_log.log.level
    propagate_before = scanner_log.log.propagate
    monkeypatch.chdir(repo)

    captured: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    def _handler_state() -> list[tuple[str, int, int]]:
        """Exact handler state: class, level and object identity -- so a
        replaced or re-leveled handler can never compare equal."""
        return [(type(h).__name__, h.level, id(h)) for h in scanner_log.log.handlers]

    def _accounted_messages() -> list[str]:
        return [
            record.getMessage()
            for record in captured
            if record.getMessage().startswith(check_secret_baseline._CHECKING_FILE_PREFIX)
        ]

    handlers_before = _handler_state()
    capture_handler = _CaptureHandler(level=logging.DEBUG)
    scanner_log.log.addHandler(capture_handler)
    handlers_with_capture = _handler_state()
    try:
        # Success path: both files scanned in-process; the pinned logger
        # state is exactly what it was before, and every file is accounted
        # exactly once on the scanner's own INFO channel.
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(paths) + "\n"))
        assert _detect_secrets_scan_driver.main() == 0
        assert scanner_log.log.level == level_before
        assert _handler_state() == handlers_with_capture
        assert scanner_log.log.propagate == propagate_before
        success_accounting = _accounted_messages()
        assert success_accounting.count(
            f"{check_secret_baseline._CHECKING_FILE_PREFIX}first.py"
        ) == 1
        assert success_accounting.count(
            f"{check_secret_baseline._CHECKING_FILE_PREFIX}second.py"
        ) == 1
        assert len(success_accounting) == len(paths)

        # Exception path: a scanner crash mid-run propagates (the caller fails
        # closed) and must leave the logger state unchanged too; the accounting
        # line of the file scanned before the crash stays intact.
        captured.clear()
        original_scan_file = scan_module.scan_file
        calls = {"count": 0}

        def _exploding_scan_file(filename: str):
            if calls["count"] >= 1:
                raise RuntimeError("synthetic scanner failure")
            calls["count"] += 1
            yield from original_scan_file(filename)

        monkeypatch.setattr(scan_module, "scan_file", _exploding_scan_file)
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(paths) + "\n"))
        with pytest.raises(RuntimeError):
            _detect_secrets_scan_driver.main()
        assert scanner_log.log.level == level_before
        assert _handler_state() == handlers_with_capture
        assert scanner_log.log.propagate == propagate_before
        assert (
            f"{check_secret_baseline._CHECKING_FILE_PREFIX}first.py" in _accounted_messages()
        )
    finally:
        scanner_log.log.removeHandler(capture_handler)
        assert _handler_state() == handlers_before


def test_accounted_files_excludes_nested_probe_paths_by_basename() -> None:
    """Review HIGH direct regression: probe exclusion is basename-based and
    path-independent. The nested per-run runtime-directory probe path no
    longer starts with the prefix; the legacy repo-root form, the nested
    POSIX form and the nested Windows-separator form must all be excluded
    from the accounted set, while a non-probe file is accounted at any
    depth on either separator style."""
    prefix = check_secret_baseline._CHECKING_FILE_PREFIX
    stderr = (
        f"[scan]\tINFO\t{prefix}tracked/deep/file.py\n"
        f"[scan]\tINFO\t{prefix}.secrets-scan-probe-0-1234.txt\n"
        f"[scan]\tINFO\t{prefix}"
        "services/platform-core/runtime/secret-scan-probes/1234-ab/"
        ".secrets-scan-probe-1-1234.txt\n"
        f"[scan]\tINFO\t{prefix}"
        "services\\platform-core\\runtime\\secret-scan-probes\\1234-ab\\"
        ".secrets-scan-probe-2-1234.txt\n"
        f"[scan]\tINFO\t{prefix}deep\\nested\\nonprobe.py\n"
    ).encode("utf-8")
    accounted = check_secret_baseline._accounted_files(stderr)
    assert accounted == {"tracked/deep/file.py", "deep/nested/nonprobe.py"}


def test_exact_requested_accounted_set_with_nested_probe_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact requested/accounted equality on the success path: the nested
    sentinel probe rides in the chunk input and its Windows-separator
    accounting line is excluded by basename, so the accounted set equals the
    requested set exactly and the reconciliation passes."""
    repo, baseline = _tracked_repo(tmp_path)

    def _nested_probe_accounting(
        files: list[str], repo_root: Path
    ) -> subprocess.CompletedProcess[bytes]:
        completed = _driver_fake()(files, repo_root)
        probe_names = [
            name
            for name in files
            if Path(name).name.startswith(check_secret_baseline._PROBE_PREFIX)
        ]
        windows_probe_lines = (
            f"[scan]\tINFO\t{check_secret_baseline._CHECKING_FILE_PREFIX}"
            + name.replace("/", "\\")
            + "\n"
            for name in probe_names
        )
        stderr = completed.stderr + "".join(windows_probe_lines).encode("utf-8")
        return subprocess.CompletedProcess(
            args=completed.args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _nested_probe_accounting)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message


def test_accounted_file_outside_requested_set_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The error direction of the exact set: an accounting entry for a file
    outside the requested set (even a Windows-separator path) fails closed
    with status 2 instead of being silently tolerated."""
    repo, baseline = _tracked_repo(tmp_path)

    def _extra_accounting(
        files: list[str], repo_root: Path
    ) -> subprocess.CompletedProcess[bytes]:
        completed = _driver_fake()(files, repo_root)
        extra = (
            f"[scan]\tINFO\t{check_secret_baseline._CHECKING_FILE_PREFIX}"
            "evil\\outside.py\n"
        )
        stderr = completed.stderr + extra.encode("utf-8")
        return subprocess.CompletedProcess(
            args=completed.args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _extra_accounting)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "outside the requested set" in message
    assert "evil/outside.py" in message


@pytest.mark.parametrize(
    "behavior, expected_calls, expected_status",
    [
        ("flaky-then-success", 2, 0),
        (
            "persistent-transient",
            1 + len(check_secret_baseline._SPAWN_RETRY_DELAYS),
            2,
        ),
        ("non-transient", 1, 2),
    ],
    ids=["retried-then-succeeds", "persistent-transient-fails-closed", "non-transient-not-retried"],
)
def test_git_start_failure_retry_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
    expected_calls: int,
    expected_status: int,
) -> None:
    """Gazda-független szimuláció: a predikátum True, a subprocess a
    dokumentált 0xC0000142-vel (vagy nem-transiens 1-gyel) bukik."""
    calls: list[int] = []
    if behavior == "flaky-then-success":
        repo = _init_repo(tmp_path / "repo")
        (repo / "x.py").write_text("# synthetic\n", encoding="utf-8")
        baseline = _empty_baseline(repo)
        _git(repo, "add", "x.py", baseline.name)
        _commit(repo)
    else:
        baseline = _empty_baseline(tmp_path)

    def _fake_ls_files(*args, **kwargs):
        calls.append(1)
        if behavior == "non-transient":
            raise subprocess.CalledProcessError(1, "git ls-files")
        if behavior == "persistent-transient" or len(calls) == 1:
            raise subprocess.CalledProcessError(3221225794, "git ls-files")
        return b"100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0\tx.py\0"

    monkeypatch.setattr(
        check_secret_baseline,
        "_is_transient_windows_start_failure",
        lambda rc: rc == 3221225794,
    )
    monkeypatch.setattr(check_secret_baseline.subprocess, "check_output", _fake_ls_files)
    if behavior == "flaky-then-success":
        status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    else:
        status, message = check_secret_baseline.reconcile_tracked_secrets(
            baseline, repo_root=check_secret_baseline.REPO_ROOT
        )
    assert len(calls) == expected_calls
    assert status == expected_status
    if expected_status == 2:
        assert "git ls-files failed" in message


@pytest.mark.parametrize(
    "behavior, expected_runs",
    [
        ("flaky-then-success", 2),
        ("persistent-transient", 1 + len(check_secret_baseline._SPAWN_RETRY_DELAYS)),
    ],
    ids=["retried-then-succeeds", "persistent-transient-fails-closed"],
)
def test_driver_start_failure_retry_contract(
    monkeypatch: pytest.MonkeyPatch, behavior: str, expected_runs: int
) -> None:
    runs: list[int] = []

    def _flaky_scan(args, **kwargs):
        runs.append(1)
        files = kwargs["input"].decode("utf-8").splitlines()
        if behavior == "persistent-transient" or len(runs) == 1:
            return subprocess.CompletedProcess(
                args=["scan-driver"], returncode=3221225794, stdout=b"", stderr=b""
            )
        return _driver_fake()(files, check_secret_baseline.REPO_ROOT)

    monkeypatch.setattr(
        check_secret_baseline,
        "_is_transient_windows_start_failure",
        lambda rc: rc == 3221225794,
    )
    monkeypatch.setattr(check_secret_baseline.subprocess, "run", _flaky_scan)
    files = ["services/platform-core/app/seed.py"]
    if behavior == "flaky-then-success":
        assert check_secret_baseline._live_scan(files, check_secret_baseline.REPO_ROOT) == {
            "results": {}
        }
    else:
        with pytest.raises(check_secret_baseline.ScanFailure) as excinfo:
            check_secret_baseline._live_scan(files, check_secret_baseline.REPO_ROOT)
        assert "scan driver exit code 3221225794" in str(excinfo.value)
    assert len(runs) == expected_runs
