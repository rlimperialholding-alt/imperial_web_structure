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
* the audited identity is occurrence-aware **and content-bearing**: the
  comparison unit is ``(normalized path, detector type, SHA-1 fingerprint,
  line number, SHA-256 line-content fingerprint)``. The fifth part is
  immutable evidence, not a position: the audited side takes it from the file
  version in git history at the audited anchor commit, the live side from the
  working tree, so the two sides can only ever agree on *bytes*. A bare
  line-number match is therefore never sufficient anywhere in this module --
  an audited fingerprint that stays on its line while its key or context
  changes (a classified ``reference_sha256`` binding rewritten to an
  unclassified one) has no content evidence, so it stays an addition and must
  be proven harmless by a structural classifier on that exact line or fail
  closed. A value already baselined on one classified line can never suppress
  a new occurrence of the same digest on any other line: the new line is an
  addition and must be proven harmless on that exact line, or the run fails
  closed. A baseline entry without a usable line number or without audited
  line-content evidence can never match a live finding, and a live finding
  without a usable line number or without live line-content evidence can
  never reconcile -- all of these fail closed;
* the audited *occurrence set* is normalized from git history, not assumed
  from the baseline document alone. The protected baseline was generated by
  the pinned CLI, which records each audited value once (identical
  ``(type, fingerprint)`` pairs per file collapse to their first line) and
  silently skips files it cannot decode under the host locale -- so a value
  that legally repeats on several lines of an unchanged audited file, a
  value whose line drifted after an unrelated edit above it, and every value
  inside a file the baseline generator could not decode are all documented
  baseline-representation gaps, not secret additions. The audited
  occurrence set is therefore re-derived by scanning the tracked file
  versions at the audited anchor commit (the commit that last modified the
  baseline file) with the same pinned, forced-UTF-8, per-line driver as the
  live scan, through a dedicated seam (``_run_audited_driver``), with temp
  copies written only under the git-ignored runtime directory and always
  removed. A baseline that is untracked, uncommitted or outside the
  reconciled root fails closed (status 2), and a file that did not exist at
  the audited commit has no audited state at all -- every finding in it
  fails closed unless structurally classified;
* reconciliation is occurrence-aware against that audited set, strictly per
  line, and always backed by immutable line-content evidence: a live identity
  reconciles only when it matches a baseline entry on the same line *with
  byte-identical line content*, matches an audited occurrence on the same line
  with byte-identical line content, or is *proven* to be one specific audited
  occurrence that an unrelated edit shifted. In every case the proof is the
  same immutable evidence -- the live line text must be byte-identical
  (compared as SHA-256 content fingerprints) to the audited line's text read
  from git history at the anchor commit -- and it is injective: every audited
  occurrence backs at most one live occurrence, and a live occurrence already
  sitting on its audited line claims that audited occurrence first. Neither
  aggregate occurrence counts nor bare line numbers are ever a reconciliation
  input: a value's total count matching the audited total proves nothing about
  *which* occurrence is live, and a matching line number proves nothing about
  *what* that line now says. An audited digest deleted from its classified
  line and reintroduced on a different, unclassified line stays an addition,
  and so does an audited digest that never left its line but whose key or
  surrounding context was rewritten -- both must be proven harmless by a
  structural classifier on their exact line; one unprovable line fails closed,
  even when the same digest is audited or classified on another line. A live
  finding without a usable line number, or without live line-content
  evidence, never reconciles through the baseline or the audited state: it
  stays unclassified and fails closed;
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
  ``source_sha256``, and only inside the repository's dedicated, provably
  static content-registry files -- never inside an executable source file,
  and never under a generic key name such as ``sha256``/``checksum``) and
  ``drive-resource-id`` (a Google
  Drive/Docs resource identifier in the documented ``1`` + 32/43
  ``[A-Za-z0-9_-]`` form bound to exactly the ``id``/``sourceId`` key in the
  two documented Drive index files, which must additionally be corroborated by
  a Drive/Docs URL or an explicit ``drive`` provenance marker in the same
  file);
* findings are classified per line, never per digest: every new line
  occurrence of a value is cleared only when proven non-secret on that exact
  line; one unprovable line keeps its own per-line identity unclassified and
  fails closed, even when the same digest is baselined or classified on
  another line;
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
from datetime import UTC, datetime
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
# The audited-state scan writes temporary copies of the audited file versions
# under the git-ignored platform-core runtime directory (sibling of the
# unmatched audit artifact), so no historical content can ever dirty the
# tracked worktree. The original basename is kept (only the directory and an
# index prefix change), so the pinned driver's filename-level filters classify
# the temp copy exactly like the live candidate.
_HISTORICAL_SCAN_RELATIVE_DIR = ("services", "platform-core", "runtime", "historical")


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


