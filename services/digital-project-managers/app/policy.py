from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    status: str
    escalation_level: str
    requires_approval: bool
    reason: str


R7_ACTIONS = frozenset(
    {
        "approve_extra_work",
        "completion_certificate",
        "contract_change",
        "contract_signature",
        "data_breach",
        "final_performance_certificate",
        "liability_recognition",
        "modify_contract",
        "performance_certificate",
        "performance_certification",
        "recognize_liability",
        "safety_incident",
        "sign_contract",
        "structural_incident",
    }
)
R6_ACTIONS = frozenset(
    {
        "change_deadline",
        "commit_company",
        "commitment",
        "external_commitment",
        "grant_discount",
        "place_order",
        "purchase_order",
    }
)
R0_R3_ACTIONS = frozenset(
    {
        "classify_ticket",
        "create_internal_task",
        "internal_administration",
        "prepare_report",
        "prepare_technical_explanation",
        "publish_tender",
        "rank_quotes",
        "read_project",
        "request_document",
        "request_quote",
        "send_reminder",
        "send_standard_email",
        "status_report",
        "sync_partner_control",
        "update_status",
    }
)


def normalize_action_type(action_type: str) -> str:
    return "_".join(action_type.strip().lower().replace("-", "_").split())


def classify_action_risk(action_type: str, declared_risk_level: int) -> int:
    """Return the server-enforced risk level without trusting caller classification."""
    if not 0 <= declared_risk_level <= 7:
        raise ValueError("risk_level must be between R0 and R7")
    normalized = normalize_action_type(action_type)
    if normalized in R7_ACTIONS:
        return 7
    if normalized in R6_ACTIONS:
        return max(6, declared_risk_level)
    if normalized in R0_R3_ACTIONS:
        return declared_risk_level
    return max(5, declared_risk_level)


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
