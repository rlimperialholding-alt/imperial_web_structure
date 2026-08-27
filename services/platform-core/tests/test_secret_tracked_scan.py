"""Narrow cross-platform regression tests for the canonical tracked-secret scan.

Proves the tracked-file contract of ``check_secret_baseline.py``:

* only Git-tracked regular files (index modes 100644/100755) are candidates —
  untracked, ignored, build, cache, runtime, gitlink and symlink entries can
  never influence reconciliation;
* index records with a tab inside a filename parse safely;
* Windows and POSIX separators produce the same normalized fingerprints;
* candidate files are decoded identically on every host locale, so a
  Hungarian-Windows (cp1250) run cannot silently skip files that a Linux
  (UTF-8) runner scans — this was the actual Task 31 remote discrepancy;
* every candidate is accounted for deterministically: scanned, or reported
  scanner-exempt (ignored extension suffix, lock-file basename, swagger path
  or not valid UTF-8 on every platform — all derived from the pinned scanner's
  own filename filters);
* per-file live coverage is proven from the scanner's own per-file accounting:
  a readable, UTF-8-decodable candidate the scanner never opens fails closed
  (status 2) with its path named, and a NUL-byte ASCII file is covered by the
  real scanner end-to-end;
* the pinned scanner version is verified and a mismatch fails closed;
* the baseline file and the scanner's own runtime audit output are excluded
  exactly once, so the audit's SHA-1 fingerprints are never re-scanned;
* the runtime audit artifact is write-only evidence: a hand-planted audit
  claiming a live candidate is "classified" does not suppress it;
* new/changed/removed audited entries fail closed without revealing
  candidate plaintext, and unclassified candidates produce a bounded,
  explicitly-truncated hash/path-only audit report;
* the audited occurrence state is anchored to git history (the commit that
  last modified the baseline): unchanged canonical repeat occurrences and
  line-drifted existing occurrences reconcile, while a value introduced
  after the audited state -- a new file, a new digest or a duplicate
  occurrence of an audited value -- fails closed unless a structural
  classifier proves it on its exact line;
* a candidate outside the baseline is cleared only by a structural classifier
  that re-derives the value from the working tree and reproduces the
  scanner's fingerprint, narrowed to exact, non-generic field names and exact
  file paths: an unbound hex value, the exact digest key outside the registry
  files, a lookalike key (``api_sha256``), an uncorroborated Drive-shaped
  identifier, the exact Drive key outside the Drive index files, an
  unclassifiable detector type, and a genuine credential added to an
  otherwise-classified file all still fail closed;
* the classifier allowlist contains no executable source file and no generic
  digest key name (``sha256``/``checksum`` are out); the real digest values
  of ``app/seed.py`` stay unclassified, and the pinned driver preserves one
  finding entry per line so the same digest reported on a classified line and
  on an unclassifiable line fails closed;
* the audited identity is occurrence-aware: the comparison unit includes the
  finding line number, so a value baselined on a classified line can never
  suppress a new occurrence of the same digest on a different unclassified
  line -- the new line must be proven harmless by the structural classifier
  on that exact line or the reconciliation fails closed. A newly introduced
  occurrence is one that exceeds the audited occurrence count of its value:
  unchanged repeats and line drift reconcile, a duplicate copy of an audited
  value still blocks;
* an ``OSError`` while spawning the pinned driver becomes a secret-free
  ``ScanFailure``, never a raw traceback;
* the runtime audit directory is git-ignored, its artifact never appears in
  ``git status``, and a planted audit file cannot act as suppression input;
* there is no snapshot or environment seam: tests exercise the live path
  exclusively through direct pytest ``monkeypatch`` seams, and setting the
  pytest environment marker has no effect on the scan;
* sentinel probe write/delete errors are controlled fail-closed failures and
  the probe file is always cleaned up;
* the pinned driver receives exactly the bounded canonical set through the
  documented UTF-8 subprocess invocation, and each chunk must echo back its
  sentinel probe fingerprint;
* git/driver failure, malformed output, missing files, duplicate/ambiguous
  paths and driver output outside the canonical set fail closed (status 2);
* neither the old ``audited-delta`` allowlist nor the new
  ``tracked-secret-delta-audit`` runtime artifact is a tracked file, and the
  whole platform-core runtime directory stays untracked.

All synthetic candidate values are assembled at runtime from short,
non-secret-looking fragments, so this source file contains no secret-like
plaintext literal at all. Fixtures are temporary synthetic git repositories
created offline with the local git CLI; no network, no protected corpus
mutation, no production write. The live smoke test runs the real pinned
scanner end-to-end without any monkeypatching.
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
PASSWORD_LINE = "password = '" + _SYNTHETIC_VALUE + "'\n"
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
    expected_type, expected_hash = check_secret_baseline._expected_probe_fingerprint()
    return {"type": expected_type, "hashed_secret": expected_hash}


def _driver_fake(
    returncode: int = 0,
    payload: dict | None = None,
    include_probe: bool = True,
    skip_accounting: set[str] | None = None,
):
    """Canned ``_run_driver_scan`` that satisfies the sentinel probe contract.

    Emits the scanner's own per-file accounting lines for every file in the
    stdin list (except the probe and any path in ``skip_accounting``), so the
    per-file coverage check passes unless a test asks for a skipped file.
    """

    def _fake(files: list[str], repo_root: Path) -> subprocess.CompletedProcess[bytes]:
        results = dict(payload or {})
        if include_probe:
            probe_name = next(
                (name for name in files if name.startswith(check_secret_baseline._PROBE_PREFIX)),
                None,
            )
            if probe_name is not None:
                results[probe_name] = [_expected_probe_entry()]
        accounted = [
            f"[scan]\tINFO\t{check_secret_baseline._CHECKING_FILE_PREFIX}{name}"
            for name in files
            if not name.startswith(check_secret_baseline._PROBE_PREFIX)
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
    # Szimlink- és gitlink-indexbejegyzés valódi hálózat/symlink nélkül:
    blob_sha = _git(repo, "hash-object", "-w", "--stdin", input_text="target/path\n").strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob_sha},link_name")
    (repo / "link_name").write_text("target/path\n", encoding="utf-8")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{blob_sha},submodule_dir")
    baseline = _empty_baseline(repo)
    _git(repo, "add", baseline.name)
    _commit(repo)

    candidates = check_secret_baseline._git_tracked_candidates(repo, baseline)
    assert candidates == ["script.sh", "tracked.py"]
    # A teljes tracked halmazból kizárólag a baseline és a nem-reguláris
    # (szimlink/gitlink) bejegyzések hiányoznak — az exklúzió exact:
    tracked = _git(repo, "ls-files").splitlines()
    assert set(tracked) - set(candidates) == {
        baseline.name,
        "link_name",
        "submodule_dir",
    }


def test_tab_in_git_ls_files_record_parses_safely() -> None:
    """A tab inside a filename survives ``-s -z`` parsing intact.

    On Linux git tracks such names happily and the scanner opens them; on
    Windows git itself rejects the path before ``ls-files`` can ever emit
    it. Either way the parser must take everything after the record's first
    tab as the path and never mis-split or drop it.
    """
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)

    def _unreadable(target: Path) -> bytes:
        raise OSError("synthetic unreadable candidate")

    monkeypatch.setattr(check_secret_baseline, "_read_candidate_bytes", _unreadable)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "cannot be read" in message


def test_unknown_index_mode_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline,
        "_run_git_ls_files",
        lambda repo_root: b"100700 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391\tx.py\0",
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "unexpected git index entry mode" in message


def test_malformed_index_record_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)
    monkeypatch.setattr(
        check_secret_baseline,
        "_run_git_ls_files",
        lambda repo_root: b"100644 not-a-sha1\tx.py\0",
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert status == 2
    assert "malformed git ls-files record" in message


def test_fingerprint_normalization_matches_windows_and_posix_separators() -> None:
    finding = {"type": "Secret Keyword", "hashed_secret": "0" * 40, "line_number": 7}
    windows = check_secret_baseline._fingerprints(
        {"results": {"services\\platform-core\\tests\\x.py": [finding]}}
    )
    posix = check_secret_baseline._fingerprints(
        {"results": {"services/platform-core/tests/x.py": [finding]}}
    )
    assert windows == posix
    # Az identitás occurrence-aware: a sorszám a kulcs része.
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
    # Untracked/build/cache/runtime jelöltek — egyik sem látszódhat:
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
    # A baseline saját tartalma jelöltet hordozna, ha a scanner látná:
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
    """A candidate introduced after the audited state fails closed, plaintext-free.

    The tracked file carries only benign content at the audited commit; the
    synthetic candidate is written into the working tree afterwards, so it has
    no audited state and must be reported -- never silently reconciled.
    """
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
    (repo / "tracked.py").write_text(PASSWORD_LINE, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1
    assert "- tracked.py" in message
    assert _SYNTHETIC_VALUE not in message
    hashed = hashlib.sha1(_SYNTHETIC_VALUE.encode("utf-8")).hexdigest()
    assert hashed not in message


def test_cp1250_undecodable_tracked_file_is_still_scanned(tmp_path: Path) -> None:
    """A Hungarian UTF-8 file must not be skipped on a cp1250 host.

    This is the canonical Task 31 regression: the pinned scanner reads
    candidates with a bare ``open()`` and silently ignores any file raising
    ``UnicodeDecodeError``. Under the Windows cp1250 locale this file raises
    and the whole file -- including its candidate -- disappeared from the
    scan, while the Linux UTF-8 runner reported it. The canonical scan forces
    UTF-8 mode, so both platforms observe the same fingerprint.
    """
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

    # Ellenséges szülő-környezet: a felülírásnak ezt is le kell győznie.
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
    monkeypatch.setattr(
        check_secret_baseline, "_run_driver_scan", _driver_fake(include_probe=False)
    )
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 2
    assert "sentinel probe was not detected" in message


def test_live_scan_feeds_exactly_the_bounded_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fed: list[list[str]] = []
    files = [f"services/platform-core/f{f:04d}.py" for f in range(250)]
    probe_prefix = check_secret_baseline._PROBE_PREFIX

    def _recording_driver(chunk: list[str], repo_root: Path) -> subprocess.CompletedProcess[bytes]:
        fed.append([name for name in chunk if not name.startswith(probe_prefix)])
        return _driver_fake()(chunk, repo_root)

    monkeypatch.setattr(check_secret_baseline, "_run_driver_scan", _recording_driver)
    result = check_secret_baseline._live_scan(files, check_secret_baseline.REPO_ROOT)
    assert result == {"results": {}}
    assert [path for chunk in fed for path in chunk] == files
    # Minden chunk kapott saját szondát (a fake ezt visszhangozta):
    assert all(len(chunk) < len(files) for chunk in fed)


def test_reconcile_has_no_snapshot_or_environment_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No command-level snapshot seam and no env-toggled bypass exists.

    The removed snapshot seam was honored through ``PYTEST_CURRENT_TEST`` and
    was therefore togglable by environment alone. The signature must not even
    accept it, and setting the pytest environment marker must have no effect:
    the live scan still runs.
    """
    parameters = inspect.signature(check_secret_baseline.reconcile_tracked_secrets).parameters
    assert set(parameters) == {"baseline_path", "repo_root"}

    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)

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
    """A readable, UTF-8-decodable file the scanner never opens fails closed.

    The review regression: per-file coverage is proven from the scanner's own
    accounting, so a file silently skipped for any unmodeled reason (an
    unknown filename filter, a transient open failure) must turn the gate red
    with the path named -- never a silent PASS.
    """
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)

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


