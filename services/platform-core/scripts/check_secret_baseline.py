"""Fail when tracked files contain secret candidates absent from the audited set.

The comparison logic lives in ``reconcile_tracked_secrets`` so the platform-core
local reconciliation command reuses exactly this canonical implementation
instead of duplicating a weaker parser. Messages never contain secret material;
only tracked file paths, counts and SHA-1 fingerprints are reported.

Tracked-file contract (canonical and cross-platform):

* the candidate set comes from ``git ls-files``: only regular-file index
  entries (100644/100755) are candidates, so symlink/gitlink entries,
  untracked, ignored, build, cache and runtime files can never influence the
  result; index records are strictly validated. The baseline file and this
  script's own runtime audit output are each excluded exactly once, so the
  scanner can never re-scan the fingerprints it just wrote. Paths are
  normalized to forward slashes and sorted, so chunking is identical
  everywhere; duplicates after normalization always fail closed, and
  case-only pairs fail closed only on case-insensitive platforms
  (``os.path.normcase``);
* the pinned scanner is fed only that bounded set, through a dedicated
  driver subprocess (``_detect_secrets_scan_driver.py``) calling the pinned
  package's own ``scan.scan_file`` per file with the list on stdin (no
  command-line length limit, no repository walk). The subprocess is forced
  into UTF-8 mode, because file *decoding* -- not file selection -- is the
  cross-platform divergence: the scanner's bare ``open()`` silently drops
  files raising ``UnicodeDecodeError`` under the host locale (cp1250 on a
  Hungarian Windows host skips UTF-8 text that Linux scans). Forced UTF-8
  makes both platforms identical and never suppresses a finding;
* per-file coverage is proven, not assumed: every candidate is classified
  as scanned or scanner-exempt (the pinned scanner's own filename filters,
  imported so they can never drift, plus not-UTF-8 content) and exempt
  files are reported by path; the driver's stderr accounting (one
  ``Checking file:`` line per opened file) is parsed, sentinel probes are
  excluded from it by basename prefix (path-independent on either separator
  style), and the remaining accounted set must equal the requested set
  exactly: a requested file absent from it fails closed with status 2, and
  an accounted file outside the requested set fails closed with status 2
  as well. Each chunk carries a synthetic
  sentinel probe whose known fingerprint must appear in that chunk's
  output -- on the exact line number this module's own scanner-compatible
  line model predicts for separator-bearing content, so U+2028/U+2029 line
  identity is verified live against the pinned driver on every scan run,
  not only by tests. Probes are scratch files written to a per-run,
  per-process private directory under the git-ignored runtime tree, so no
  parallel or earlier scan of any other process can enter a run's bounded
  input set; they are removed with the run whatever its outcome (success,
  assertion, exception or timeout). Any git/driver error, missing
  candidate, malformed
  output, duplicate or ambiguous path, lost chunk coverage, missing sentinel
  detection or driver output outside the canonical set fails closed with
  status 2. The scanner version is pinned and verified.

Audited-set contract:

* the audited set is exactly ``.secrets.baseline`` (protected; its rotation
  is a separate R3 attestation). There is no committed allowlist, delta file
  or suppression list next to it, and **no artifact this script writes is
  ever read back as input** -- the audit output is a report, never a filter;
* the audited identity is occurrence-aware **and content-bearing**:
  ``(normalized path, detector type, SHA-1 fingerprint, line number, SHA-256
  line-content fingerprint)``. The fifth part is immutable evidence, not a
  position: the audited side takes it from git history at the audited
  anchor commit, the live side from the working tree, so the two sides can
  only ever agree on *bytes*. A bare line-number match is therefore never
  sufficient anywhere in this module: an audited fingerprint whose line was
  rewritten from a classified context to an unclassified one stays an
  addition and must be proven harmless by a structural classifier on that
  exact line or fail closed; a baselined value can never suppress a new
  occurrence on any other line; an identity without a usable line number or
  line-content evidence on either side can never match;
* the audited *occurrence set* is normalized from git history, not assumed
  from the baseline document alone: the protected baseline records each
  audited value once and skips host-locale undecodable files, so repeated
  values, line drift and decode-skips are documented representation gaps,
  not secret additions. The audited set is re-derived by scanning the
  tracked file versions at the audited anchor commit (the commit that last
  modified the baseline) with the same pinned, forced-UTF-8, per-line
  driver, through a dedicated seam (``_run_audited_driver``), with temp
  copies under the git-ignored runtime directory, always removed. Within
  one command the same unchanged input is never scanned twice: an addition
  file whose live working-tree bytes equal its audited-commit bytes takes
  its audited identities from the already-run live scan (the deterministic
  scan of exactly those bytes) instead of being re-scanned; only
  byte-different content is re-scanned. A
  baseline that is untracked, uncommitted or outside the reconciled root
  fails closed (status 2), and a file absent at the audited commit has no
  audited state -- every finding in it fails closed unless structurally
  classified;
* reconciliation is occurrence-aware, strictly per line, always backed by
  immutable line-content evidence, and injective: every audited occurrence
  backs at most one live occurrence, an unchanged-in-place occurrence
  claims its audited occurrence first, and neither aggregate counts nor
  bare line numbers are ever a reconciliation input. An audited digest
  deleted from its classified line and reintroduced on a different,
  unclassified line stays an addition, and so does one whose line text was
  rewritten -- one unprovable line fails closed, even when the same digest
  is audited or classified elsewhere;
* a live candidate outside the baseline is cleared only by a *structural
  classifier* (``_STRUCTURAL_CLASSIFIERS``): it re-reads the reported line
  from the working tree, extracts the token it considers non-secret by
  construction, and only clears the finding when ``sha1(token)`` reproduces
  the scanner's fingerprint. The two classes are narrow on both axes:
  ``content-digest`` (a 64-hex value bound to exactly one of
  ``reference_sha256``/``fragment_sha256``/``claim_snapshot_sha256``/
  ``source_sha256``, only inside the dedicated, provably static
  content-registry files -- never executable source, never a generic key
  such as ``sha256``/``checksum``) and ``drive-resource-id`` (the documented
  ``1`` + 32/43 ``[A-Za-z0-9_-]`` Drive/Docs form bound to exactly
  ``id``/``sourceId`` in the two Drive index files, corroborated by a
  Drive/Docs URL or an explicit ``drive`` provenance marker). Classification
  is per line, never per digest; every candidate that neither the baseline
  nor a classifier clears is **unclassified**, and unclassified means fail
  closed with status 1 -- new detector types, new files and new value
  shapes all land here by default;
* residual risk, stated explicitly: a classifier decides on *exact field
  name, exact file path and shape*, so a genuine secret deliberately stored
  in the exact cleared shape would be cleared. Both require an attacker to
  control an exact field name inside an exact documented file, which is a
  reviewable source change, not a silent one. Extending either rule is a
  security decision needing a documented R3 attestation; never a gate fix;
* a failing run additionally writes a *bounded* hash/path-only audit report
  (``_AUDIT_MAX_ROWS`` rows, ``_AUDIT_MAX_HASHES_PER_ROW`` fingerprints per
  row, the truncated remainder counted explicitly) to the git-ignored
  ``<repo root>/services/platform-core/runtime/tracked-secret-delta-audit.json``
  -- untracked runtime evidence, never dirtying the tracked worktree;
* there is no snapshot or environment seam anywhere in this module: the live
  scan can never be bypassed from a command line or an environment variable.
  Tests exercise failure paths exclusively through direct pytest
  ``monkeypatch`` seams (pytest-bound, process-local), which cannot affect
  the command-level behavior of this script or of ``reconciliation.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = REPO_ROOT / ".secrets.baseline"
_BASELINE_EXCLUDE_REGEX = r"(^|[\\/])\.secrets\.baseline$"
_REGULAR_MODES = {"100644", "100755"}
# Symlink (120000) and gitlink (160000) entries are documented non-regular
# index entries and are never candidates; every other mode fails closed.
_KNOWN_INDEX_MODES = _REGULAR_MODES | {"120000", "160000"}
_SCAN_CHUNK_SIZE = 100
# Chunk-driver work-sharing is bounded and auditable by construction: each
# chunk runs its own pinned driver subprocess (the public ``scan.scan_file``
# path, one serial scan per file, no pool inside the driver), the thread pool
# only ever holds this many concurrent subprocesses, and every driver has no
# children of its own -- no nested process-pool explosion and no orphan child
# can occur under pytest/Windows. The sentinel probes and the per-file
# ``Checking file:`` accounting keep every chunk's coverage fail-closed.
# Worker selection is CPU-bounded (review LOW): never more than the
# documented 4-driver cap, never more drivers than available cores, and
# never zero on a host that reports no CPU count -- so a scan running inside
# the official test suites never over-allocates CPU and never starves
# pytest or the other probes.
_SCAN_WORKERS = min(4, max(1, os.cpu_count() or 1))
# A single candidate this large or larger always forms its own chunk (see
# ``_solo_split_chunks``): the pinned driver scans one file at a time inside
# a chunk, so one many-megabyte file serializes its chunk neighbours and
# decides the whole bounded scan wall time by itself.
_SOLO_CHUNK_MIN_BYTES = 512 * 1024
# The scanner pinned by requirements-dev.txt; a different version may ship
# different detectors or entropy limits, silently changing every fingerprint,
# so a mismatch fails closed instead of producing a delta.
_PINNED_SCANNER_VERSION = "1.5.0"
_SCANNER_DISTRIBUTION = "detect-secrets"
_DRIVER_PATH = Path(__file__).with_name("_detect_secrets_scan_driver.py")
# Decoding determinism, not cosmetics: PYTHONUTF8 forces the driver's bare
# ``open()`` calls to UTF-8 on every host and PYTHONIOENCODING pins the
# encodings we decode strictly, so an ambient locale cannot alter the result.
_SCANNER_ENV_OVERRIDES = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
# Narrow, documented allowlist of transient Windows subprocess-start failures:
# under heavy parallel load Windows can reject a fresh process with
# STATUS_DLL_INIT_FAILED (0xC0000142, exit code 3221225794) and the identical
# spawn succeeds a moment later. Only this code, only on Windows, is retried
# with bounded short delays; every other failure stays fail-closed.
_SPAWN_RETRY_DELAYS = (0.2, 0.5)
_TRANSIENT_WINDOWS_START_CODES = {3221225794}
# Runtime artifact emitted only when live candidates remain unmatched; the
# platform-core ``runtime`` directory is git-ignored, so a passing gate never
# writes and even a failing gate never dirties the tracked worktree. The
# artifact is write-only for the scanner: nothing reads it back as input.
_UNMATCHED_AUDIT_RELATIVE_PATH = (
    "services",
    "platform-core",
    "runtime",
    "tracked-secret-delta-audit.json",
)
# The audit is a short review aid, not a data dump: bounded rows and hashes,
# and the truncated remainder is always an explicit count, never silent.
_AUDIT_MAX_ROWS = 25
_AUDIT_MAX_HASHES_PER_ROW = 5
_PROBE_PREFIX = ".secrets-scan-probe-"
# Sentinel probes are scratch files: they live under the git-ignored runtime
# directory in a per-run, per-process subdirectory, never at the repository
# root. A scan run therefore never sees another run's or another process's
# probe on disk, a killed process can only leave an ignored remnant inside
# its own private directory, and the whole run directory is removed with the
# scan whatever its outcome (success, assertion, exception or timeout).
_PROBE_RELATIVE_DIR = ("services", "platform-core", "runtime", "secret-scan-probes")
_CHECKING_FILE_PREFIX = "Checking file: "
# The audited-state scan writes temporary copies of the audited file versions
# under the git-ignored runtime directory (sibling of the audit artifact), so
# no historical content can ever dirty the tracked worktree. The original
# basename is kept, so the driver's filename-level filters classify the temp
# copy exactly like the live candidate.
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
    """Deterministic platform path semantics via ``os.path.normcase``:

    Windows-style platforms fold case, so case-only pairs are ambiguous
    there; POSIX keeps case and such distinct paths are legal.
    """
    return os.path.normcase("A") == os.path.normcase("a")


def _unmatched_audit_path(repo_root: Path) -> Path:
    return repo_root.joinpath(*_UNMATCHED_AUDIT_RELATIVE_PATH)


def _audit_output_relative_path() -> str:
    """The scanner's own audit output, as a normalized repository path."""
    return "/".join(_UNMATCHED_AUDIT_RELATIVE_PATH)


