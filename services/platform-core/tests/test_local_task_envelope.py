"""Targeted tests for the local task envelope validator (synthetic cases only)."""

from __future__ import annotations

import json

import pytest

from scripts import validate_local_task_envelope as validator

VALID = [
    {"task_id": "SYN-0001", "input_kind": "SYNTHETIC", "sequence": 1},
    {"task_id": "SYN-9999", "input_kind": "SYNTHETIC", "sequence": 2**40},
]


@pytest.mark.parametrize("envelope", VALID)
def test_accepts_valid_synthetic_envelope(envelope):
    assert validator.validate_envelope(envelope) == []


REJECTED = [
    ("missing field", {"task_id": "SYN-0001", "sequence": 1}, "missing required field: input_kind"),
    ("unknown field", {**VALID[0], "extra": 5}, "envelope contains unknown fields"),
    ("short task id", {**VALID[0], "task_id": "SYN-123"}, "task_id must start"),
    ("long task id", {**VALID[0], "task_id": "SYN-12345"}, "task_id must start"),
    ("non-digit task id", {**VALID[0], "task_id": "SYN-12a4"}, "task_id must start"),
    ("lowercase task id", {**VALID[0], "task_id": "syn-0001"}, "task_id must start"),
    ("non-string task id", {**VALID[0], "task_id": 1234}, "task_id must start"),
    ("wrong input kind", {**VALID[0], "input_kind": "REAL"}, "input_kind must equal"),
    ("empty input kind", {**VALID[0], "input_kind": ""}, "input_kind must equal"),
    ("zero sequence", {**VALID[0], "sequence": 0}, "sequence must be"),
    ("negative sequence", {**VALID[0], "sequence": -1}, "sequence must be"),
    ("boolean sequence", {**VALID[0], "sequence": True}, "sequence must be"),
    ("float sequence", {**VALID[0], "sequence": 1.0}, "sequence must be"),
    ("string sequence", {**VALID[0], "sequence": "1"}, "sequence must be"),
]


@pytest.mark.parametrize(("label", "envelope", "expected"), REJECTED)
def test_rejects_invalid_synthetic_envelope(label, envelope, expected):
    errors = validator.validate_envelope(envelope)
    assert any(expected in error for error in errors)


@pytest.mark.parametrize("envelope", [[], "text", 42, None, True])
def test_rejects_non_object_envelope(envelope):
    assert validator.validate_envelope(envelope) == ["envelope must be a JSON object"]


def test_error_list_is_stable_for_combined_failures():
    envelope = {"input_kind": "REAL", "sequence": True, "extra": 1}
    assert validator.validate_envelope(envelope) == [
        "missing required field: task_id",
        "envelope contains unknown fields",
        "task_id must start with the SYN- prefix followed by exactly four digits",
        "input_kind must equal the synthetic marker",
        "sequence must be a positive integer and not a boolean",
    ]


@pytest.mark.parametrize(
    ("envelope", "forbidden"),
    [
        ({**VALID[0], "task_id": "ZZZ-9999"}, "ZZZ-9999"),
        ({**VALID[0], "input_kind": "REAL"}, "REAL"),
        ({**VALID[0], "sequence": -7}, "-7"),
        ({**VALID[0], "extra": "secret-x9"}, "secret-x9"),
    ],
)
def test_errors_never_echo_received_values(envelope, forbidden):
    assert all(forbidden not in error for error in validator.validate_envelope(envelope))


def run_cli(tmp_path, payload):
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return validator.main([str(path)])


def test_cli_accepts_valid_file(tmp_path, capsys):
    assert run_cli(tmp_path, VALID[0]) == 0
    assert capsys.readouterr().out.strip() == "task envelope is valid"


def test_cli_rejects_invalid_file_without_echo(tmp_path, capsys):
    assert run_cli(tmp_path, {**VALID[0], "sequence": -7}) == 1
    captured = capsys.readouterr()
    assert "sequence must be a positive integer" in captured.err
    assert "-7" not in captured.err


def test_cli_rejects_non_json_file(tmp_path, capsys):
    path = tmp_path / "envelope.json"
    path.write_text("not json", encoding="utf-8")
    assert validator.main([str(path)]) == 1
    assert "does not contain valid JSON" in capsys.readouterr().err


def test_cli_requires_exactly_one_argument(capsys):
    assert validator.main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_unknown_field_name_is_never_echoed(tmp_path, capsys):
    envelope = {**VALID[0], "opaque_field_x9": "opaque-value-x9"}
    errors = validator.validate_envelope(envelope)
    assert errors == ["envelope contains unknown fields"]
    assert all("opaque_field_x9" not in error for error in errors)
    assert run_cli(tmp_path, envelope) == 1
    assert "opaque_field_x9" not in capsys.readouterr().err


def test_multiple_unknown_fields_yield_one_generic_error():
    first = {**VALID[0], "opaque_field_x9": 1, "extra": 2, "zzz_unknown": 3}
    second = {**VALID[0], "zzz_unknown": 3, "extra": 2, "opaque_field_x9": 1}
    assert validator.validate_envelope(first) == ["envelope contains unknown fields"]
    assert validator.validate_envelope(second) == validator.validate_envelope(first)