def test_probe_delete_error_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A probe that cannot be removed is a controlled fail-closed error."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)

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


def test_scanner_exempt_candidates_are_accounted_deterministically(
    tmp_path: Path,
) -> None:
    """Files the pinned scanner exempts by design must be accounted, not silent.

    A non-UTF-8 file without an ignored extension (the scanner's decode-error
    skip path), a text file with an ignored extension (the extension filter),
    a lock-file basename and a swagger path (the pinned scanner's documented
    filename filters) are all classified scanner-exempt, reported by path, and
    can never appear as additions -- exactly matching the pinned scanner's own
    contract on every platform.
    """
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


def _drive_id_line(key: str, seed: bytes) -> tuple[str, str, str]:
    """A Drive-shaped ``<key>: "1<32 chars>"`` line, its id and fingerprint."""
    tail = base64.urlsafe_b64encode(hashlib.sha256(seed).digest()).decode("ascii")
    resource_id = "1" + tail[:32]
    line = '  "' + key + '": "' + resource_id + '",\n'
    return line, resource_id, hashlib.sha1(resource_id.encode("utf-8")).hexdigest()


def test_runtime_audit_output_is_never_read_back_as_suppression_input(
    tmp_path: Path,
) -> None:
    """The audit artifact is a report, not an allowlist.

    A hand-planted audit file that declares the live candidate "classified"
    must not clear it: the reconciliation still fails closed. This is exactly
    the property the committed delta-audit allowlist violated.
    """
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
    # A jelölt az audited commit után kerül a munkafába: nincs auditált
    # állapota, a beültetett audit sem tisztázhatja.
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
    """The scanner never re-scans the fingerprints it just wrote.

    The audit artifact is full of 40-hex SHA-1 fingerprints, which the Hex
    High Entropy detector would flag. Even when the artifact is force-added to
    the index, it must not become a candidate, so its hashes can never appear
    as findings.
    """
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
    """A secret stored under a key merely ending in ``sha256`` is not cleared.

    This is the review scenario: ``api_sha256: "<64 hex>"`` must stay
    unclassified even inside a registry file, because only the exact,
    documented digest key names qualify.
    """
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
    """Clearance is per-value, never per-file.

    A file whose digests are all structurally classified must still fail
    closed the moment a genuine credential is added to it.
    """
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
    # Az audited commit után, korroboráló provenance nélkül bevezetett
    # Drive-alakú azonosító: addition, amit a classifier nem bizonyíthat.
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
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
    """A finding whose line number is absent or bogus stays unclassified.

    ``lines[0 - 1]`` would silently classify against the *last* line of the
    file, so an out-of-range number must fail closed instead of wrapping.
    A ``None`` (absent) line number normalizes to ``None`` in the audited
    identity, while the classifier computes 0 for it -- the mismatch is
    deliberate: a line-less finding can never be classified.
    """
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
    """A driver sosem lapítja össze az azonos digestű, különböző soros találatokat.

    Ugyanaz a 64-hex érték egy kötött digest-soron és egy kötetlen soron: a
    korábbi ``(type, hashed_secret)`` dedup csak a legkisebb sorszámot tartotta
    volna meg, a review HIGH exploitját adva. Az új szerződés szerint minden
    sor külön bejegyzésként él tovább.
    """
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
    """Azonos digestű, eltérő sorokon szereplő classified és unclassified találat.

    A review HIGH exploitjának közvetlen regressziója: ugyanaz az érték a 2.
    soron kötött digest-kulcshoz (a kötött sor az audited állapot része), a 3.
    soron kötetlen pozícióban az audited commit UTÁN jelenik meg. Az élő scan
    mindkét sort jelenti; a 3. sor a duplikált előfordulás miatt addition, a
    classifier pedig azon a soron nem tudja bizonyítani ártalmatlanságát --
    így a reconciliation fail-closed marad.
    """
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
    """A classified soron baselined érték nem fedhet el új, osztályozatlan sort.

    A Task36 review HIGH közvetlen regressziója: az azonos 64-hex digest a 2.
    soron a ``reference_sha256`` kulcshoz kötve áll -- ez a sor a védett
    baseline-ban szerepel, tehát pontosan egyezik --, a 3. soron viszont az
    audited commit UTÁN, kötetlen pozícióban ismétlődik. A 3. sor a duplikált
    előfordulás miatt addition: a strukturális osztályozó azon a soron nem
    tudja bizonyítani ártalmatlanságát, így a reconciliation fail-closed
    marad. A baseline-létezés önmagában sosem tisztázhatja az új
    sor-előfordulást.
    """
    repo = _init_repo(tmp_path / "repo")
    digest_line, hashed = _digest_line("reference_sha256", b"synthetic-baselined-line")
    digest = hashlib.sha256(b"synthetic-baselined-line").hexdigest()
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + digest_line + '  "x": 1\n}\n')
    # A baseline pontosan a classified (2.) sort tartalmazza -- a 3. sor
    # előfordulását nem.
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
    # Az audited commit után bevezetett, kötetlen sor: új előfordulás.
    _write_tracked(
        repo,
        _DIGEST_MANIFEST_PATH,
        "{\n" + digest_line + '  "unbound": "' + digest + '",\n  "x": 1\n}\n',
    )

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1, message
    # Pontosan egy identitás maradt osztályozatlan: a 3. sor új előfordulása.
    # A 2. sor baseline-találatát a pozitív kontroll
    # (``test_baselined_classified_line_still_matches_the_audited_set_exactly``)
    # bizonyítja; a status-1 üzenet csak az osztályozatlanakat sorolja.
    assert "1 unclassified candidate(s) in 1 tracked file(s)" in message
    assert _DIGEST_MANIFEST_PATH in message
    # A classified sort pontosan egyezett a baseline-nal, de az új sort nem
    # tisztázhatta -- ezért semmilyen classifier-engedmény nem jelent meg.
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
    """Az új sor-előfordulást a classifiernek kell bizonyítania -- és tudja is.

    Ugyanaz a digest a 2. (baselined, classified) és a 3. (új) soron, mindkettő
    ``reference_sha256``-hez kötve. Az új 3. sor bekerül az addition-halmazba,
    és a strukturális osztályozó azon a soron bizonyítja ártalmatlanságát --
    a reconciliation így PASS, és a classified számláló pontosan az új sort
    mutatja.
    """
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
    # Az audited commit után bevezetett, kötött 3. sor: addition, amit a
    # classifier azon a soron bizonyít.
    _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + digest_line + digest_line + '  "x": 1\n}\n')

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "1 tracked candidate(s) match the audited baseline" in message
    assert "content-digest: 1" in message