def _scanner_filename_predicates() -> tuple[Any, Any, Any]:
    """The pinned scanner's filename-level skip predicates, imported from
    the pinned package so the exemption classification can never drift:
    ignored-extension suffix, lock-file basename and ``swagger`` path.
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


_PROBE_SECRET_VALUE: str | None = None


def _probe_secret_value() -> str:
    """Runtime-generated, per-process synthetic sentinel: a stable synthetic
    marker plus a fresh unpredictable nonce. The value therefore never exists
    in this source, is never a production credential and cannot be reused
    across runs; the module-level cache keeps it stable within one process
    so the probe text, the expected line number and the expected fingerprint
    always agree."""
    global _PROBE_SECRET_VALUE
    if _PROBE_SECRET_VALUE is None:
        _PROBE_SECRET_VALUE = "".join(
            ("Synthetic", "PlaintextValue", "-", secrets.token_hex(8))
        )
    return _PROBE_SECRET_VALUE


# U+2028 LINE SEPARATOR és U+2029 PARAGRAPH SEPARATOR: a pinned scanner
# text-mode ``open()`` + ``readlines()`` útvonala NEM tördel ezeknél, a
# ``str.splitlines()`` viszont igen -- ez a különbség a sorazonossági seam.
# A futás során minden chunk szentinel probe-ja ezt a két karaktert hordozza,
# és a scanner a titkos sorát pontosan azon a sorszámon kell jelentse, amelyet
# a ``_universal_newline_lines`` modell jósol; eltérés minden futásban
# fail-closed (status 2).
_UNICODE_LINE_SEPARATOR = "\u2028"  # escape form; the file never carries the literal
_UNICODE_PARAGRAPH_SEPARATOR = "\u2029"  # escape form; the file never carries the literal


def _probe_assignment_key() -> str:
    """Runtime-assembled assignment keyword: the committed source never
    carries a credential-assignment literal, while the emitted probe keeps
    the exact pattern the pinned scanner's keyword detector requires."""
    return "".join(("pass", "word"))