def _run_git_baseline_anchor(repo_root: Path, relative_path: str) -> str:
    """``git log -1 --format=%H`` of the baseline file; bounded transient retry.

    Module-local seam for the anchor tests; the same documented Windows
    transient process-start retry applies as to every other git invocation.
    """
    for attempt in range(1, len(_SPAWN_RETRY_DELAYS) + 2):
        try:
            return subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "log",
                    "-1",
                    "--format=%H",
                    "--",
                    relative_path,
                ],
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            ).strip()
        except subprocess.CalledProcessError as exc:
            if attempt <= len(_SPAWN_RETRY_DELAYS) and _is_transient_windows_start_failure(
                exc.returncode
            ):
                time.sleep(_SPAWN_RETRY_DELAYS[attempt - 1])
                continue
            raise
    raise ScanFailure("git baseline anchor retry loop exhausted.")  # pragma: no cover


def _baseline_anchor_commit(repo_root: Path, baseline_path: Path) -> str:
    """The commit that last modified the protected baseline in git history.

    The audited occurrence state is reconstructed from the tracked file
    versions at this commit, so the anchor must exist: a baseline that is
    untracked, uncommitted or outside the reconciled root fails closed. The
    returned object id is validated as a 40-hex sha, so a malformed git
    answer can never be used as a git rev argument.
    """
    try:
        relative = _normalize(str(baseline_path.relative_to(repo_root)))
    except ValueError as exc:
        raise ScanFailure("baseline is outside the reconciled repository root.") from exc
    try:
        anchor = _run_git_baseline_anchor(repo_root, relative)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ScanFailure("baseline anchor commit could not be resolved from git history.") from exc
    if len(anchor) != 40 or any(char not in "0123456789abcdef" for char in anchor):
        raise ScanFailure("baseline anchor commit is not a valid object id.")
    return anchor


def _run_git_show_audited_file(repo_root: Path, anchor: str, path: str) -> bytes:
    """``git show <anchor>:<path>`` raw bytes; bounded transient retry.

    Module-local seam for the audited-state tests. ``CalledProcessError``
    means the path did not exist at the audited commit (the documented
    new-file case); the caller maps that to an absent audited state, which
    fails closed for every live finding in that file.
    """
    for attempt in range(1, len(_SPAWN_RETRY_DELAYS) + 2):
        try:
            return subprocess.check_output(
                ["git", "-C", str(repo_root), "show", f"{anchor}:{path}"],
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as exc:
            if attempt <= len(_SPAWN_RETRY_DELAYS) and _is_transient_windows_start_failure(
                exc.returncode
            ):
                time.sleep(_SPAWN_RETRY_DELAYS[attempt - 1])
                continue
            raise
    raise ScanFailure("git show audited file retry loop exhausted.")  # pragma: no cover


def _audited_file_bytes(repo_root: Path, anchor: str, path: str) -> bytes | None:
    """Tracked file content at the audited commit; ``None`` when absent there.

    A path that did not exist at the audited commit has no audited state:
    every live finding in it is an addition and fails closed unless a
    structural classifier proves it. Any other git failure raises
    ``ScanFailure``.
    """
    try:
        return _run_git_show_audited_file(repo_root, anchor, path)
    except subprocess.CalledProcessError:
        return None
    except FileNotFoundError as exc:
        raise ScanFailure("git is unavailable for the audited-state scan.") from exc


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


def _run_driver_scan(files: list[str], repo_root: Path) -> subprocess.CompletedProcess[bytes]:
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
        except OSError as exc:
            # The driver could not even be spawned (missing interpreter,
            # unreadable driver file, ...). The message is fixed and carries
            # no environment, path or secret material; a raw traceback must
            # never surface instead of the controlled fail-closed status.
            raise ScanFailure("scan driver could not start.") from exc
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
        accounted.add(_normalize(line[marker + len(_CHECKING_FILE_PREFIX) :].strip()))
    return accounted


def _scan_file_set(
    files: list[str],
    repo_root: Path,
    runner: Any,
) -> dict[str, Any]:
    """Chunked, sentinel-probed, coverage-accounted scan of ``files`` via ``runner``.

    Shared by the live scan (``_run_driver_scan``) and the audited-state scan
    (``_run_audited_driver``): chunking, the per-chunk sentinel probe, the
    per-file coverage accounting and the canonical-set check are byte-for-byte
    identical for both, so the audited state is derived with exactly the
    live-scan strength.

    Every requested path is passed to the driver exactly once; the merged
    output must not mention any file outside the requested set. Per-file
    coverage is proven, not assumed: the driver stderr carries the scanner's
    own ``Checking file:`` line for every file it opens, and any requested
    file absent from that accounting fails closed (the probe files are the
    only exception -- they are never part of the requested set). Each chunk
    additionally carries a sentinel probe (a runtime-generated file inside the
    repository root, always removed afterwards, including on failure) whose
    known fingerprint must appear in the chunk output, proving detection
    worked in that invocation. Raises ScanFailure on driver errors, malformed
    output, lost coverage, a missing probe detection or probe write/delete
    errors.
    """
    if not files:
        raise ScanFailure("no candidate files to scan.")
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
                raise ScanFailure(f"sentinel probe could not be written: {probe_name}.") from exc
            return probe_name, runner([*chunk, probe_name], repo_root)
        finally:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ScanFailure(f"sentinel probe could not be removed: {probe_name}.") from exc

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
            "scanner did not account for requested file(s): " + ", ".join(sorted(missing)) + "."
        )
    return {"results": merged}