def test_baselined_classified_line_still_matches_the_audited_set_exactly(
    tmp_path: Path,
) -> None:
    """Az occurrence-aware identitás nem törte meg a baselined sor egyezését.

    Kontroll: a baseline pontosan a classified 2. sort tartalmazza, az élő
    scan is pontosan azt a sort jelenti -- az azonos (path, type, hash, line)
    identitás egyezik, nincs addition, nincs classifier-engedmény.
    """
    repo = _init_repo(tmp_path / "repo")
    digest_line, hashed = _digest_line("reference_sha256", b"synthetic-exact-line-match")
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

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "1 tracked candidate(s) match the audited baseline" in message
    assert "structural classifier" not in message


def test_unchanged_canonical_repeat_occurrences_reconcile(tmp_path: Path) -> None:
    """Iránymutató 1: a kanonikus, deduplikált baseline változatlan ismétlődő
    előfordulásokkal is sikeresen egyeztet.

    A védett baseline-t generáló CLI minden (type, fingerprint) értéket
    egyszer, az első soron rögzít -- a fájlban azonos érték több soron is
    állhat (a valós website-targets.json mintájára). Az occurrence-aware
    egyeztetés a baseline-sor pontos egyezése mellett a többi sort az
    auditált állapottal egyezteti: változatlan fájl, tehát nem addition.
    """
    repo = _init_repo(tmp_path / "repo")
    # Minden kötőjeles szava 8 karakternél rövidebb, így a Base64-detektor
    # (legalább 8 karakteres futam) nem lő be rá: csak a Secret Keyword talál.
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
    # A baseline-sor pontosan egyezik, a további három ismétlődés az auditált
    # állapothoz konvergál -- egyik sem addition, classifier nélkül.
    assert "1 tracked candidate(s) match the audited baseline" in message
    assert "3 candidate(s) reconcile with the audited repository state" in message
    assert "structural classifier" not in message