def _probe_text() -> str:
    """Separator-bearing sentinel content: line 1 carries U+2028/U+2029 inline,
    the synthetic secret sits on line 2 under universal-newline semantics.
    (``str.splitlines()`` would split at both separators and push the secret
    to line 4 -- the live parity check catches that drift in either
    direction.) The assignment keyword is assembled at runtime (see
    ``_probe_assignment_key``), so no credential-assignment literal exists
    in this source."""
    first_line = (
        f"probe-preamble{_UNICODE_LINE_SEPARATOR}middle{_UNICODE_PARAGRAPH_SEPARATOR}tail\n"
    )
    return first_line + _probe_assignment_key() + " = '" + _probe_secret_value() + "'\n"


def _run_git_checked(repo_root: Path, *args: str) -> bytes:
    """``git -C <repo> <args...>`` with the documented bounded transient retry.

    Shared by every git invocation of this module, so the transient
    Windows-start retry and its fail-closed exhaustion behave identically for
    all of them.
    """
    command = ["git", "-C", str(repo_root), *args]
    for attempt in range(1, len(_SPAWN_RETRY_DELAYS) + 2):
        try:
            return subprocess.check_output(command, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as exc:
            if attempt <= len(_SPAWN_RETRY_DELAYS) and _is_transient_windows_start_failure(
                exc.returncode
            ):
                time.sleep(_SPAWN_RETRY_DELAYS[attempt - 1])
                continue
            raise
    raise ScanFailure("git retry loop exhausted.")  # pragma: no cover


def _run_git_ls_files(repo_root: Path) -> bytes:
    """Run ``git ls-files`` once; bounded transient retry. Module-local seam."""
    return _run_git_checked(repo_root, "-c", "core.quotepath=false", "ls-files", "-s", "-z")


def _parse_git_ls_files(raw: bytes) -> list[str]:
    """Parse ``git ls-files -s -z`` records with strict validation.

    A record is ``<mode> SP <40-hex sha1> SP <stage> TAB <path>``; with ``-z``
    the path is raw bytes, so a tab inside a filename survives parsing
    intact (everything after the first tab is the path). Unknown mode,
    malformed object id or stage, or missing path fails closed instead of
    silently skipping a file. Symlink/gitlink modes are the single
    documented non-regular category and are skipped.
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
    """``git log -1 --format=%H`` of the baseline file; module-local seam."""
    return _run_git_checked(repo_root, "log", "-1", "--format=%H", "--", relative_path).decode(
        "utf-8"
    ).strip()


def _baseline_anchor_commit(repo_root: Path, baseline_path: Path) -> str:
    """The commit that last modified the protected baseline in git history.

    The audited occurrence state is reconstructed from the tracked file
    versions at this commit, so the anchor must exist (untracked,
    uncommitted or outside-root baselines fail closed) and the object id is
    validated as a 40-hex sha before any use as a git rev argument.
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
    """``git show <anchor>:<path>`` raw bytes; module-local seam for the
    audited-state tests. ``CalledProcessError`` means the path did not exist
    at the audited commit (the documented new-file case); the caller maps
    that to an absent audited state, which fails closed for every live
    finding in that file."""
    return _run_git_checked(repo_root, "show", f"{anchor}:{path}")


def _audited_file_bytes(repo_root: Path, anchor: str, path: str) -> bytes | None:
    """Tracked file content at the audited commit; ``None`` when absent.

    A path absent at the audited commit has no audited state: every live
    finding in it fails closed unless structurally classified.
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
    excluded exactly once, so the scanner can never re-scan the SHA-1
    fingerprints it just wrote (a self-sustaining delta). The audit already
    lives in a git-ignored directory; this is a second, explicit barrier.
    Raises ScanFailure on git errors or malformed index output; the derived
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
        pass  # outside the reconciled root, so never a candidate anyway
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

    Applies at the point of use, independent of how the list was derived: an
    empty set, duplicate paths after normalization, paths differing only by
    case on a case-insensitive platform, or a candidate file missing or
    non-regular on disk all fail closed. Returns the normalized, sorted list.
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

    Exempts exactly what the pinned scanner silently skips: its own filename
    filters (imported from the pinned package so they can never drift) plus
    not-UTF-8 content; exempt files are reported by path, and an unreadable
    candidate fails closed.
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
    """Fail closed unless the installed scanner is exactly the pinned
    version (the driver imports the same installed distribution)."""
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
    prints the deterministic results document on stdout plus the scanner's
    per-file ``Checking file:`` accounting on stderr. Bounded retry applies
    only to the documented transient Windows process-start failure.
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


def _probe_basename(chunk_index: int) -> str:
    """The sentinel probe basename for a chunk: prefix, chunk index, process id."""
    return f"{_PROBE_PREFIX}{chunk_index}-{os.getpid()}.txt"


def _expected_probe_line_number() -> int:
    """The line on which ``_probe_text`` places the synthetic secret under
    this module's own scanner-compatible line model.

    Derived from ``_universal_newline_lines``, not hard-coded: if the model
    ever drifts from the pinned scanner's text-mode numbering (for example
    by splitting on U+2028/U+2029), the expectation moves with it and the
    live parity check against the real driver output fails closed.
    """
    sentinel = _probe_secret_value()
    for index, line in enumerate(_universal_newline_lines(_probe_text()), start=1):
        if sentinel in line:
            return index
    raise ScanFailure("separator probe has no expected line.")  # pragma: no cover


def _expected_probe_fingerprint() -> tuple[str, str, int]:
    """(type, fingerprint, expected line) -- the full live-parity identity."""
    return (
        "Secret Keyword",
        hashlib.sha1(_probe_secret_value().encode("utf-8")).hexdigest(),
        _expected_probe_line_number(),
    )


def _is_probe_name(path: str) -> bool:
    """Path-independent sentinel-probe identification by basename prefix.

    Probes live under the per-run nested runtime directory, so their full
    path never starts with the prefix; only the basename does, on either
    separator style. The probe runtime tree is git-ignored, so no tracked
    candidate can carry the prefix -- the basename test can only exempt this
    run's own sentinel scratch files from the accounted set.
    """
    return PurePosixPath(_normalize(path)).name.startswith(_PROBE_PREFIX)


def _accounted_files(stderr: bytes) -> set[str]:
    """Parse the scanner's own per-file accounting from its INFO log.

    The pinned scanner logs ``Checking file: <path>`` for every file it
    actually opens; a file that never appears here was never scanned --
    whatever the reason -- and the caller fails closed. Sentinel probes are
    excluded by basename prefix, path-independently, so the accounted set is
    exactly the requested files on the success path. Non-UTF-8 stderr cannot
    prove coverage and fails closed here too.
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
        name = _normalize(line[marker + len(_CHECKING_FILE_PREFIX) :].strip())
        if _is_probe_name(name):
            continue
        accounted.add(name)
    return accounted