def _live_scan(files: list[str], repo_root: Path) -> dict[str, Any]:
    """Scan exactly the given canonical live file set (see ``_scan_file_set``)."""
    return _scan_file_set(files, repo_root, _run_driver_scan)


# The audited-state scan runs through the same driver function object, under
# a distinct module-level name. The separate name is the documented seam: a
# test that pins the live scan (monkeypatching ``_run_driver_scan``) must not
# silently pin the audited-state scan too -- the audited state keeps running
# the real pinned driver, so a faked live result can never fabricate audited
# coverage. Tests that need to control the audited-state scan monkeypatch
# this name instead.
_run_audited_driver = _run_driver_scan


def _audited_occurrence_identities(
    repo_root: Path,
    anchor: str,
    addition_paths: list[str],
) -> set[tuple[str, str, str, int]]:
    """Per-line occurrence identities of the addition files at the audited commit.

    The audited state is the *normalized* audited set: the protected baseline
    records each audited value once (the pinned CLI collapses identical
    ``(type, fingerprint)`` pairs per file to their first line and silently
    skips files it cannot decode under the host locale), so the occurrence
    set the audited commit actually contained is re-derived here by scanning
    the tracked file versions at the anchor commit with the same pinned,
    forced-UTF-8, per-line driver as the live scan. Temporary copies are
    written under the git-ignored runtime directory with their original
    basename (so the driver's filename-level filters classify them exactly
    like the live candidates) and are always removed, including on failure;
    any write/scan/cleanup failure fails closed. A path that did not exist
    at the audited commit contributes no audited state.
    """
    if not addition_paths:
        return set()
    temp_root = repo_root.joinpath(*_HISTORICAL_SCAN_RELATIVE_DIR)
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ScanFailure("audited-state temp directory could not be created.") from exc
    written: list[Path] = []
    mapping: dict[str, str] = {}
    try:
        for index, path in enumerate(sorted(addition_paths)):
            content = _audited_file_bytes(repo_root, anchor, path)
            if content is None:
                # Új fájl az audited commit óta: nincs auditált állapota, így
                # minden élő találata addition -- fail-closed, hacsak a
                # strukturális osztályozó nem bizonyítja.
                continue
            temp_path = temp_root / f"{index}-{Path(path).name}"
            try:
                temp_path.write_bytes(content)
            except OSError as exc:
                raise ScanFailure(f"audited-state temp copy could not be written: {path}.") from exc
            written.append(temp_path)
            mapping[_normalize(str(temp_path))] = path
        if not written:
            return set()
        scanned = _scan_file_set(
            [_normalize(str(path)) for path in written], repo_root, _run_audited_driver
        )
    finally:
        for temp_path in written:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ScanFailure(
                    f"audited-state temp copy could not be removed: {temp_path.name}."
                ) from exc
    identities: set[tuple[str, str, str, int]] = set()
    for filename, findings in scanned.get("results", {}).items():
        original = mapping.get(_normalize(str(filename)))
        if original is None:
            raise ScanFailure("audited-state scan reported a file outside the temp set.")
        for finding in findings:
            line_number = _normalized_line_number(finding)
            if line_number is None:
                # Auditált előfordulás használható sor nélkül sosem
                # egyeztethet -- a hívó fail-closed marad.
                continue
            identities.add(
                (
                    original,
                    str(finding.get("type", "")),
                    str(finding.get("hashed_secret", "")),
                    line_number,
                )
            )
    return identities


def _line_content_digests(lines: list[str]) -> dict[int, str]:
    """Map each 1-based line number to the SHA-256 of that exact line text.

    Only the digest is retained, never the line itself, so the per-line
    equivalence evidence used by ``_split_additions`` can be compared, counted
    and reasoned about without any secret plaintext ever entering a data
    structure, a message or a report.
    """
    return {
        index: hashlib.sha256(line.encode("utf-8")).hexdigest()
        for index, line in enumerate(lines, start=1)
    }