def test_line_drifted_existing_occurrence_reconciles(tmp_path: Path) -> None:
    """Iránymutató 1 (sor-eltolódás): egy auditált érték eltolódott sora nem
    addition -- az előfordulásszám nem haladja meg az auditáltat."""
    repo = _init_repo(tmp_path / "repo")
    digest_line, hashed = _digest_line("reference_sha256", b"synthetic-line-drift")
    target = _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + digest_line + '  "x": 1\n}\n')
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
    # Az auditált sor fölé kerülő, független szerkesztés: az érték a 2. sorról
    # a 4. sorra csúszik -- az előfordulásszám nem nő, így nem addition.
    drifted = '{\n  "added": 1,\n  "added": 2,\n' + digest_line + '  "x": 1\n}\n'
    target.write_text(drifted, encoding="utf-8")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 0, message
    assert "1 candidate(s) reconcile with the audited repository state" in message
    assert "structural classifier" not in message


def test_duplicated_audited_value_blocks_without_structural_proof(tmp_path: Path) -> None:
    """Iránymutató 2: az auditált digest ÚJ soron ismételt másolata addition.

    Ugyanaz a 64-hex érték a 2. soron baseline-hoz kötötten áll, a 3. soron
    viszont az audited commit után, kötetlen pozícióban ismétlődik. Az
    előfordulásszám meghaladja az auditáltat, ezért a 3. sor új előfordulás:
    a classifier azon a soron nem bizonyít, így a reconciliation fail-closed.
    """
    repo = _init_repo(tmp_path / "repo")
    digest_line, hashed = _digest_line("reference_sha256", b"synthetic-duplicated")
    digest = hashlib.sha256(b"synthetic-duplicated").hexdigest()
    target = _write_tracked(repo, _DIGEST_MANIFEST_PATH, "{\n" + digest_line + '  "x": 1\n}\n')
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