def _candidate_size(repo_root: Path, path: str) -> int:
    """Byte size of a candidate; 0 when unreadable (a packing hint only)."""
    try:
        return (repo_root / _normalize(path)).stat().st_size
    except OSError:
        return 0


def _chunk_cost(chunk: list[str], repo_root: Path) -> int:
    """The estimated scan cost of a chunk: its largest file's byte size.

    Used only for the deterministic submission order of the bounded chunk
    pool; it never influences which files are scanned or any fail-closed
    condition."""
    largest = 0
    for path in chunk:
        size = _candidate_size(repo_root, path)
        if size > largest:
            largest = size
    return largest


def _solo_split_chunks(chunks: list[list[str]], repo_root: Path) -> list[list[str]]:
    """Give every oversized candidate its own chunk, deterministically.

    The pinned driver scans one file at a time inside a chunk, so a single
    many-megabyte file serializes the rest of its chunk and decides the
    whole bounded scan wall time by itself. Splitting such files into solo
    chunks lets the other workers absorb their chunk neighbours while the
    oversized file scans alone. Which file belongs to which chunk stays the
    consecutive sorted split -- only the packing changes, so nothing about
    what is scanned, the per-chunk sentinel probes or the exact-set
    accounting is affected. Relative order is preserved throughout, so the
    result is deterministic on every host.
    """
    result: list[list[str]] = []
    for chunk in chunks:
        solo: list[str] = []
        rest: list[str] = []
        for path in chunk:
            if _candidate_size(repo_root, path) >= _SOLO_CHUNK_MIN_BYTES:
                solo.append(path)
            else:
                rest.append(path)
        result.extend([path] for path in solo)
        if rest:
            result.append(rest)
    return result


