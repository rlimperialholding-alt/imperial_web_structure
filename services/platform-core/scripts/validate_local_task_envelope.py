"""Validate a synthetic local ADAS task envelope from a JSON file (read-only)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EXPECTED_FIELDS = ("task_id", "input_kind", "sequence")
SYNTHETIC_MARKER = "SYNTHETIC"
TASK_ID_PATTERN = re.compile(r"^SYN-[0-9]{4}$")


def validate_envelope(envelope: object) -> list[str]:
    """Return a stable list of validation errors; an empty list means valid."""
    errors: list[str] = []
    if not isinstance(envelope, dict):
        errors.append("envelope must be a JSON object")
        return errors

    missing = [name for name in EXPECTED_FIELDS if name not in envelope]
    for name in missing:
        errors.append(f"missing required field: {name}")

    unknown = [name for name in envelope if name not in EXPECTED_FIELDS]
    if unknown:
        errors.append("envelope contains unknown fields")

    task_id = envelope.get("task_id")
    if not isinstance(task_id, str) or TASK_ID_PATTERN.fullmatch(task_id) is None:
        errors.append("task_id must start with the SYN- prefix followed by exactly four digits")

    if envelope.get("input_kind") != SYNTHETIC_MARKER:
        errors.append("input_kind must equal the synthetic marker")

    sequence = envelope.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        errors.append("sequence must be a positive integer and not a boolean")
    return errors


def validate_file(path: Path) -> list[str]:
    """Read one envelope JSON file (read-only) and return its validation errors."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [f"envelope file is not readable: {path.name}"]
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return ["envelope file does not contain valid JSON"]
    return validate_envelope(envelope)


def main(argv: list[str] | None = None) -> int:
    """Run the validator as a CLI; returns 0 when valid, non-zero otherwise."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: validate_local_task_envelope.py <envelope.json>", file=sys.stderr)
        return 2
    errors = validate_file(Path(args[0]))
    if errors:
        for error in errors:
            print(f"invalid task envelope: {error}", file=sys.stderr)
        return 1
    print("task envelope is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