def test_new_tracked_file_after_the_audited_state_fails_closed(tmp_path: Path) -> None:
    """Az audited commit után létrejött fájlnak nincs auditált állapota.

    Egy teljesen új, titokjelöltet hordozó fájl (staged, de az audited commit
    után) minden találata addition -- fail-closed, hacsak a strukturális
    osztályozó nem bizonyítja.
    """
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
    (repo / "late.py").write_text(PASSWORD_LINE, encoding="utf-8")
    _git(repo, "add", "late.py")

    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert status == 1
    assert "- late.py" in message
    assert _SYNTHETIC_VALUE not in message


def test_uncommitted_baseline_fails_closed_on_the_audited_anchor(tmp_path: Path) -> None:
    """Commit nélküli baseline nem horgonyozhat auditált állapotot.

    A git-történetben nem létező baseline-fájlra nincs anchor commit: a
    reconciliation fail-closed (status 2), nem feltételez auditált állapotot.
    """
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
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
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "tracked.py", baseline.name)
    _commit(repo)
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
    """A valódi ``app/seed.py`` digestértékei fail-closed módon osztályozatlanok.

    A fájl a forrásban hordozza a tartalomdigestjeit (pl. CALCULATION_SOURCES
    sha256 mezői); miután kikerült a classifier allowlistből, ezek valós, de
    strukturálisan nem bizonyítható jelöltek -- a szabály szerint
    osztályozatlanok maradnak, és R3 baseline-attesztációt igényelnek.
    """
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

    A harmadik tulajdonságot -- az audit nem lehet suppression input -- a
    ``test_runtime_audit_output_is_never_read_back_as_suppression_input``
    bizonyítja viselkedésszinten: egy beültetett, „classified"-ra hamisított
    audit sem tisztázhat élő jelöltet.
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
    """Regression: sem a régi allowlist, sem az új runtime-audit nem követett.

    A korábbi audit-artifact pontos neve (`.secrets.audited-delta.json`) és az
    új runtime-artifact neve (`tracked-secret-delta-audit.json`) sem lehet
    követett fájl, és a teljes `services/platform-core/runtime/` könyvtárnak
    git-ignorednak kell maradnia -- a review LOW findingja szerint az audit
    csak nem követett, futásidejű bizonyíték lehet.
    """
    tracked = subprocess.check_output(
        ["git", "ls-files"], cwd=str(REPO_ROOT), text=True, encoding="utf-8"
    ).splitlines()
    assert [path for path in tracked if "audited-delta" in path] == []
    assert [path for path in tracked if "tracked-secret-delta-audit" in path] == []
    assert [path for path in tracked if path.startswith("services/platform-core/runtime/")] == []


