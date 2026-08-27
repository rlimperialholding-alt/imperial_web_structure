"""Fail when tracked files contain secret candidates absent from the audited set.

The comparison logic lives in ``reconcile_tracked_secrets`` so the platform-core
local reconciliation command reuses exactly this canonical implementation
instead of duplicating a weaker parser. Messages never contain secret material;
only tracked file paths, counts and SHA-1 fingerprints are reported.

Tracked-file contract (canonical and cross-platform):

* the candidate file set is derived explicitly from ``git ls-files`` of the
  repository root: only regular-file index entries (modes 100644/100755) are
  candidates, so symlink/gitlink entries, untracked, ignored, build, cache and
  runtime files can never influence the result;
* index records are parsed with strict validation: an unknown index mode, a
  malformed record or non-UTF-8 index output fails closed, and a filename
  containing a tab character survives parsing intact (the path is everything
  after the record's first tab delimiter, which the format itself places
  before the path);
* the baseline file and this script's own runtime audit output are each
  excluded exactly once from that set, so the scanner can never re-scan the
  fingerprints it just wrote (the audit lives in a git-ignored directory, so
  the exclusion is defence in depth, not the only barrier);
* paths are normalized to forward slashes so Windows and POSIX produce the
  same keys, and the list is sorted so chunking is identical on every
  platform. A duplicate after normalization always fails closed; a pair of
  paths differing only by case fails closed only on case-insensitive
  platforms (determined with ``os.path.normcase``), because distinct names
  such as ``Module.py``/``module.py`` are legal on Linux;
* the pinned scanner is fed only that bounded set. The scan runs through a
  dedicated driver subprocess (``_detect_secrets_scan_driver.py``) that calls
  the pinned package's own ``scan.scan_file`` per file -- the exact code path
  the package CLI uses -- with the file list travelling on stdin, so there is
  no platform command-line length limit and no repository walk. The driver
  emits the deterministic results document on stdout and the scanner's own
  INFO accounting on stderr; the subprocess is forced into UTF-8 mode, because
  file *decoding* -- not file selection -- is the actual cross-platform
  divergence. The pinned scanner reads candidates with a bare ``open()`` and
  silently drops any file that raises ``UnicodeDecodeError`` (detect_secrets
  core/scan.py, "we flat out ignore binary files"). That default encoding is
  locale dependent: UTF-8 on GitHub's Linux runners, but cp1250 on a Hungarian
  Windows host. Hungarian UTF-8 text such as ``Ő`` (U+0150) encodes to
  ``C5 90``, and byte ``0x90`` is undefined in cp1250 -- so those files decode
  cleanly on Linux and raise on Windows, where the scanner then skips them
  entirely and under-reports. Forcing UTF-8 mode (and a pinned stdio
  encoding) makes both platforms decode identically and strictly increases
  Windows coverage; it never suppresses a finding;
* per-file coverage is proven, not assumed, in two layers. Before scanning,
  every candidate is classified deterministically into exactly one of two
  categories: scanned, or scanner-exempt -- the three filename-level filters
  of the pinned scanner (ignored extension suffix, lock-file basename such as
  ``package-lock.json``, ``swagger`` path), imported from the pinned package
  itself so they can never drift, plus content that is not valid UTF-8 and
  therefore undecodable on every platform. Exempt files are reported by path
  in the reconciliation message, so no file can disappear silently. After
  scanning, the driver's stderr accounting is parsed: the scanner logs one
  ``Checking file: <path>`` line for every file it actually opens, so a
  requested file absent from that accounting -- whatever the unmodeled reason
  -- fails closed with status 2. Each driver chunk additionally carries a
  synthetic sentinel probe whose known fingerprint must appear in that chunk's
  output, proving detection really worked in every invocation. Any git/driver
  error, missing candidate file, malformed driver output, duplicate or
  ambiguous path, lost chunk coverage, missing sentinel detection, missing
  per-file accounting or driver output outside the canonical set fails closed
  with status 2;
* the scanner version is pinned and verified, so a differently-versioned
  scanner cannot silently change fingerprints.

Audited-set contract:

* the audited set is exactly ``.secrets.baseline`` (protected; its rotation is
  a separate R3 attestation). There is no committed allowlist, delta file or
  suppression list next to it, and **no artifact this script writes is ever
  read back as input**. The audit output below is a report, never a filter:
  deleting it, corrupting it or hand-editing it cannot make a finding pass;
* a live candidate outside the baseline is cleared only by a *structural
  classifier* (see ``_STRUCTURAL_CLASSIFIERS``). A classifier does not trust a
  path, a filename or a remembered fingerprint: it re-reads the reported line
  from the working tree, extracts the token that the classifier itself
  considers non-secret by construction, and only clears the finding when
  ``sha1(token)`` reproduces the fingerprint the scanner reported. A real
  secret can therefore never inherit another value's clearance, and a
  classified file that later gains a genuine secret still fails closed. The
  two classes are narrow on both axes -- exact field name and exact file
  path -- and evidence-backed:
  ``content-digest`` (a 64-hex value bound on its own line to exactly one of
  ``reference_sha256``/``fragment_sha256``/``claim_snapshot_sha256``/
  ``source_sha256``/``checksum``/``sha256``, and only inside the repository's
  documented content-registry files) and ``drive-resource-id`` (a Google
  Drive/Docs resource identifier in the documented ``1`` + 32/43
  ``[A-Za-z0-9_-]`` form bound to exactly the ``id``/``sourceId`` key in the
  two documented Drive index files, which must additionally be corroborated by
  a Drive/Docs URL or an explicit ``drive`` provenance marker in the same
  file);
* every candidate that neither the baseline nor a structural classifier
  clears is **unclassified**, and unclassified means fail closed with status 1
  -- new detector types, new files and new value shapes all land here by
  default;
* residual risk, stated explicitly rather than implied: a classifier decides
  on *exact field name, exact file path and shape*, so a genuine secret
  deliberately stored in the exact cleared shape -- a hex-encoded 256-bit key
  written as ``reference_sha256`` inside one of the content-registry files, or
  a credential shaped like a Drive id under ``id``/``sourceId`` in a Drive
  index file that already references Drive -- would be cleared. Both require
  an attacker to control an exact field name inside an exact documented file,
  which is a reviewable source change, not a silent one. Extending either rule
  (more key names, more paths, more value shapes) is a security decision and
  needs a documented R3 attestation; it must never be done to make a red gate
  go green;
* a failing run additionally writes a *bounded* hash/path-only audit report
  (at most ``_AUDIT_MAX_ROWS`` rows and ``_AUDIT_MAX_HASHES_PER_ROW``
  fingerprints per row, with the truncated remainder counted explicitly, so
  the artifact stays short and reviewable) to the git-ignored
  ``<repo root>/services/platform-core/runtime/tracked-secret-delta-audit.json``.
  It is untracked runtime evidence: it documents the decision without
  revealing plaintext and without ever dirtying the tracked worktree;
* there is no snapshot or environment seam anywhere in this module: the live
  scan can never be bypassed from a command line or an environment variable.
  Tests exercise failure paths exclusively through direct pytest
  ``monkeypatch`` seams (pytest-bound, process-local), which cannot affect the
  command-level behavior of this script or of ``reconciliation.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = REPO_ROOT / ".secrets.baseline"
_BASELINE_EXCLUDE_REGEX = r"(^|[\\/])\.secrets\.baseline$"
_REGULAR_MODES = {"100644", "100755"}
# Symlink (120000) and gitlink (160000) entries are documented non-regular
# index entries and are never candidates; every other mode fails closed.
_KNOWN_INDEX_MODES = _REGULAR_MODES | {"120000", "160000"}
_SCAN_CHUNK_SIZE = 100
_SCAN_WORKERS = 2
# The scanner pinned by requirements-dev.txt. A different version may ship
# different detectors or entropy limits, which would silently change every
# fingerprint, so a mismatch fails closed instead of producing a delta.
_PINNED_SCANNER_VERSION = "1.5.0"
_SCANNER_DISTRIBUTION = "detect-secrets"
_DRIVER_PATH = Path(__file__).with_name("_detect_secrets_scan_driver.py")
# Decoding determinism, not cosmetics: see the module docstring. PYTHONUTF8
# forces the driver's bare ``open()`` calls to UTF-8 on every host, and
# PYTHONIOENCODING pins the JSON/stdout/stderr encodings we decode strictly,
# so an ambient locale or inherited PYTHONIOENCODING cannot alter the result.
_SCANNER_ENV_OVERRIDES = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
# Narrow, documented allowlist of transient Windows subprocess-start failures.
# Under heavy parallel suite load Windows can reject a fresh process with
# STATUS_DLL_INIT_FAILED (0xC0000142, exit code 3221225794); the identical
# spawn succeeds a moment later. Only this code, only on Windows, is retried
# with bounded short delays; every other failure stays fail-closed on the
# first attempt, and a persistent transient code still fails closed.
_SPAWN_RETRY_DELAYS = (0.2, 0.5)
_TRANSIENT_WINDOWS_START_CODES = {3221225794}
# Runtime artifact emitted only when live candidates remain unmatched; the
# platform-core ``runtime`` directory is git-ignored, so a passing gate never
# writes and even a failing gate never dirties the tracked worktree. This
# artifact is write-only for the scanner: nothing reads it back as input.
_UNMATCHED_AUDIT_RELATIVE_PATH = (
    "services",
    "platform-core",
    "runtime",
    "tracked-secret-delta-audit.json",
)
# The audit is a short review aid, not a data dump: a fail-closed run must stay
# readable even if thousands of candidates are unmatched. The truncated
# remainder is always reported as an explicit count, never silently dropped.
_AUDIT_MAX_ROWS = 25
_AUDIT_MAX_HASHES_PER_ROW = 5
_PROBE_PREFIX = ".secrets-scan-probe-"
_CHECKING_FILE_PREFIX = "Checking file: "


class ScanFailure(Exception):
    """Fail-closed scanner/git/candidate-set condition.

    Messages carry only paths, counts and fingerprints; never secret material.
    """


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _is_transient_windows_start_failure(returncode: int) -> bool:
    """True only for a documented transient Windows process-start failure."""
    return sys.platform == "win32" and returncode in _TRANSIENT_WINDOWS_START_CODES


def _is_case_insensitive_platform() -> bool:
    """Deterministic platform path semantics, via ``os.path.normcase``.

    Windows-style platforms fold case (normcase lowercases), so two tracked
    paths differing only by case are ambiguous there. POSIX-style platforms
    keep case, and such distinct paths are legal and must not be rejected.
    """
    return os.path.normcase("A") == os.path.normcase("a")


def _unmatched_audit_path(repo_root: Path) -> Path:
    return repo_root.joinpath(*_UNMATCHED_AUDIT_RELATIVE_PATH)


def _audit_output_relative_path() -> str:
    """The scanner's own audit output, as a normalized repository path."""
    return "/".join(_UNMATCHED_AUDIT_RELATIVE_PATH)


