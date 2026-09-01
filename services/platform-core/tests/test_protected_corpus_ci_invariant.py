"""Focused protected-corpus CI invariant regression.

Mirrors the protected-corpus phase of ``.imperial-adas/ci/Invoke-ADASCI.ps1``:
each manifest entry must exist and its raw on-disk bytes must hash to the
recorded SHA-256 exactly. The invariant is deliberately byte-exact, so the
checked-out bytes have to be canonical on every platform; a Windows checkout
that materialises CRLF produces a different digest than an ubuntu-latest
checkout and breaks Remote CI. These tests therefore prove three things:

1. the real repository passes when content and canonical digest agree;
2. the canonical form is LF and is pinned in ``.gitattributes``, so the
   platform-dependent digest drift cannot silently return;
3. the invariant still fails closed on content tampering, on line-ending
   tampering, and on a removed protected file;
4. every recorded digest is proven equal to the canonical committed Git-blob
   bytes (LF), so the manifest can never be silently blessed from an
   ambiguous CRLF working tree;
5. the coverage check is scoped to tracked acceptance artifacts, so an
   unrelated untracked temporary file cannot cause a false failure.

Case 3 also proves the invariant was not softened into a line-ending
insensitive comparison. All tamper fixtures are synthetic copies under the
pytest temporary directory; the real protected corpus is never mutated.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLATFORM_CORE = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_CORE.parents[1]
ADAS_ROOT = REPO_ROOT / ".imperial-adas"
MANIFEST_PATH = ADAS_ROOT / "protected-corpus-manifest.json"
ACCEPTANCE_DIR = ADAS_ROOT / "acceptance"
GITATTRIBUTES_PATH = REPO_ROOT / ".gitattributes"
CI_SCRIPT_PATH = ADAS_ROOT / "ci" / "Invoke-ADASCI.ps1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _entries() -> list[dict]:
    entries = _manifest().get("files")
    assert isinstance(entries, list) and entries, "protected corpus manifest is empty"
    return entries


def _verify(entries: list[dict], root: Path) -> list[str]:
    """Byte-exact mirror of the Invoke-ADASCI.ps1 protected-corpus phase."""
    findings: list[str] = []
    for entry in entries:
        relative = str(entry["path"])
        target = root / relative
        if not target.is_file():
            findings.append(f"Protected corpus file missing: {relative}")
            continue
        if _sha256(target) != str(entry["sha256"]).lower():
            findings.append(f"Protected corpus hash mismatch: {relative}")
    return findings


def _synthetic_corpus(tmp_path: Path) -> Path:
    """Copy the protected corpus byte-for-byte into an isolated temp root."""
    root = tmp_path / "synthetic-repo"
    for entry in _entries():
        destination = root / str(entry["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / str(entry["path"]), destination)
    return root


def _lf_pinned_patterns() -> list[str]:
    patterns: list[str] = []
    for raw in GITATTRIBUTES_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if "eol=lf" in fields[1:]:
            patterns.append(fields[0])
    return patterns


def _pattern_covers(pattern: str, relative: str) -> bool:
    # gitattributes uses gitignore globbing. Collapsing '**' to '*' can only
    # over-approximate coverage, so this stays a structural guard against the
    # pin being dropped; the authoritative byte-level guarantee is asserted by
    # test_protected_corpus_bytes_are_lf_canonical.
    return fnmatch.fnmatchcase(relative, pattern.replace("**", "*"))


def test_protected_corpus_matches_canonical_digest() -> None:
    assert _verify(_entries(), REPO_ROOT) == []


def _tracked_acceptance_files() -> set[str]:
    """Intended acceptance artifacts: tracked files, not transient temp files.

    The coverage check is scoped to Git-tracked files so an unrelated
    untracked temporary file in the acceptance directory cannot cause a false
    failure, while any tracked artifact omitted from the manifest still fails
    closed. Environments without Git metadata (e.g. a packed container image)
    fall back to the physically present files, which there are exactly the
    intended acceptance content.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--", ".imperial-adas/acceptance"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {
            f".imperial-adas/acceptance/{path.name}"
            for path in sorted(ACCEPTANCE_DIR.iterdir())
            if path.is_file()
        }
    return {line for line in listed.splitlines() if line}