def _scan_file_set(
    files: list[str],
    repo_root: Path,
    runner: Any,
) -> dict[str, Any]:
    """Chunked, sentinel-probed, coverage-accounted scan via ``runner``.

    Shared by the live and audited-state scans, so the audited state has
    exactly the live-scan strength. Every requested path is passed exactly
    once; output outside the requested set fails closed. Per-file coverage
    is proven as an exact set: the driver stderr carries the scanner's
    ``Checking file:`` line per opened file, sentinel probes are excluded
    from that set by basename prefix (path-independently), and the remaining
    accounted set must equal the requested set in both directions -- a
    requested file absent from it fails closed, and an accounted file
    outside the requested set fails closed too. Oversized candidates ride
    solo chunks (``_solo_split_chunks``) so one many-megabyte file never
    serializes its neighbours; the packing change alters nothing about what
    is scanned. Each chunk carries a sentinel probe whose known fingerprint
    must appear in the chunk output on the exact line this module's
    scanner-compatible line model predicts for U+2028/U+2029-bearing
    content -- the live scanner-versus-classifier line-identity parity
    check. Raises ScanFailure on driver errors, malformed output, lost
    coverage, exact-set mismatch, missing probe detection or probe
    write/delete errors.
    """
    if not files:
        raise ScanFailure("no candidate files to scan.")
    _assert_pinned_scanner()
    chunks = [
        files[index : index + _SCAN_CHUNK_SIZE] for index in range(0, len(files), _SCAN_CHUNK_SIZE)
    ]
    chunks = _solo_split_chunks(chunks, repo_root)
    if sum(len(chunk) for chunk in chunks) != len(files):
        raise ScanFailure("candidate chunking lost files (incomplete coverage).")
    # Deterministic submission scheduling: the most expensive chunk starts
    # first, so a single many-line file can never land late in a worker
    # queue and serialize the whole bounded official time frame. Only the
    # *submission order* changes -- which file belongs to which chunk stays
    # exactly the consecutive sorted split, and Python's stable sort keeps
    # the original index order for equal-cost chunks -- and the caller's
    # exact-set, per-chunk coverage and merge are order-insensitive, so this
    # changes nothing about what is scanned or about any fail-closed
    # condition.
    chunks.sort(key=lambda chunk: -_chunk_cost(chunk, repo_root))
    expected_type, expected_hash, expected_line = _expected_probe_fingerprint()
    # Per-run, per-process probe isolation: a fresh private directory under
    # the git-ignored runtime tree, so no parallel or earlier scan of any
    # other process can ever place a probe file into this run's input.
    run_dir = repo_root.joinpath(
        *_PROBE_RELATIVE_DIR, f"{os.getpid()}-{secrets.token_hex(4)}"
    )
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ScanFailure("sentinel probe run directory could not be created.") from exc

    def _probe_relative_name(chunk_index: int) -> str:
        return "/".join((*_PROBE_RELATIVE_DIR, run_dir.name, _probe_basename(chunk_index)))

    def _run_chunk(
        chunk_index: int, chunk: list[str]
    ) -> tuple[str, subprocess.CompletedProcess[bytes]]:
        probe_name = _probe_relative_name(chunk_index)
        probe_path = repo_root / _normalize(probe_name)
        try:
            try:
                probe_path.write_text(_probe_text(), encoding="utf-8")
            except OSError as exc:
                raise ScanFailure(f"sentinel probe could not be written: {probe_name}.") from exc
            return probe_name, runner([*chunk, probe_name], repo_root)
        finally:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ScanFailure(f"sentinel probe could not be removed: {probe_name}.") from exc

    try:
        with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
            completed = list(pool.map(lambda pair: _run_chunk(*pair), enumerate(chunks)))
    finally:
        # The whole private probe directory disappears with the scan,
        # whatever its outcome; leftovers from a hard-killed run therefore
        # stay confined to that run's own ignored directory, never the
        # repository root or any other run's bounded input set.
        shutil.rmtree(run_dir, ignore_errors=True)
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
                    and _normalized_line_number(finding) == expected_line
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
    extra = accounted - requested
    if extra:
        raise ScanFailure(
            "scanner accounted for file(s) outside the requested set: "
            + ", ".join(sorted(extra))
            + "."
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
    live_results: dict[str, Any] | None = None,
) -> set[tuple[str, str, str, int]]:
    """Per-line occurrence identities of the addition files at the audited commit.

    The baseline records each audited value once and skips host-locale
    undecodable files, so the audited occurrence set is re-derived by
    scanning the tracked file versions at the anchor commit with the same
    pinned, forced-UTF-8, per-line driver as the live scan. Temporary copies
    live under the git-ignored runtime directory with their original
    basename (so the driver's filename filters classify them identically)
    and are always removed; any write/scan/cleanup failure fails closed. A
    path absent at the audited commit contributes no audited state.

    Within one command the same unchanged input is never scanned twice:
    when the live working-tree bytes of an addition file equal the bytes at
    the audited commit, the pinned driver would re-derive exactly the live
    findings (same deterministic public path, same bytes), so the audited
    identities of that file are taken from ``live_results`` -- the already
    run live scan -- instead of re-scanning. Only byte-different content is
    re-scanned from a temp copy. This is an exact substitution, not a
    weakening: the live scan itself is the canonical scan of exactly those
    bytes, and its per-file coverage is already proven fail-closed.
    """
    if not addition_paths:
        return set()
    identities: set[tuple[str, str, str, int]] = set()
    live = live_results if live_results is not None else {}
    to_scan: list[str] = []
    for path in sorted(addition_paths):
        content = _audited_file_bytes(repo_root, anchor, path)
        if content is None:
            continue
        try:
            live_bytes = _read_candidate_bytes(repo_root / _normalize(path))
        except OSError as exc:
            raise ScanFailure(f"tracked candidate file cannot be read: {path}.") from exc
        if live_bytes == content:
            for finding in live.get(path, []):
                line_number = _normalized_line_number(finding)
                if line_number is None:
                    # Auditált előfordulás használható sor nélkül sosem
                    # egyeztethet -- a hívó fail-closed marad.
                    continue
                identities.add(
                    (
                        path,
                        str(finding.get("type", "")),
                        str(finding.get("hashed_secret", "")),
                        line_number,
                    )
                )
            continue
        to_scan.append(path)
    if not to_scan:
        return identities
    temp_root = repo_root.joinpath(*_HISTORICAL_SCAN_RELATIVE_DIR)
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ScanFailure("audited-state temp directory could not be created.") from exc
    written: list[Path] = []
    mapping: dict[str, str] = {}
    try:
        for index, path in enumerate(sorted(to_scan)):
            content = _audited_file_bytes(repo_root, anchor, path)
            if content is None:
                continue
            temp_path = temp_root / f"{index}-{Path(path).name}"
            try:
                temp_path.write_bytes(content)
            except OSError as exc:
                raise ScanFailure(f"audited-state temp copy could not be written: {path}.") from exc
            written.append(temp_path)
            mapping[_normalize(str(temp_path))] = path
        if written:
            scanned = _scan_file_set(
                [_normalize(str(path)) for path in written], repo_root, _run_audited_driver
            )
        else:
            scanned = {"results": {}}
    finally:
        for temp_path in written:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ScanFailure(
                    f"audited-state temp copy could not be removed: {temp_path.name}."
                ) from exc
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
    equivalence evidence never carries secret plaintext.
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

    The immutable evidence behind every audited identity: baselined lines
    must still say the same thing, and a shifted occurrence must still exist
    byte-identically. Read straight from git history at the anchor commit,
    so nothing in the working tree can influence it. A path absent at the
    audited commit, or not UTF-8 there, contributes no evidence -- every
    live occurrence in it stays an addition and fails closed unless a
    structural classifier proves it.
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
        evidence[path] = _line_content_digests(_universal_newline_lines(text))
    return evidence