def _audited_line_content_digests(
    repo_root: Path,
    anchor: str,
    paths: list[str],
) -> dict[str, dict[int, str]]:
    """Per-line content fingerprints of the given files at the audited commit.

    This is the immutable evidence behind every audited identity: it lets
    ``_split_baseline_matches`` require that a baselined line still says the
    same thing, and ``_split_additions`` prove that a *specific* audited
    occurrence still exists after an unrelated edit shifted its line. The
    audited line text is read straight from git history at the anchor commit,
    so nothing in the working tree can influence it.

    A path that did not exist at the audited commit, or whose audited content
    is not valid UTF-8 (the driver forces UTF-8, so such a version was never
    line-addressable either), contributes no evidence at all -- every live
    occurrence in it then stays an addition and fails closed unless a
    structural classifier proves it. Any other git failure raises
    ``ScanFailure`` through ``_audited_file_bytes``.
    """
    evidence: dict[str, dict[int, str]] = {}
    for path in sorted(paths):
        content = _audited_file_bytes(repo_root, anchor, path)
        if content is None:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        evidence[path] = _line_content_digests(text.splitlines())
    return evidence


def _live_line_content_digests(
    repo_root: Path,
    paths: list[str],
) -> dict[str, dict[int, str]]:
    """Per-line content fingerprints of the given files in the working tree.

    Read through the same strict UTF-8 reader the structural classifiers use,
    so the equivalence proof and the classification see byte-identical line
    text. An unreadable candidate raises ``ScanFailure`` and fails closed.
    """
    return {
        path: _line_content_digests(_read_text_for_classification(repo_root / path))
        for path in sorted(paths)
    }


def _normalized_line_number(finding: dict[str, Any]) -> int | None:
    """The 1-based line number of a finding; ``None`` when absent or malformed.

    The audited identity is occurrence-aware: the line number is part of the
    comparison unit, so a value baselined on one classified line can never
    suppress a new occurrence of the same digest on a different unclassified
    line. ``None`` is deliberately distinct from every real line number: a
    baseline entry without a usable line can never match a live finding, so
    both sides fail closed through the classifier instead of being silently
    reconciled.
    """
    raw = finding.get("line_number")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _fingerprints(document: dict[str, Any]) -> set[tuple[str, str, str, int | None]]:
    """Per-line occurrence identities: ``(path, type, fingerprint, line number)``.

    Both the audited set (from the protected baseline) and the observed set
    (from the live scan) are reduced through this single function, so the two
    sides always start from the same per-line identity. Because the line number
    is part of the identity, the same digest on a different line is a different
    occurrence.

    This four-part identity is never a reconciliation decision on its own:
    ``_content_bearing_identities`` extends it with the immutable line-content
    fingerprint that both the baseline subtraction and the audited-state
    matching require, so a matching path/type/fingerprint/line whose line text
    changed can never reconcile.
    """
    fingerprints: set[tuple[str, str, str, int | None]] = set()
    for filename, findings in document.get("results", {}).items():
        for finding in findings:
            fingerprints.add(
                (
                    _normalize(str(filename)),
                    str(finding.get("type", "")),
                    str(finding.get("hashed_secret", "")),
                    _normalized_line_number(finding),
                )
            )
    return fingerprints


def _content_bearing_identities(
    identities: set[tuple[str, str, str, int | None]],
    line_digests: dict[str, dict[int, str]],
) -> set[tuple[str, str, str, int, str]]:
    """Extend per-line identities with their immutable line-content evidence.

    The full occurrence identity is
    ``(path, detector type, fingerprint, line number, line-content digest)``.
    ``line_digests`` supplies the fifth part for exactly one side: git history
    at the audited anchor commit for the audited side (see
    ``_audited_line_content_digests``), the working tree for the live side
    (see ``_live_line_content_digests``). Because the two sides draw their
    evidence from different, independent sources, an identity can only ever be
    shared when the line text itself is byte-identical -- position alone is
    never enough.

    An identity without a usable line number, or whose line carries no content
    fingerprint on this side (out of range, or a file version that was never
    line-addressable), produces no content-bearing identity at all. It can
    therefore never match the other side: it stays an addition and fails
    closed unless a structural classifier proves it on its exact line.
    """
    bearing: set[tuple[str, str, str, int, str]] = set()
    for path, finding_type, hashed, line_number in identities:
        if line_number is None:
            continue
        content = line_digests.get(path, {}).get(line_number)
        if content is None:
            continue
        bearing.add((path, finding_type, hashed, line_number, content))
    return bearing