def _scanner_filename_predicates() -> tuple[Any, Any, Any]:
    """The pinned scanner's filename-level skip predicates.

    Imported from the pinned package itself so the exemption classification
    can never drift from what the scanner actually skips at the filename-filter
    level: ``is_non_text_file`` (exact ignored-extension suffix),
    ``is_lock_file`` (documented lock-file basenames such as
    ``package-lock.json``) and ``is_swagger_file`` (paths containing
    ``swagger``). ``is_invalid_file`` (not a regular file) is handled by the
    fail-closed existence check, and the baseline file by the explicit
    exclusions above.
    """
    try:
        from detect_secrets.filters.heuristic import (
            is_lock_file,
            is_non_text_file,
            is_swagger_file,
        )
    except ImportError as exc:
        raise ScanFailure("pinned scanner package is not importable.") from exc
    return (is_non_text_file, is_lock_file, is_swagger_file)


def _probe_secret_value() -> str:
    """Runtime-constructed synthetic value for the sentinel probe.

    Deliberately assembled at runtime so no secret-like plaintext literal
    exists anywhere in this source file; the scanner detects the probe line
    with the same detectors it applies to every candidate.
    """
    return "".join(("Synthetic", "PlaintextValue", "-1234567890-ABC"))


def _probe_line() -> str:
    return "password = '" + _probe_secret_value() + "'\n"