def _live_line_content_digests(
    repo_root: Path,
    paths: list[str],
) -> dict[str, dict[int, str]]:
    """Per-line content fingerprints of the given files in the working tree.

    Read through the same strict UTF-8 reader and the same scanner-compatible
    line split the structural classifiers use, so the equivalence proof and
    the classification see byte-identical line text. An unreadable candidate
    raises ``ScanFailure`` and fails closed.
    """
    return {
        path: _line_content_digests(_read_text_for_classification(repo_root / path))
        for path in sorted(paths)
    }


def _normalized_line_number(finding: dict[str, Any]) -> int | None:
    """The 1-based line number of a finding; ``None`` when absent or malformed.

    ``None`` is deliberately distinct from every real line number: a finding
    without a usable line can never match the other side, so it fails closed
    through the classifier instead of being silently reconciled.
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
    sides always start from the same per-line identity; the same digest on a
    different line is a different occurrence. This four-part identity is
    never a reconciliation decision on its own -- ``_content_bearing_identities``
    extends it with the immutable line-content fingerprint that both the
    baseline subtraction and the audited-state matching require.
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

    The full occurrence identity is ``(path, detector type, fingerprint,
    line number, line-content digest)``. ``line_digests`` supplies the fifth
    part for exactly one side: git history at the audited anchor commit for
    the audited side, the working tree for the live side -- different,
    independent sources, so an identity can only ever be shared when the
    line text is byte-identical. An identity without a usable line number or
    content fingerprint produces nothing and can never match: it stays an
    addition and fails closed unless a structural classifier proves it.
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

    A live occurrence leaves the addition set only when the protected
    baseline records that exact ``(path, type, fingerprint, line)`` identity
    **and** the line still carries byte-identical content (working tree vs.
    git history at the anchor commit). A bare four-part match is never
    sufficient: an audited fingerprint whose line was rewritten from a
    classified to an unclassified context keeps the same four parts, so a
    line-number-only subtraction would silently clear it. Without content
    evidence it has no audited counterpart, stays an addition, and must be
    proven harmless on that exact line or fail closed.
    """
    matched_with_content = _content_bearing_identities(
        observed, live_line_digests
    ) & _content_bearing_identities(audited, audited_line_digests)
    matched: set[tuple[str, str, str, int | None]] = {
        (path, finding_type, hashed, line_number)
        for path, finding_type, hashed, line_number, _ in matched_with_content
    }
    return matched, observed - matched