def _split_baseline_matches(
    observed: set[tuple[str, str, str, int | None]],
    audited: set[tuple[str, str, str, int | None]],
    audited_line_digests: dict[str, dict[int, str]],
    live_line_digests: dict[str, dict[int, str]],
) -> tuple[
    set[tuple[str, str, str, int | None]],
    set[tuple[str, str, str, int | None]],
]:
    """Split live identities into proven baseline matches and additions.

    Returns ``(baseline matches, additions)``. A live occurrence leaves the
    addition set only when the protected baseline records that exact
    ``(path, type, fingerprint, line)`` identity **and** the line still carries
    byte-identical content: the working-tree line text must reproduce the
    audited line text read from git history at the anchor commit.

    A bare four-part match is deliberately not sufficient. An audited
    fingerprint that never leaves its line while its key or surrounding
    context is rewritten -- a classified ``reference_sha256`` binding turned
    into an unclassified one, for instance -- keeps the same path, detector
    type, fingerprint and line number, so a line-number-only subtraction would
    silently clear it without ever consulting a structural classifier. With
    content evidence in the identity it has no audited counterpart, stays an
    addition, and must be proven harmless on that exact line or fail closed.
    """
    matched_with_content = _content_bearing_identities(
        observed, live_line_digests
    ) & _content_bearing_identities(audited, audited_line_digests)
    matched: set[tuple[str, str, str, int | None]] = {
        (path, finding_type, hashed, line_number)
        for path, finding_type, hashed, line_number, _ in matched_with_content
    }
    return matched, observed - matched


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
# closed. Each rule is additionally narrowed to *exact*, non-generic field
# names and *exact* file paths: dedicated, provably static content-registry
# documents only -- never executable source files, never ``*.py``. Extending
# either set is an R3 security decision, never a gate fix. Clearance is
# decided per reported line, so a value whose occurrences span a classified
# digest line and an unprovable line stays unclassified.

# The exact digest field names used by the repository's content registries.
# Only precise, non-generic names qualify: any other key -- ``api_sha256``,
# ``some_checksum``, a name merely ending in ``sha256``, and the generic
# ``sha256``/``checksum`` themselves -- stays unclassified.
_CONTENT_DIGEST_KEYS = frozenset(
    {
        "reference_sha256",
        "fragment_sha256",
        "claim_snapshot_sha256",
        "source_sha256",
    }
)
# The exact content-registry files whose 64-hex values are content digests by
# construction. Every entry is a dedicated, provably static registry document
# (JSON data, no executable content); an executable source file must never be
# added to this set, and the same exact key in any other file -- including
# every ``.py`` file -- stays unclassified.
_CONTENT_DIGEST_PATHS = frozenset(
    {
        "services/platform-core/app/static/prevalidated-commercial-sources/manifest.json",
        "services/operational-guidance/config/operational-process-catalog-v1.0.json",
        "services/platform-core/SOURCE_LOCK.json",
        "services/platform-core/docs/DEVELOPMENT_DISCOVERY_COMMERCIAL_V1.json",
    }
)
# A 64-hex content digest bound on its own line to exactly one of the digest
# keys: ``"reference_sha256": "<64 hex>"`` or ``source_sha256=<64 hex>``. The
# key alternation is generated from ``_CONTENT_DIGEST_KEYS`` (longest first),
# so the documented set and the compiled pattern can never drift apart.
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
    additions: set[tuple[str, str, str, int | None]],
    repo_root: Path,
) -> tuple[dict[str, int], set[tuple[str, str, str, int | None]]]:
    """Split live-but-unbaselined per-line findings into classified/unclassified.

    Returns ``(classified counts by classification name, unclassified set)``.
    Every finding that no structural classifier proves is returned as
    unclassified, so the caller fails closed on it.

    Classification is per line, never per digest: the addition identity is
    ``(path, detector type, fingerprint, line number)``, so a value already
    baselined on a classified line still puts every *new* line occurrence
    through the structural classifier on that exact line. Only the exact new
    lines are evaluated -- a baselined line never needs re-proving, and a new
    line that cannot be proven non-secret there keeps its own identity
    unclassified, even when the same digest is proven harmless elsewhere.
    A finding whose line number is absent, malformed or out of range can
    never be classified and stays unclassified.
    """
    by_path: dict[str, list[dict[str, Any]]] = {}
    for filename, findings in current.get("results", {}).items():
        by_path.setdefault(_normalize(str(filename)), []).extend(findings)
    remaining = set(additions)
    classified: dict[str, int] = {}
    for path in sorted({filename for filename, _, _, _ in additions}):
        # Minden addition-pathra újraolvassuk a fájlt: egy olvashatatlan
        # jelölt fail-closed ScanFailure marad, soha nem „üres bejegyzésként"
        # csendben átugrott. A read hibája a hívóban fail-closed.
        lines = _read_text_for_classification(repo_root / path)
        document = "\n".join(lines)
        entries = by_path.get(path, [])
        if not entries:
            # A dokumentum inkonzisztens (addition élő finding nélkül): az
            # identitások osztályozatlanok maradnak -- fail-closed a hívóban.
            continue
        for finding in entries:
            finding_type = str(finding.get("type", ""))
            hashed = str(finding.get("hashed_secret", ""))
            try:
                line_number = int(finding.get("line_number", 0))
            except (TypeError, ValueError):
                line_number = 0
            if (path, finding_type, hashed, line_number) not in remaining:
                continue
            rule = _STRUCTURAL_CLASSIFIERS.get(finding_type)
            if rule is None:
                continue
            name, predicate = rule
            # 1-based and in range, or this line stays unclassified. A
            # zero or negative number must never wrap around to another
            # line.
            if not 1 <= line_number <= len(lines):
                continue
            if not predicate(lines[line_number - 1], hashed, document, path):
                continue
            classified[name] = classified.get(name, 0) + 1
            # Each new line occurrence of a digest is evaluated and counted
            # on its own line, and only when that exact line was proven
            # non-secret.
            remaining.discard((path, finding_type, hashed, line_number))
    return classified, remaining