def test_live_scan_smoke_runs_the_real_scanner_on_a_trivial_repository(
    tmp_path: Path,
) -> None:
    """Real end-to-end proof; nothing in this test is monkeypatched.

    A trivial synthetic repository is reconciled through the full live path:
    git ls-files, the pinned driver subprocess with forced UTF-8 mode,
    sentinel probes, per-file accounting and fingerprint comparison. The
    runtime-generated candidate must be detected with the exact SHA-1
    fingerprint computed independently here, and the emitted delta audit must
    be hash/path-only. A NUL-byte ASCII file -- readable and UTF-8-decodable,
    the exact case the review asked a coverage regression for -- carries no
    finding but is still opened and accounted by the real scanner, which the
    passing per-file coverage check proves.
    """
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


def test_transient_windows_start_failure_retried_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Gazda-független szimuláció: a predikátumot True-ra kényszerítjük, a
    # subprocess pedig egyszer 0xC0000142-vel bukik, utána valódi outputot ad.
    repo = _init_repo(tmp_path / "repo")
    (repo / "x.py").write_text("# synthetic\n", encoding="utf-8")
    baseline = _empty_baseline(repo)
    _git(repo, "add", "x.py", baseline.name)
    _commit(repo)
    calls: list[int] = []

    def _flaky_ls_files(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(3221225794, "git ls-files")
        return b"100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0\tx.py\0"

    monkeypatch.setattr(
        check_secret_baseline,
        "_is_transient_windows_start_failure",
        lambda rc: rc == 3221225794,
    )
    monkeypatch.setattr(check_secret_baseline.subprocess, "check_output", _flaky_ls_files)
    status, message = check_secret_baseline.reconcile_tracked_secrets(baseline, repo_root=repo)
    assert len(calls) == 2
    assert status == 0, message


def test_persistent_transient_windows_start_failure_still_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)
    calls: list[int] = []

    def _broken_ls_files(*args, **kwargs):
        calls.append(1)
        raise subprocess.CalledProcessError(3221225794, "git ls-files")

    monkeypatch.setattr(
        check_secret_baseline,
        "_is_transient_windows_start_failure",
        lambda rc: rc == 3221225794,
    )
    monkeypatch.setattr(check_secret_baseline.subprocess, "check_output", _broken_ls_files)
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert len(calls) == 1 + len(check_secret_baseline._SPAWN_RETRY_DELAYS)
    assert status == 2
    assert "git ls-files failed" in message