def _universal_newline_lines(text: str) -> list[str]:
    """Split decoded text exactly like text-mode line iteration.

    The pinned scanner reads candidates through a text-mode ``open()`` and
    ``readlines()``: CRLF and lone CR translate to LF, and
    ``_UNICODE_LINE_SEPARATOR`` (U+2028) / ``_UNICODE_PARAGRAPH_SEPARATOR``
    (U+2029) are **not** line boundaries: this normalization translates only
    CRLF and CR, so both separators pass through untouched and can never
    start a new line. ``str.splitlines()`` would split on both, so a file
    containing either character would shift every subsequent line number
    between the scanner's findings and this module's line-content evidence
    and classifier reads -- a substitution seam. This function reproduces
    the scanner's numbering: the translated text is split on LF, and exactly
    one empty final element is dropped when the text ends with a line break
    (iteration never yields a trailing empty line). The live sentinel probe
    (``_probe_text``/``_expected_probe_line_number``) pins this contract
    against the real pinned driver on every scan run.
    """
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if lines[-1] == "" and text.endswith(("\r", "\n")):
        lines.pop()
    return lines


def _read_text_for_classification(path: Path) -> list[str]:
    """Read a candidate as UTF-8 for structural classification.

    Split with the scanner's own text-mode line numbering (see
    ``_universal_newline_lines``), so the classifier reads exactly the line
    the scanner numbered. The scanner already proved the file decodes; a read
    error here still fails closed via the caller, because an unreadable file
    can never be classified.
    """
    try:
        return _universal_newline_lines(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ScanFailure(f"candidate is unreadable for classification: {path.name}.") from exc


# --- Structural classifiers -------------------------------------------------
#
# A classifier clears a live finding ONLY by re-deriving it from the working
# tree: it extracts the token it considers non-secret by construction and must
# reproduce the scanner's own SHA-1 fingerprint, so a genuine secret can
# never inherit clearance. Each rule is narrowed to *exact*, non-generic
# field names and *exact* file paths: dedicated, provably static
# content-registry documents only -- never executable source files, never
# ``*.py``. Extending either set is an R3 security decision, never a gate
# fix. Clearance is decided per reported line.

# The exact digest field names used by the content registries: only
# precise, non-generic names qualify (generic ``sha256``/``checksum`` and
# lookalikes such as ``api_sha256`` stay unclassified).
_CONTENT_DIGEST_KEYS = frozenset(
    {
        "reference_sha256",
        "fragment_sha256",
        "claim_snapshot_sha256",
        "source_sha256",
    }
)
# The exact content-registry files whose 64-hex values are content digests
# by construction: dedicated, provably static registry documents (JSON data,
# no executable content). An executable source file must never be added, and
# the same key in any other file stays unclassified.
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
# The exact Drive-index field names; any other key stays unclassified.
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
# Corroboration that a file really is a Drive/Docs index: an actual Drive
# URL or an explicit ``drive`` provenance marker; without one, a Drive-shaped
# token stays unclassified.
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
    Classification is per line, never per digest: every *new* line occurrence
    goes through the structural classifier on that exact line, and a line
    that cannot be proven non-secret there keeps its own identity
    unclassified even when the same digest is proven harmless elsewhere. An
    absent, malformed or out-of-range line number can never be classified.
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

    Rows carry the normalized path, detector type, SHA-1 fingerprints and
    line numbers only -- never plaintext -- and are marked unclassified.
    Deliberately bounded (``_AUDIT_MAX_ROWS`` rows,
    ``_AUDIT_MAX_HASHES_PER_ROW`` per row); truncation is never silent (the
    omitted counts are stated explicitly), so the artifact stays short
    without understating what failed closed. Write-only evidence: nothing in
    this module reads it back, so it can never act as an allowlist, baseline
    or suppression input.
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

    Returns ``(status, message)``. Status 0: every live candidate is in the
    protected baseline, reconciled with the audited repository state, or
    proven non-secret by a structural classifier. Status 1: at least one
    unclassified candidate (a bounded audit report is written to the
    git-ignored runtime directory). Status 2: missing or malformed
    baseline, any scanner/git failure or canonical-set condition. The live
    scan always runs; there is no snapshot or environment bypass. Messages
    never contain secret material; comparison is occurrence-aware, strictly
    per line and always content-bearing.
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
            audited_state = _audited_occurrence_identities(
                root, audited_anchor, addition_paths, current.get("results", {})
            )
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

    Returns ``{audited line: live line}``; every live occurrence left
    unseated is a new occurrence and stays an addition. Seating requires
    byte-identical line content on both sides -- there is no bare
    line-number path at all: a shared line number without shared content is
    exactly the substitution this module must reject. Content equality is an
    equivalence relation, so the proof graph is a disjoint union of complete
    bipartite blocks (one per content fingerprint) and maximum matching
    needs no search: inside a block ``min(live, audited)`` occurrences seat,
    unchanged-in-place occurrences first, so a stronger claim is never
    displaced by a weaker one and a wholesale drift still seats perfectly. A
    line with no content fingerprint on either side never seats. All
    iteration is over sorted inputs, so the result is deterministic.
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
    one-to-one against the audited occurrences of that same value (see
    ``_match_occurrences``); only an *individually* matched occurrence counts
    as pre-existing. Seating uses immutable content evidence only -- same
    line and byte-identical content, or byte-identical content proving the
    occurrence shifted with an unrelated edit -- with the strongest evidence
    committed first, so an unchanged occurrence can never be displaced and a
    value audited once that now appears twice can never have both copies
    cleared. There is deliberately no weaker rule, and equivalence is never
    inferred from counts or positions: an audited digest moved to an
    unclassified line has no edge and fails closed even though the count is
    unchanged. Because the structural classifiers decide on exactly that
    line text, byte-identical content cannot smuggle a classified context
    into an unclassified one. Identities without a usable line number, in
    files with no audited content evidence, or on out-of-range lines never
    reconcile and stay remaining (fail closed). Ordering is fully sorted, so
    the split is deterministic.
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
