#!/usr/bin/env python3
"""Verify or refresh the integration manifest from canonical Git bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

MANIFEST_PATH = Path("services/operational-guidance/INTEGRATION-FILE-MANIFEST.json")
OWNED_PATHS = (
    ".github/workflows/operational-guidance-ci.yml",
    "docs/integrations/operational-guidance-v0.8.1.md",
    "services/operational-guidance",
)


def run_git(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def find_repo_root() -> Path:
    output = run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(output.decode("utf-8").strip()).resolve()


def tracked_owned_paths(repo_root: Path) -> list[str]:
    output = run_git(repo_root, "ls-files", "-z", "--", *OWNED_PATHS)
    paths = output.decode("utf-8").split("\0")
    return sorted(path for path in paths if path and path != MANIFEST_PATH.as_posix())


def source_bytes(repo_root: Path, path: str, source: str, revision: str) -> bytes:
    if source == "worktree":
        return (repo_root / path).read_bytes()
    object_name = f"{revision}:{path}" if source == "head" else f":{path}"
    return run_git(repo_root, "show", "--no-textconv", object_name)


def file_record(repo_root: Path, path: str, source: str, revision: str) -> dict[str, object]:
    payload = source_bytes(repo_root, path, source, revision)
    return {
        "path": path,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def refresh_manifest(
    repo_root: Path,
    manifest: dict[str, object],
    source: str,
    revision: str,
) -> int:
    paths = tracked_owned_paths(repo_root)
    records = [file_record(repo_root, path, source, revision) for path in paths]
    refreshed = {
        "target_repository": manifest["target_repository"],
        "branch": manifest["branch"],
        "base": manifest["base"],
        "file_count_excluding_manifest": len(records),
        "files": records,
    }
    manifest_file = repo_root / MANIFEST_PATH
    manifest_file.write_text(
        json.dumps(refreshed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Refreshed {MANIFEST_PATH.as_posix()} from {source}: {len(records)} files.")
    return 0


def verify_manifest(
    repo_root: Path,
    manifest: dict[str, object],
    source: str,
    revision: str,
) -> int:
    errors: list[str] = []
    entries = manifest.get("files")
    if not isinstance(entries, list):
        print("Manifest field 'files' must be a list.")
        return 1

    expected_paths = tracked_owned_paths(repo_root)
    manifest_paths = [
        entry["path"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    declared_count = manifest.get("file_count_excluding_manifest")

    if declared_count != len(entries):
        errors.append(
            f"declared file count is {declared_count!r}, but manifest contains {len(entries)} entries"
        )
    if len(manifest_paths) != len(entries):
        errors.append("manifest contains entries without a valid string path")
    if manifest_paths != sorted(manifest_paths):
        errors.append("manifest paths are not sorted")
    if len(manifest_paths) != len(set(manifest_paths)):
        errors.append("manifest contains duplicate paths")
    if manifest_paths != expected_paths:
        missing = sorted(set(expected_paths) - set(manifest_paths))
        unexpected = sorted(set(manifest_paths) - set(expected_paths))
        if missing:
            errors.append(f"manifest is missing tracked owned paths: {missing}")
        if unexpected:
            errors.append(f"manifest contains unexpected paths: {unexpected}")

    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append(f"invalid manifest entry: {entry!r}")
            continue
        path = entry["path"]
        try:
            actual = file_record(repo_root, path, source, revision)
        except (OSError, RuntimeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        if entry.get("size") != actual["size"]:
            errors.append(
                f"{path}: size mismatch: manifest={entry.get('size')!r}, "
                f"actual={actual['size']}"
            )
        if entry.get("sha256") != actual["sha256"]:
            errors.append(
                f"{path}: SHA-256 mismatch: manifest={entry.get('sha256')!r}, "
                f"actual={actual['sha256']}"
            )

    if errors:
        print(f"Integration manifest verification failed with {len(errors)} error(s):")
        for error in errors:
            print(f" - {error}")
        return 1

    print(
        f"Integration manifest verified from {source}: "
        f"{len(entries)}/{len(entries)} files match."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        choices=("head", "index", "worktree"),
        default="head",
        help="Byte source to verify or use when refreshing the manifest.",
    )
    parser.add_argument("--revision", default="HEAD", help="Git revision for --source head.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Regenerate the manifest. Prefer --source index after staging intended files.",
    )
    args = parser.parse_args()

    try:
        repo_root = find_repo_root()
        manifest = json.loads((repo_root / MANIFEST_PATH).read_text(encoding="utf-8"))
        if args.refresh:
            return refresh_manifest(repo_root, manifest, args.source, args.revision)
        return verify_manifest(repo_root, manifest, args.source, args.revision)
    except (KeyError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Integration manifest operation failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