def _run_git_ls_files(repo_root: Path) -> bytes:
    """Run ``git ls-files`` once; bounded retry only for the documented
    transient Windows start failure. Module-local seam for the retry tests."""
    for attempt in range(1, len(_SPAWN_RETRY_DELAYS) + 2):
        try:
            return subprocess.check_output(
                [
                    "git",
                    "-c",
                    "core.quotepath=false",
                    "-C",
                    str(repo_root),
                    "ls-files",
                    "-s",
                    "-z",
                ],
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as exc:
            if attempt <= len(_SPAWN_RETRY_DELAYS) and _is_transient_windows_start_failure(
                exc.returncode
            ):
                time.sleep(_SPAWN_RETRY_DELAYS[attempt - 1])
                continue
            raise
    # Csak statikus elemzési biztonság: a ciklus mindig returnöl vagy raise-el.
    raise ScanFailure("git ls-files retry loop exhausted.")  # pragma: no cover


def _parse_git_ls_files(raw: bytes) -> list[str]:
    """Parse ``git ls-files -s -z`` records with strict validation.

    A record is ``<mode> SP <40-hex sha1> SP <stage> TAB <path>``; with ``-z``
    the path is raw bytes, so a tab inside a filename is preserved intact
    (everything after the first tab is the path). Anything else -- unknown
    mode, malformed object id or stage, or missing path -- fails closed
    instead of silently skipping a file the scanner would otherwise never
    see. Symlink/gitlink modes are the single documented non-regular
    category and are skipped.
    """
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScanFailure("git ls-files output is not valid UTF-8.") from exc
    candidates: list[str] = []
    for record in decoded.split("\0"):
        if not record:
            continue
        mode, _, remainder = record.partition(" ")
        digest_field, _, path = remainder.partition("\t")
        object_id, _, stage = digest_field.partition(" ")
        if mode not in _KNOWN_INDEX_MODES:
            raise ScanFailure(f"unexpected git index entry mode {mode!r}.")
        if len(object_id) != 40 or any(char not in "0123456789abcdef" for char in object_id):
            raise ScanFailure("malformed git ls-files record (invalid object id).")
        if stage not in {"0", "1", "2", "3"}:
            raise ScanFailure("malformed git ls-files record (invalid stage).")
        if not path:
            raise ScanFailure("malformed git ls-files record (missing path).")
        if mode not in _REGULAR_MODES:
            continue
        candidates.append(_normalize(path))
    return candidates


def _git_tracked_candidates(repo_root: Path, baseline_path: Path) -> list[str]:
    """Derive the candidate file list from the git index.

    Only regular-file index entries (modes 100644/100755) are candidates; the
    protected baseline and this script's own runtime audit output are each
    excluded exactly once. Excluding the audit output keeps the scanner from
    ever re-scanning the SHA-1 fingerprints it just wrote (which the Hex High
    Entropy detector would otherwise flag, producing a self-sustaining delta).
    The audit already lives in a git-ignored directory, so this is a second,
    explicit barrier that survives the directory being un-ignored or moved.
    Raises ScanFailure on git errors or malformed index output. The derived
    list is validated by ``_validate_candidates`` at the point of use.
    """
    try:
        raw = _run_git_ls_files(repo_root)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ScanFailure(f"git ls-files failed: {exc.__class__.__name__}.") from exc
    candidates = _parse_git_ls_files(raw)
    excluded: set[str] = {_audit_output_relative_path()}
    try:
        excluded.add(_normalize(str(baseline_path.relative_to(repo_root))))
    except ValueError:
        # The baseline lives outside the reconciled root; it can never be a
        # candidate of this root anyway.
        pass
    return [path for path in candidates if path not in excluded]


def _validate_candidate_names(normalized: list[str]) -> None:
    """Name-level validation, independent of any filesystem state."""
    if not normalized:
        raise ScanFailure("no tracked regular candidate files found.")
    if len(set(normalized)) != len(normalized):
        raise ScanFailure("duplicate tracked paths after normalization.")
    if _is_case_insensitive_platform() and len({path.casefold() for path in normalized}) != len(
        normalized
    ):
        raise ScanFailure("ambiguous tracked paths differing only by case.")


def _validate_candidates(candidates: list[str], repo_root: Path) -> list[str]:
    """Normalize, validate and sort a candidate file list; raises ScanFailure.

    Applies at the point of use, independent of how the list was derived:
    an empty set, duplicate paths after normalization, paths differing only
    by case on a case-insensitive platform, or a candidate file missing or
    non-regular on disk all fail closed. Returns the forward-slash-
    normalized, sorted list.
    """
    normalized = [_normalize(path) for path in candidates]
    _validate_candidate_names(normalized)
    for path in normalized:
        target = repo_root / path
        if not target.is_file() or target.is_symlink():
            raise ScanFailure(f"tracked candidate file missing or non-regular: {path}")
    return sorted(normalized)


def _read_candidate_bytes(target: Path) -> bytes:
    """Module-local seam so the unreadable-file path stays testable."""
    return target.read_bytes()


def _classify_candidates(
    candidates: list[str], repo_root: Path
) -> tuple[list[str], dict[str, str]]:
    """Split candidates into scanned and scanner-exempt, deterministically.

    The pinned scanner silently skips exactly the files rejected by its
    filename-level filters plus files it cannot decode: an exact ignored
    extension suffix, a documented lock-file basename, a ``swagger`` path, or
    a ``UnicodeDecodeError`` under the forced UTF-8 mode (platform
    independent, mirroring the driver's decoding exactly). The filename
    predicates are imported from the pinned package itself, so this
    classification can never drift from the scanner's own behavior. Every
    exempt file is returned with its reason and reported by path in the
    reconciliation message -- no file can disappear silently. A candidate that
    cannot even be read fails closed: a file the scanner could not account for
    must never be passed over quietly.
    """
    non_text, lock_file, swagger_file = _scanner_filename_predicates()
    scannable: list[str] = []
    exempt: dict[str, str] = {}
    for path in candidates:
        target = repo_root / path
        if non_text(target.name):
            exempt[path] = "ignored-extension"
            continue
        if lock_file(target.name):
            exempt[path] = "lock-file"
            continue
        if swagger_file(path):
            exempt[path] = "swagger-path"
            continue
        try:
            content = _read_candidate_bytes(target)
        except OSError as exc:
            raise ScanFailure(f"tracked candidate file cannot be read: {path}.") from exc
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            exempt[path] = "not-utf-8"
            continue
        scannable.append(path)
    return scannable, exempt


def _assert_pinned_scanner() -> None:
    """Fail closed unless the installed scanner is exactly the pinned version.

    The driver imports the same installed distribution, so the metadata
    visible here is the one the subprocess will use.
    """
    try:
        installed = metadata.version(_SCANNER_DISTRIBUTION)
    except metadata.PackageNotFoundError as exc:
        raise ScanFailure(f"pinned scanner {_SCANNER_DISTRIBUTION} is not installed.") from exc
    if installed != _PINNED_SCANNER_VERSION:
        raise ScanFailure(
            f"scanner version {installed} is not the pinned {_PINNED_SCANNER_VERSION}."
        )


def _run_driver_scan(
    files: list[str], repo_root: Path
) -> subprocess.CompletedProcess[bytes]:
    """Scan exactly the given file list with the pinned driver subprocess.

    The file list travels on stdin, so no platform command-line length limit
    applies. The driver runs with the documented forced-UTF-8 environment and
    prints the deterministic results document on stdout plus the scanner's own
    per-file ``Checking file:`` accounting lines on stderr. Bounded retry
    applies only to the documented transient Windows process-start failure;
    every other outcome returns on the first attempt.
    """
    env = dict(os.environ)
    env.update(_SCANNER_ENV_OVERRIDES)
    for attempt in range(1, len(_SPAWN_RETRY_DELAYS) + 2):
        try:
            completed = subprocess.run(
                [sys.executable, str(_DRIVER_PATH)],
                cwd=str(repo_root),
                env=env,
                input=("\n".join(files) + "\n").encode("utf-8"),
                capture_output=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScanFailure("scan driver chunk timed out.") from exc
        if attempt <= len(_SPAWN_RETRY_DELAYS) and _is_transient_windows_start_failure(
            completed.returncode
        ):
            time.sleep(_SPAWN_RETRY_DELAYS[attempt - 1])
            continue
        return completed
    # Csak statikus elemzési biztonság: a ciklus mindig returnöl.
    raise ScanFailure("scan driver retry loop exhausted.")  # pragma: no cover


def _probe_filename(chunk_index: int) -> str:
    return f"{_PROBE_PREFIX}{chunk_index}-{os.getpid()}.txt"


def _expected_probe_fingerprint() -> tuple[str, str]:
    return (
        "Secret Keyword",
        hashlib.sha1(_probe_secret_value().encode("utf-8")).hexdigest(),
    )


def _accounted_files(stderr: bytes) -> set[str]:
    """Parse the scanner's own per-file accounting from its INFO log.

    The pinned scanner logs ``Checking file: <path>`` for every file it
    actually opens, after the filename-level filters and before decoding. A
    file that never appears here was never scanned -- whatever the reason --
    and the caller fails closed on it. Non-UTF-8 stderr cannot be parsed and
    therefore cannot prove coverage; it fails closed here too.
    """
    try:
        text = stderr.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScanFailure("scanner accounting log is not valid UTF-8.") from exc
    accounted: set[str] = set()
    for line in text.splitlines():
        marker = line.find(_CHECKING_FILE_PREFIX)
        if marker == -1:
            continue
        accounted.add(_normalize(line[marker + len(_CHECKING_FILE_PREFIX):].strip()))
    return accounted


def _live_scan(files: list[str], repo_root: Path) -> dict[str, Any]:
    """Scan exactly the given canonical file set and merge the results.

    Every requested path is passed to the pinned driver exactly once; the
    merged output must not mention any file outside the requested set.
    Per-file coverage is proven, not assumed: the driver stderr carries the
    scanner's own ``Checking file:`` line for every file it opens, and any
    requested file absent from that accounting fails closed (the probe files
    are the only exception -- they are never part of the requested set).
    Each chunk additionally carries a sentinel probe (a runtime-generated file
    inside the repository root, always removed afterwards, including on
    failure) whose known fingerprint must appear in the chunk output, proving
    detection worked in that invocation. Raises ScanFailure on driver errors,
    malformed output, lost coverage, a missing probe detection or probe
    write/delete errors.
    """
    if not files:
        raise ScanFailure("no tracked candidate files to scan.")
    _assert_pinned_scanner()
    chunks = [
        files[index : index + _SCAN_CHUNK_SIZE] for index in range(0, len(files), _SCAN_CHUNK_SIZE)
    ]
    if sum(len(chunk) for chunk in chunks) != len(files):
        raise ScanFailure("candidate chunking lost files (incomplete coverage).")
    expected_type, expected_hash = _expected_probe_fingerprint()

    def _run_chunk(
        chunk_index: int, chunk: list[str]
    ) -> tuple[str, subprocess.CompletedProcess[bytes]]:
        probe_name = _probe_filename(chunk_index)
        probe_path = repo_root / probe_name
        try:
            try:
                probe_path.write_text(_probe_line(), encoding="utf-8")
            except OSError as exc:
                raise ScanFailure(
                    f"sentinel probe could not be written: {probe_name}."
                ) from exc
            return probe_name, _run_driver_scan([*chunk, probe_name], repo_root)
        finally:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ScanFailure(
                    f"sentinel probe could not be removed: {probe_name}."
                ) from exc

    with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
        completed = list(pool.map(lambda pair: _run_chunk(*pair), enumerate(chunks)))
    requested = {_normalize(path) for path in files}
    merged: dict[str, list[dict[str, Any]]] = {}
    accounted: set[str] = set()
    for probe_name, result in completed:
        if result.returncode != 0:
            raise ScanFailure(f"scan driver exit code {result.returncode}.")
        try:
            stdout = result.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScanFailure("scan driver output is not valid UTF-8.") from exc
        try:
            document = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ScanFailure(f"scan driver output is not valid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ScanFailure("scan driver output is missing the document object.")
        results = document.get("results")
        if not isinstance(results, dict):
            raise ScanFailure("scan driver output is missing a valid results section.")
        accounted |= _accounted_files(result.stderr)
        probe_seen = False
        for filename, findings in results.items():
            key = _normalize(str(filename))
            if key == probe_name:
                if isinstance(findings, list) and any(
                    isinstance(finding, dict)
                    and str(finding.get("type", "")) == expected_type
                    and str(finding.get("hashed_secret", "")) == expected_hash
                    for finding in findings
                ):
                    probe_seen = True
                continue
            if key not in requested:
                raise ScanFailure(
                    f"scanner reported file outside the canonical tracked set: {key}."
                )
            if not isinstance(findings, list):
                raise ScanFailure(f"scanner output is not a findings list for file: {key}.")
            merged.setdefault(key, []).extend(findings)
        if not probe_seen:
            raise ScanFailure(
                "sentinel probe was not detected in driver output "
                f"(unaccounted scanner invocation for chunk {probe_name})."
            )
    missing = requested - accounted
    if missing:
        raise ScanFailure(
            "scanner did not account for requested file(s): "
            + ", ".join(sorted(missing))
            + "."
        )
    return {"results": merged}


def _fingerprints(document: dict[str, Any]) -> set[tuple[str, str, str]]:
    fingerprints: set[tuple[str, str, str]] = set()
    for filename, findings in document.get("results", {}).items():
        for finding in findings:
            fingerprints.add(
                (
                    _normalize(str(filename)),
                    str(finding.get("type", "")),
                    str(finding.get("hashed_secret", "")),
                )
            )
    return fingerprints


def _read_text_for_classification(path: Path) -> list[str]:
    """Read a candidate as UTF-8 for structural classification.

    The scanner already proved the file decodes; a read error here still fails
    closed via the caller, because an unreadable file can never be classified.
    """
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ScanFailure(f"candidate is unreadable for classification: {path.name}.") from exc


# --- Structural classifiers -------------------------------------------------
#
# A classifier clears a live finding ONLY by re-deriving it from the working
# tree: it extracts the token it considers non-secret by construction and must
# reproduce the scanner's own SHA-1 fingerprint. Nothing here trusts a
# filename alone or a remembered hash, so a genuine secret cannot inherit
# clearance, and adding one to an otherwise classified file still fails
# closed. Each rule is additionally narrowed to *exact* field names and
# *exact* file paths: the repository's documented content registries, nothing
# more. Extending either set is an R3 security decision, never a gate fix.

# The exact digest field names used by the repository's content registries.
# Any other key -- ``api_sha256``, ``some_checksum``, a name merely ending in
# ``sha256`` -- stays unclassified.
_CONTENT_DIGEST_KEYS = frozenset(
    {
        "reference_sha256",
        "fragment_sha256",
        "claim_snapshot_sha256",
        "source_sha256",
        "checksum",
        "sha256",
    }
)
# The exact content-registry files whose 64-hex values are content digests by
# construction. The same exact key in any other file stays unclassified.
_CONTENT_DIGEST_PATHS = frozenset(
    {
        "services/platform-core/app/static/prevalidated-commercial-sources/manifest.json",
        "services/operational-guidance/config/operational-process-catalog-v1.0.json",
        "services/platform-core/SOURCE_LOCK.json",
        "services/platform-core/app/seed.py",
        "services/platform-core/docs/DEVELOPMENT_DISCOVERY_COMMERCIAL_V1.json",
    }
)
# A 64-hex content digest bound on its own line to exactly one of the digest
# keys: ``"reference_sha256": "<64 hex>"``, ``sha256=<64 hex>``. The key
# alternation is generated from ``_CONTENT_DIGEST_KEYS`` (longest first), so
# the documented set and the compiled pattern can never drift apart.
_CONTENT_DIGEST_RE = re.compile(
    r"(?<![A-Za-z0-9_])[\"']?(?:"
    + "|".join(sorted(_CONTENT_DIGEST_KEYS, key=len, reverse=True))
    + r")[\"']?\s*[:=]\s*[\"']([0-9a-f]{64})[\"']"
)
# The exact Drive-index field names. Any other key (``driveId``, ``file_id``,
# a name merely ending in ``id``) stays unclassified.
_DRIVE_RESOURCE_ID_KEYS = frozenset({"id", "sourceId"})
# The exact Drive/Docs index files. A Drive-shaped value under the same exact
# key in any other file stays unclassified.
_DRIVE_RESOURCE_ID_PATHS = frozenset(
    {
        "services/platform-core/app/canonical_documents/templates.json",
        "sites/_portal/data/artifacts.json",
    }
)
# A Google Drive/Docs resource identifier bound to exactly ``id``/``sourceId``.
# The documented modern form is a leading ``1`` plus 32 or 43 URL-safe base64
# characters; nothing shorter, longer or differently prefixed qualifies. The
# key alternation is generated from ``_DRIVE_RESOURCE_ID_KEYS`` (longest
# first), so the documented set and the compiled pattern cannot drift apart.
_DRIVE_RESOURCE_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_])[\"']?(?:"
    + "|".join(sorted(_DRIVE_RESOURCE_ID_KEYS, key=len, reverse=True))
    + r")[\"']?\s*[:=]\s*[\"']"
    r"(1[A-Za-z0-9_-]{32}(?:[A-Za-z0-9_-]{11})?)[\"']"
)
# Corroboration that a file really is a Drive/Docs index: an actual Drive URL,
# or an explicit ``drive`` provenance marker on a sibling field. Without one of
# these, a Drive-shaped token stays unclassified.
_DRIVE_PROVENANCE_RE = re.compile(
    r"https://(?:docs|drive)\.google\.com|[\"']kind[\"']\s*:\s*[\"']drive-|"
    r"[\"']path[\"']\s*:\s*[\"']/drive/"
)


def _classify_content_digest(line: str, hashed: str, _document: str, path: str) -> bool:
    if path not in _CONTENT_DIGEST_PATHS:
        return False
    return any(
        hashlib.sha1(value.encode("utf-8")).hexdigest() == hashed
        for value in _CONTENT_DIGEST_RE.findall(line)
    )


def _classify_drive_resource_id(line: str, hashed: str, document: str, path: str) -> bool:
    if path not in _DRIVE_RESOURCE_ID_PATHS:
        return False
    if not _DRIVE_PROVENANCE_RE.search(document):
        return False
    return any(
        hashlib.sha1(value.encode("utf-8")).hexdigest() == hashed
        for value in _DRIVE_RESOURCE_ID_RE.findall(line)
    )


# detector type -> (classification name, predicate). A detector type absent
# from this table has no classifier at all and always fails closed.
_STRUCTURAL_CLASSIFIERS: dict[str, tuple[str, Any]] = {
    "Hex High Entropy String": ("content-digest", _classify_content_digest),
    "Base64 High Entropy String": ("drive-resource-id", _classify_drive_resource_id),
}


def _classify_additions(
    current: dict[str, Any],
    additions: set[tuple[str, str, str]],
    repo_root: Path,
) -> tuple[dict[str, int], set[tuple[str, str, str]]]:
    """Split live-but-unbaselined findings into classified and unclassified.

    Returns ``(classified counts by classification name, unclassified set)``.
    Every finding that no structural classifier proves is returned as
    unclassified, so the caller fails closed on it.
    """
    by_path: dict[str, list[dict[str, Any]]] = {}
    for filename, findings in current.get("results", {}).items():
        by_path.setdefault(_normalize(str(filename)), []).extend(findings)
    remaining = set(additions)
    classified: dict[str, int] = {}
    for path in sorted({filename for filename, _, _ in additions}):
        wanted = {
            (finding_type, hashed)
            for filename, finding_type, hashed in remaining
            if filename == path
        }
        if not wanted:
            continue
        lines = _read_text_for_classification(repo_root / path)
        document = "\n".join(lines)
        for finding in by_path.get(path, []):
            finding_type = str(finding.get("type", ""))
            hashed = str(finding.get("hashed_secret", ""))
            if (finding_type, hashed) not in wanted:
                continue
            rule = _STRUCTURAL_CLASSIFIERS.get(finding_type)
            if rule is None:
                continue
            name, predicate = rule
            try:
                line_number = int(finding.get("line_number", 0))
            except (TypeError, ValueError):
                continue
            # 1-based and in range, or the finding stays unclassified. A zero or
            # negative number must never wrap around to a different line.
            if not 1 <= line_number <= len(lines):
                continue
            if predicate(lines[line_number - 1], hashed, document, path):
                classified[name] = classified.get(name, 0) + 1
                # Discard from both sets: the same fingerprint may be reported
                # on several lines, and it must be counted exactly once.
                wanted.discard((finding_type, hashed))
                remaining.discard((path, finding_type, hashed))
    return classified, remaining


def _emit_unmatched_audit(additions: set[tuple[str, str, str]], repo_root: Path) -> Path:
    """Write the bounded hash/path-only audit for unmatched candidates.

    Rows carry the normalized path, the detector type and the SHA-1
    fingerprints only -- never plaintext secret material -- and are marked
    unclassified. The artifact is written to the git-ignored runtime
    directory, so only a failing (fail-closed) run writes anything.

    The report is deliberately bounded: at most ``_AUDIT_MAX_ROWS`` rows and
    ``_AUDIT_MAX_HASHES_PER_ROW`` fingerprints per row. Truncation is never
    silent -- the omitted counts are stated explicitly and the totals always
    describe the full finding set -- so the artifact stays short enough to read
    in a review without ever understating what failed closed.

    This file is write-only evidence. Nothing in this module reads it back, so
    it can never act as an allowlist, baseline or suppression input.
    """
    by_path: dict[str, dict[str, list[str]]] = {}
    for filename, finding_type, hashed in additions:
        by_path.setdefault(filename, {}).setdefault(finding_type, []).append(hashed)
    every_row: list[tuple[str, str, list[str]]] = [
        (filename, finding_type, sorted(by_path[filename][finding_type]))
        for filename in sorted(by_path)
        for finding_type in sorted(by_path[filename])
    ]
    rows: list[dict[str, Any]] = []
    for filename, finding_type, hashes in every_row[:_AUDIT_MAX_ROWS]:
        row: dict[str, Any] = {
            "path": filename,
            "type": finding_type,
            "classification": "unclassified",
            "findingCount": len(hashes),
            "hashes": hashes[:_AUDIT_MAX_HASHES_PER_ROW],
        }
        if len(hashes) > _AUDIT_MAX_HASHES_PER_ROW:
            row["hashesOmitted"] = len(hashes) - _AUDIT_MAX_HASHES_PER_ROW
        rows.append(row)
    document: dict[str, Any] = {
        "schemaVersion": "3.0",
        "kind": "tracked-secret-delta-audit",
        "scope": (
            "normalized paths, detector types and SHA-1 fingerprints only; "
            "no plaintext secret material"
        ),
        "usage": (
            "untracked runtime report only; never read back as allowlist, "
            "baseline or suppression input"
        ),
        "classification": "unclassified",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "findingTotal": len(additions),
        "pathTotal": len(by_path),
        "rowTotal": len(every_row),
        "rowsOmitted": max(0, len(every_row) - _AUDIT_MAX_ROWS),
        "rows": rows,
    }
    path = _unmatched_audit_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def reconcile_tracked_secrets(
    baseline_path: Path,
    repo_root: Path | None = None,
) -> tuple[int, str]:
    """Reconcile the audited set against the canonical tracked-secret scan.

    Returns ``(status, message)``. Status 0: every live candidate is either in
    the protected baseline or proven non-secret by a structural classifier
    (stale-only entries, scanner-exempt files and the per-class classified
    counts are reported as documented warnings). Status 1: at least one live
    candidate is unclassified -- a bounded hash/path-only audit report is
    written to the git-ignored runtime directory. Status 2: missing or
    malformed baseline, any scanner/git failure or canonical-set condition.
    The live scan always runs; there is no snapshot or environment bypass.
    Messages never contain secret material, only file paths/counts and
    fingerprints.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    if not baseline_path.is_file():
        return 2, "repository baseline is missing."
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 2, f"repository baseline is not valid JSON: {exc}"
    baseline_results = baseline.get("results")
    if not isinstance(baseline_results, dict):
        return 2, "repository baseline is missing a valid results section."
    for filename, findings in baseline_results.items():
        if not isinstance(findings, list):
            return 2, (
                f"repository baseline is not a findings list for file: {_normalize(str(filename))}."
            )
    try:
        candidates = _validate_candidates(_git_tracked_candidates(root, baseline_path), root)
        scannable, exempt = _classify_candidates(candidates, root)
        current = _live_scan(scannable, root)
    except ScanFailure as exc:
        return 2, str(exc)
    audited = _fingerprints(baseline)
    observed = _fingerprints(current)
    try:
        classified, unclassified = _classify_additions(current, observed - audited, root)
    except ScanFailure as exc:
        return 2, str(exc)
    if unclassified:
        locations = sorted({filename for filename, _, _ in unclassified})
        message = (
            f"{len(unclassified)} unclassified candidate(s) in "
            f"{len(locations)} tracked file(s).\n"
            + "\n".join(f"- {filename}" for filename in locations)
        )
        try:
            audit_path = _emit_unmatched_audit(unclassified, root)
        except OSError:
            audit_path = None
        if audit_path is not None:
            message += f"\nbounded hash/path-only audit report written to: {audit_path}"
        return 1, message
    # Only the baseline intersection may be reported as "matching the audited
    # baseline"; structurally classified candidates are counted separately, so
    # the message can never overstate how much the protected baseline covers.
    parts = [f"{len(observed & audited)} tracked candidate(s) match the audited baseline"]
    if classified:
        listed = ", ".join(f"{name}: {count}" for name, count in sorted(classified.items()))
        parts.append(
            f"{sum(classified.values())} candidate(s) outside the baseline proven "
            f"non-secret by structural classifier ({listed})"
        )
    stale = audited - observed
    if stale:
        parts.append(f"{len(stale)} stale audited entry/entries")
    if exempt:
        listed = ", ".join(f"{path} ({reason})" for path, reason in sorted(exempt.items()))
        parts.append(
            f"{len(exempt)} tracked candidate file(s) scanner-exempt by design "
            f"(ignored-extension, lock-file, swagger-path or not-utf-8): {listed}"
        )
    return 0, "; ".join(parts) + "."


def main() -> int:
    status, message = reconcile_tracked_secrets(BASELINE_PATH)
    if status == 0:
        print(f"Secret baseline PASS: {message}")
    else:
        print(f"Secret baseline FAIL: {message}")
    return status


if __name__ == "__main__":
    # A konzol/környezet kódlaptól független kimenet: a path-listák
    # tartalmazhatnak nem-ASCII fájlneveket, ezek nem okozhatnak crash-t.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main())