def test_manifest_protects_every_acceptance_file() -> None:
    declared = {str(entry["path"]) for entry in _entries()}
    present = _tracked_acceptance_files()

    assert present - declared == set(), "acceptance file excluded from protection"


def test_manifest_digests_equal_committed_git_blob_lf_bytes() -> None:
    """The recorded digests are the canonical committed blob bytes, not a
    working-tree rendering.

    Reviewers asked for proof that the manifest was never blessed from an
    ambiguous CRLF working tree: each entry is resolved against HEAD, read
    as raw blob bytes, and hashed exactly once. Git blobs are stored
    LF-normalized, so this is also the "after LF normalization" evidence;
    the CR check makes that explicit. The working-tree byte check above
    remains the CI-mirror guard, this one proves provenance.
    """
    for entry in _entries():
        relative = str(entry["path"])
        try:
            oid = subprocess.run(
                ["git", "rev-parse", f"HEAD:{relative}"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            blob = subprocess.run(
                ["git", "cat-file", "blob", oid],
                cwd=REPO_ROOT,
                capture_output=True,
                check=True,
            ).stdout
        except FileNotFoundError:
            pytest.skip("git executable unavailable; blob provenance check needs the repository")
        except subprocess.CalledProcessError as exc:
            pytest.fail(f"git failed while resolving {relative}: {exc}")

        digest = hashlib.sha256(blob).hexdigest()
        assert digest == str(entry["sha256"]).lower(), (
            f"manifest digest for {relative} is not the committed blob digest"
        )
        assert b"\r" not in blob, f"committed blob for {relative} contains CR bytes"


def test_protected_corpus_bytes_are_lf_canonical() -> None:
    for entry in _entries():
        relative = str(entry["path"])
        payload = (REPO_ROOT / relative).read_bytes()

        assert b"\r" not in payload, f"non-canonical line ending in {relative}"


def test_gitattributes_pins_protected_corpus_to_lf() -> None:
    patterns = _lf_pinned_patterns()
    for entry in _entries():
        relative = str(entry["path"])

        assert any(_pattern_covers(pattern, relative) for pattern in patterns), (
            f"{relative} has no eol=lf pin in .gitattributes"
        )


def test_ci_attestation_results_never_expand_the_list_directly() -> None:
    # Expanding the generic List[object] with @($results) throws "Argument types
    # do not match" in PowerShell, which aborts the attestation write on both the
    # BLOCKED and the PASS path and leaves the gate with no attestation at all.
    # The failure is silent until a full pipeline run, so guard the idiom here.
    attestation_lines = [
        line.strip()
        for line in CI_SCRIPT_PATH.read_text(encoding="utf-8").splitlines()
        if "$attestation = [ordered]@{" in line
    ]

    assert attestation_lines, "no attestation assignment found in the CI script"
    for line in attestation_lines:
        assert "results=@($results)" not in line, (
            "attestation results must be enumerated through the pipeline helper"
        )
        assert "results=(Get-ADASCIAttestationResults" in line, (
            "attestation results must use Get-ADASCIAttestationResults"
        )


def test_synthetic_corpus_copy_passes_before_tampering(tmp_path: Path) -> None:
    assert _verify(_entries(), _synthetic_corpus(tmp_path)) == []


def test_fail_closed_on_content_tamper(tmp_path: Path) -> None:
    root = _synthetic_corpus(tmp_path)
    entries = _entries()
    target = root / str(entries[0]["path"])
    target.write_bytes(target.read_bytes() + b"\n")

    findings = _verify(entries, root)

    assert findings == [f"Protected corpus hash mismatch: {entries[0]['path']}"]


def test_fail_closed_on_line_ending_tamper(tmp_path: Path) -> None:
    root = _synthetic_corpus(tmp_path)
    entries = _entries()
    target = root / str(entries[0]["path"])
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))

    findings = _verify(entries, root)

    assert findings == [f"Protected corpus hash mismatch: {entries[0]['path']}"]


def test_fail_closed_on_missing_protected_file(tmp_path: Path) -> None:
    root = _synthetic_corpus(tmp_path)
    entries = _entries()
    (root / str(entries[0]["path"])).unlink()

    findings = _verify(entries, root)

    assert findings == [f"Protected corpus file missing: {entries[0]['path']}"]
