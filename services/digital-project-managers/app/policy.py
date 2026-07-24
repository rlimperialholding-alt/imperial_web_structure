from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    status: str
    escalation_level: str
    requires_approval: bool
    reason: str


def evaluate_risk(risk_level: int) -> PolicyDecision:
    if not 0 <= risk_level <= 7:
        raise ValueError("risk_level must be between R0 and R7")
    if risk_level <= 3:
        return PolicyDecision(
            allowed=True,
            status="CREATED",
            escalation_level="E0",
            requires_approval=False,
            reason="R0-R3 is allowed inside the approved, reversible operating scope.",
        )
    if risk_level == 4:
        return PolicyDecision(
            allowed=False,
            status="WAITING_APPROVAL",
            escalation_level="E2",
            requires_approval=True,
            reason="R4 requires an explicit project rule before autonomous execution.",
        )
    if risk_level == 5:
        return PolicyDecision(
            allowed=False,
            status="WAITING_APPROVAL",
            escalation_level="E2",
            requires_approval=True,
            reason="R5 financial or contractual preparation requires human approval.",
        )
    if risk_level == 6:
        return PolicyDecision(
            allowed=False,
            status="BLOCKED",
            escalation_level="E3",
            requires_approval=True,
            reason="R6 external commitment is blocked until a designated human approves.",
        )
    return PolicyDecision(
        allowed=False,
        status="BLOCKED",
        escalation_level="E4",
        requires_approval=True,
        reason="R7 critical action is blocked and immediately escalated to a human.",
    )


def assert_external_action_allowed(risk_level: int, human_approved: bool) -> None:
    decision = evaluate_risk(risk_level)
    if risk_level >= 6:
        raise PermissionError(
            "R6-R7 external actions cannot be executed automatically, even when queued."
        )
    if decision.requires_approval and not human_approved:
        raise PermissionError(decision.reason)
