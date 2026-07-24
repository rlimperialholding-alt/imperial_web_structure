from __future__ import annotations

import pytest

from app.policy import assert_external_action_allowed, evaluate_risk


@pytest.mark.parametrize("risk_level", [0, 1, 2, 3])
def test_r0_to_r3_are_allowed(risk_level: int) -> None:
    decision = evaluate_risk(risk_level)
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.status == "CREATED"


@pytest.mark.parametrize(
    ("risk_level", "escalation_level"),
    [(6, "E3"), (7, "E4")],
)
def test_r6_and_r7_are_blocked(risk_level: int, escalation_level: str) -> None:
    decision = evaluate_risk(risk_level)
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.status == "BLOCKED"
    assert decision.escalation_level == escalation_level
    with pytest.raises(PermissionError):
        assert_external_action_allowed(risk_level, human_approved=True)


def test_invalid_risk_is_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_risk(8)