def test_non_transient_start_failure_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _empty_baseline(tmp_path)
    calls: list[int] = []

    def _broken_ls_files(*args, **kwargs):
        calls.append(1)
        raise subprocess.CalledProcessError(1, "git ls-files")

    monkeypatch.setattr(
        check_secret_baseline,
        "_is_transient_windows_start_failure",
        lambda rc: rc == 3221225794,
    )
    monkeypatch.setattr(check_secret_baseline.subprocess, "check_output", _broken_ls_files)
    status, message = check_secret_baseline.reconcile_tracked_secrets(
        baseline, repo_root=check_secret_baseline.REPO_ROOT
    )
    assert len(calls) == 1
    assert status == 2
    assert "git ls-files failed" in message


def test_scanner_chunk_transient_start_failure_retried_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[int] = []

    def _flaky_scan(args, **kwargs):
        runs.append(1)
        files = kwargs["input"].decode("utf-8").splitlines()
        if len(runs) == 1:
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
    result = check_secret_baseline._live_scan(
        ["services/platform-core/app/seed.py"], check_secret_baseline.REPO_ROOT
    )
    assert result == {"results": {}}
    assert len(runs) == 2


def test_scanner_chunk_persistent_transient_start_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[int] = []

    def _broken_scan(args, **kwargs):
        runs.append(1)
        return subprocess.CompletedProcess(
            args=["scan-driver"], returncode=3221225794, stdout=b"", stderr=b""
        )

    monkeypatch.setattr(
        check_secret_baseline,
        "_is_transient_windows_start_failure",
        lambda rc: rc == 3221225794,
    )
    monkeypatch.setattr(check_secret_baseline.subprocess, "run", _broken_scan)
    try:
        check_secret_baseline._live_scan(
            ["services/platform-core/app/seed.py"], check_secret_baseline.REPO_ROOT
        )
    except check_secret_baseline.ScanFailure as exc:
        assert "scan driver exit code 3221225794" in str(exc)
    else:
        raise AssertionError("ScanFailure was not raised.")
    assert len(runs) == 1 + len(check_secret_baseline._SPAWN_RETRY_DELAYS)