def _emit_unmatched_audit(
    additions: set[tuple[str, str, str, int | None]], repo_root: Path
) -> Path:
    """Write the bounded hash/path/line-only audit for unmatched candidates.

    Rows carry the normalized path, the detector type, the SHA-1
    fingerprints and the finding line numbers only -- never plaintext secret
    material -- and are marked unclassified. The artifact is written to the
    git-ignored runtime directory, so only a failing (fail-closed) run
    writes anything.

    The report is deliberately bounded: at most ``_AUDIT_MAX_ROWS`` rows and
    ``_AUDIT_MAX_HASHES_PER_ROW`` per-line entries per row. Truncation is
    never silent -- the omitted counts are stated explicitly and the totals
    always describe the full finding set -- so the artifact stays short
    enough to read in a review without ever understating what failed closed.

    This file is write-only evidence. Nothing in this module reads it back,
    so it can never act as an allowlist, baseline or suppression input.
    """
    by_path: dict[str, dict[str, list[tuple[str, int | None]]]] = {}
    for filename, finding_type, hashed, line_number in additions:
        by_path.setdefault(filename, {}).setdefault(finding_type, []).append((hashed, line_number))

    def _sorted_entries(
        entries: list[tuple[str, int | None]],
    ) -> list[tuple[str, int | None]]:
        # Sort by fingerprint, then by line number; a ``None`` line sorts
        # last without ever comparing against an int (which would raise).
        return sorted(set(entries), key=lambda pair: (pair[0], pair[1] is None, pair[1] or -1))

    every_row: list[tuple[str, str, list[tuple[str, int | None]]]] = [
        (filename, finding_type, _sorted_entries(by_path[filename][finding_type]))
        for filename in sorted(by_path)
        for finding_type in sorted(by_path[filename])
    ]
    rows: list[dict[str, Any]] = []
    for filename, finding_type, entries in every_row[:_AUDIT_MAX_ROWS]:
        bounded = entries[:_AUDIT_MAX_HASHES_PER_ROW]
        row: dict[str, Any] = {
            "path": filename,
            "type": finding_type,
            "classification": "unclassified",
            "findingCount": len(entries),
            "hashes": [hashed for hashed, _ in bounded],
            "lineNumbers": [line_number for _, line_number in bounded],
        }
        if len(entries) > _AUDIT_MAX_HASHES_PER_ROW:
            row["hashesOmitted"] = len(entries) - _AUDIT_MAX_HASHES_PER_ROW
        rows.append(row)
    document: dict[str, Any] = {
        "schemaVersion": "3.1",
        "kind": "tracked-secret-delta-audit",
        "scope": (
            "normalized paths, detector types, SHA-1 fingerprints and finding "
            "line numbers only; no plaintext secret material"
        ),
        "usage": (
            "untracked runtime report only; never read back as allowlist, "
            "baseline or suppression input"
        ),
        "classification": "unclassified",
        "generatedAt": datetime.now(UTC).isoformat(),
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
    the protected baseline, reconciled with the audited repository state (see
    ``_audited_occurrence_identities``) or proven non-secret by a structural
    classifier (stale-only entries, scanner-exempt files and the per-class
    classified counts are reported as documented warnings). Status 1: at
    least one live candidate is unclassified -- a bounded
    hash/path/line-only audit report is written to the git-ignored runtime
    directory. Status 2: missing or malformed baseline, any scanner/git
    failure or canonical-set condition. The live scan always runs; there is
    no snapshot or environment bypass. Messages never contain secret
    material, only file paths/counts and fingerprints. Comparison is
    occurrence-aware, strictly per line and always content-bearing: a
    baseline entry clears a live occurrence only when the line still carries
    byte-identical content, an audited occurrence reconciles on its own line
    or on a shifted line only when immutable line-content evidence proves it
    is that same occurrence (never an aggregate count and never a bare line
    number), and every other occurrence must still be proven harmless by a
    structural classifier on its exact line (see the module docstring).
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
    audited_anchor = ""
    audited_state: set[tuple[str, str, str, int]] = set()
    audited_line_digests: dict[str, dict[int, str]] = {}
    live_line_digests: dict[str, dict[int, str]] = {}
    try:
        # A sor-szintű, megváltoztathatatlan tartalmi bizonyíték MINDEN élő
        # találat identitásához kell -- a baseline-kivonáshoz is, nem csak az
        # elcsúszott előfordulások egyeztetéséhez --, ezért az összes találatot
        # hordozó path bizonyítéka egyszerre készül el.
        finding_paths = sorted({filename for filename, _, _, _ in observed})
        if finding_paths:
            audited_anchor = _baseline_anchor_commit(root, baseline_path)
            audited_line_digests = _audited_line_content_digests(
                root, audited_anchor, finding_paths
            )
            live_line_digests = _live_line_content_digests(root, finding_paths)
        baseline_matched, additions = _split_baseline_matches(
            observed, audited, audited_line_digests, live_line_digests
        )
        if additions:
            addition_paths = sorted({filename for filename, _, _, _ in additions})
            audited_state = _audited_occurrence_identities(root, audited_anchor, addition_paths)
        resolved, remaining = _split_additions(
            additions, observed, audited_state, audited_line_digests, live_line_digests
        )
        classified, unclassified = _classify_additions(current, remaining, root)
    except ScanFailure as exc:
        return 2, str(exc)
    if unclassified:
        locations = sorted({filename for filename, _, _, _ in unclassified})
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
    # Only occurrences whose baseline identity is backed by byte-identical line
    # content may be reported as "matching the audited baseline"; audited-state
    # reconciliations and structurally classified candidates are counted
    # separately, so the message can never overstate how much the protected
    # baseline covers.
    parts = [f"{len(baseline_matched)} tracked candidate(s) match the audited baseline"]
    if resolved:
        parts.append(
            f"{len(resolved)} candidate(s) reconcile with the audited repository "
            f"state at commit {audited_anchor[:12]}"
        )
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


def _match_occurrences(
    audited_lines: list[int],
    live_lines: list[int],
    audited_digests: dict[int, str],
    live_digests: dict[int, str],
) -> dict[int, int]:
    """Maximum one-to-one seating of live occurrences on audited occurrences.

    Returns ``{audited line: live line}``: the audited occurrences that are
    proven still live, and which live occurrence each one accounts for. Every
    live occurrence left unseated is a new occurrence and stays an addition.

    Seating requires byte-identical line content on both sides -- there is no
    bare line-number path here at all. A shared line number without shared
    content proves only that *something* still sits at that offset, which is
    exactly the substitution this module must reject: an audited fingerprint
    whose line was rewritten from a classified context to an unclassified one
    keeps its number and loses its evidence, so it stays an addition.

    Byte-identical line content is an *equivalence* relation, so the
    content-proof graph is a disjoint union of complete bipartite blocks --
    one per content fingerprint. Maximum matching therefore needs no search:
    inside a block, ``min(live, audited)`` occurrences seat, and an
    occurrence that is unchanged in place (its live line is also an audited
    line of the same content) seats first, so a stronger claim is never
    displaced by a weaker one. A file whose block drifted wholesale still
    seats perfectly, because every occurrence in it carries its own content
    proof.

    A line with no content fingerprint on either side (out of range, or a
    file with no audited content evidence) never forms a content edge and
    therefore never seats. All iteration is over sorted inputs, so the result
    is deterministic.
    """
    audited_by_content: dict[str, list[int]] = {}
    for audited_line in audited_lines:
        content = audited_digests.get(audited_line)
        if content is not None:
            audited_by_content.setdefault(content, []).append(audited_line)
    live_by_content: dict[str, list[int]] = {}
    for live_line in live_lines:
        content = live_digests.get(live_line)
        if content is not None:
            live_by_content.setdefault(content, []).append(live_line)

    assignment: dict[int, int] = {}
    seated_live: set[int] = set()
    for content, block_audited in sorted(audited_by_content.items()):
        block_live = live_by_content.get(content, [])
        block_audited_set = set(block_audited)
        # Előbb a helyükön változatlan előfordulások ülnek le, csak utána a
        # bizonyítottan elcsúszottak -- így egy változatlan előfordulást
        # sosem szoríthat ki egy elcsúszott másolat.
        for line in block_live:
            if line in block_audited_set:
                assignment[line] = line
                seated_live.add(line)
        free_audited = [line for line in block_audited if line not in assignment]
        drifted = [line for line in block_live if line not in seated_live]
        for audited_line, live_line in zip(free_audited, drifted, strict=False):
            assignment[audited_line] = live_line
            seated_live.add(live_line)
    return assignment


def _split_additions(
    additions: set[tuple[str, str, str, int | None]],
    observed: set[tuple[str, str, str, int | None]],
    audited_state: set[tuple[str, str, str, int]],
    audited_line_digests: dict[str, dict[int, str]],
    live_line_digests: dict[str, dict[int, str]],
) -> tuple[
    set[tuple[str, str, str, int | None]],
    set[tuple[str, str, str, int | None]],
]:
    """Split live-but-unbaselined identities into reconciled and remaining.

    Strict per-line identity, with no aggregate-count substitution anywhere.
    Per ``(path, type, fingerprint)`` value, the live occurrences are matched
    one-to-one against the audited occurrences of that same value. Only a
    live occurrence that is *individually* matched to an audited occurrence
    counts as pre-existing; every unmatched one stays an addition and must be
    proven harmless by a structural classifier on its exact line.

    A live occurrence may be seated on an audited occurrence only on
    immutable content evidence, in strictly decreasing strength (see
    ``_match_occurrences``):

    1. same line number *and* byte-identical line content -- the audited
       occurrence demonstrably still sits untouched where it was audited;
    2. byte-identical line content -- the audited occurrence is proven to be
       this very occurrence, shifted by an unrelated edit above it. Both
       sides are compared as SHA-256 content fingerprints, one taken from git
       history at the anchor commit, one from the working tree.

    There is deliberately no third, weaker rule: a shared line number without
    shared content never seats. The strongest available evidence is committed
    first, so an occurrence that is unchanged in place can never be displaced
    by a weaker claim, and a value audited once that now appears twice can
    never have both copies cleared.

    Equivalence is therefore proven per occurrence, never inferred from how
    many occurrences a value happens to have and never from where it sits: an
    audited digest deleted from its classified line and reintroduced on a
    different, unclassified line has no edge at all and fails closed, even
    though the total count is unchanged; so does an audited digest that stayed
    on its line while its key or context was rewritten. Because the
    structural classifiers decide on exactly that line text (plus the
    unchanged path), byte-identical content cannot smuggle a classified key,
    context or position into an unclassified one -- any change to the line
    breaks the proof.

    An identity without a usable line number, one in a file with no audited
    content evidence (new at the audited commit, or not UTF-8 decodable
    there), and one whose live line is out of range never reconcile through
    the audited state: they always stay remaining (fail closed). Ordering is
    fully sorted, so the split is deterministic.
    """
    audited_by_value: dict[tuple[str, str, str], set[int]] = {}
    for path, finding_type, hashed, line_number in audited_state:
        audited_by_value.setdefault((path, finding_type, hashed), set()).add(line_number)
    live_by_value: dict[tuple[str, str, str], set[int]] = {}
    for path, finding_type, hashed, line_number in observed:
        if line_number is None:
            continue
        live_by_value.setdefault((path, finding_type, hashed), set()).add(line_number)

    matched: set[tuple[str, str, str, int]] = set()
    for value_key, audited_lines in sorted(audited_by_value.items()):
        path = value_key[0]
        assignment = _match_occurrences(
            sorted(audited_lines),
            sorted(live_by_value.get(value_key, frozenset())),
            audited_line_digests.get(path, {}),
            live_line_digests.get(path, {}),
        )
        matched.update((*value_key, live_line) for live_line in assignment.values())

    resolved: set[tuple[str, str, str, int | None]] = set()
    remaining: set[tuple[str, str, str, int | None]] = set()
    for identity in sorted(additions, key=_addition_sort_key):
        path, finding_type, hashed, line_number = identity
        if line_number is not None and (path, finding_type, hashed, line_number) in matched:
            resolved.add(identity)
        else:
            remaining.add(identity)
    return resolved, remaining


def _addition_sort_key(
    identity: tuple[str, str, str, int | None],
) -> tuple[str, str, str, bool, int]:
    """Total order over addition identities, tolerating a missing line number."""
    path, finding_type, hashed, line_number = identity
    return (path, finding_type, hashed, line_number is None, line_number or 0)


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
