from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    PartnerCapacityDeclaration,
    PartnerCertificate,
    PartnerDecision,
    PartnerFieldAccess,
    PartnerIncident,
    PartnerProfile,
    PartnerProjectEvaluation,
    ProjectRegistry,
    TenderPackage,
)

INTERNAL_ROLES = frozenset(
    {"owner", "managing-director", "platform-admin", "project-manager", "finance", "technical-prep"}
)
QUALIFICATION_ROLES = frozenset(
    {"owner", "managing-director", "platform-admin", "finance", "legal", "technical-prep"}
)
REVIEW_ROLES = frozenset(
    {"owner", "managing-director", "platform-admin", "project-manager", "technical-prep"}
)
LEADERSHIP_ROLES = frozenset({"owner", "managing-director", "platform-admin"})
DECISION_TYPES = frozenset(
    {"approved", "conditional", "suspended", "excluded", "reinstatement_review"}
)
INCIDENT_TYPES = frozenset(
    {"quality", "delay", "documentation", "hse", "finance", "ethics", "legal", "customer_relation"}
)
SEVERITIES = frozenset({"minor", "major", "critical"})
CERTIFICATE_TYPES = frozenset({"liability_insurance", "tax_clearance", "quality", "hse", "other"})
SCORECARD_WEIGHTING_VERSION = "partner-score-v1"
SCORECARD_WEIGHTS = {
    "quality": Decimal("25"),
    "deadline": Decimal("20"),
    "documentation": Decimal("10"),
    "hse": Decimal("15"),
    "cooperation": Decimal("10"),
    "commercial": Decimal("15"),
    "warranty": Decimal("5"),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _email(user: object) -> str:
    return str(getattr(user, "email", "")).strip().lower()


def _role(user: object) -> str:
    return str(getattr(user, "role", ""))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _object(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _partner(db: Session, partner_id: str) -> PartnerProfile:
    row = db.scalar(select(PartnerProfile).where(PartnerProfile.partner_id == partner_id))
    if row is None:
        raise KeyError(partner_id)
    return row


def _score(value: Decimal | int | float | str) -> Decimal:
    result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if result < 0 or result > 100:
        raise ValueError("A pontszám 0 és 100 közötti lehet.")
    return result


def partner_workspace(db: Session) -> dict[str, Any]:
    profiles = list(db.scalars(select(PartnerProfile).order_by(PartnerProfile.company_name)))
    today = date.today()
    certificates = list(db.scalars(select(PartnerCertificate)))
    incidents = list(db.scalars(select(PartnerIncident).order_by(desc(PartnerIncident.created_at))))
    decisions = list(db.scalars(select(PartnerDecision).order_by(desc(PartnerDecision.created_at))))
    capacities = list(
        db.scalars(
            select(PartnerCapacityDeclaration).order_by(desc(PartnerCapacityDeclaration.created_at))
        )
    )
    return {
        "profiles": profiles,
        "certificates": certificates,
        "incidents": incidents,
        "decisions": decisions,
        "capacities": capacities,
        "metrics": {
            "partners": len(profiles),
            "eligible": sum(row.status in {"approved", "conditional"} for row in profiles),
            "blocked": sum(row.status in {"suspended", "excluded"} for row in profiles),
            "certificates_expiring_30d": sum(
                row.verification_status == "verified"
                and row.valid_until is not None
                and today <= row.valid_until <= today + timedelta(days=30)
                for row in certificates
            ),
            "open_incidents": sum(row.status not in {"closed"} for row in incidents),
            "capacity_pending_review": sum(row.status == "submitted" for row in capacities),
        },
    }


def create_partner(
    db: Session,
    user: object,
    *,
    company_name: str,
    primary_email: str,
    tax_number: str = "",
    trade_categories: list[str] | None = None,
    territories: list[str] | None = None,
    partner_id: str | None = None,
) -> PartnerProfile:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs partnerfelviteli jogosultság.")
    company_name = company_name.strip()
    primary_email = primary_email.strip().lower()
    tax_number = re.sub(r"\s+", "", tax_number).upper()
    if len(company_name) < 2 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", primary_email):
        raise ValueError("A partner neve és érvényes e-mail-címe kötelező.")
    existing = db.scalar(
        select(PartnerProfile).where(PartnerProfile.primary_email == primary_email)
    )
    if existing:
        return existing
    if tax_number and db.scalar(
        select(PartnerProfile).where(PartnerProfile.tax_number == tax_number)
    ):
        raise ValueError("Ez az adószám már másik PartnerID-hez tartozik.")
    row = PartnerProfile(
        partner_id=(partner_id or _id("PARTNER")).strip().upper(),
        company_name=company_name,
        tax_number=tax_number or None,
        primary_email=primary_email,
        trade_categories_json=_json(
            sorted({item.strip() for item in trade_categories or [] if item.strip()})
        ),
        territories_json=_json(
            sorted({item.strip() for item in territories or [] if item.strip()})
        ),
        status="pending",
        created_by=_email(user),
    )
    db.add(row)
    db.flush()
    audit(
        db,
        actor=_email(user),
        action="partner.profile.created",
        entity_type="partner",
        entity_id=row.partner_id,
        after={"company_name": row.company_name, "status": row.status},
    )
    db.commit()
    db.refresh(row)
    return row


def set_external_score(
    db: Session, partner_id: str, user: object, *, score: Decimal | int | str, evidence_ref: str
) -> PartnerProfile:
    if _role(user) not in QUALIFICATION_ROLES:
        raise PermissionError("Nincs külső PartnerCheck-pontozási jogosultság.")
    if len(evidence_ref.strip()) < 8:
        raise ValueError("A külső pontszámhoz ellenőrizhető forráshivatkozás kötelező.")
    row = _partner(db, partner_id)
    row.external_score = _score(score)
    row.external_evidence_ref = evidence_ref.strip()
    _recalculate_score(db, row)
    audit(
        db,
        actor=_email(user),
        action="partner.external_score.reviewed",
        entity_type="partner",
        entity_id=partner_id,
        after={
            "external_score": str(row.external_score),
            "combined_score": str(row.combined_score) if row.combined_score is not None else None,
            "evidence_ref": row.external_evidence_ref,
        },
    )
    db.commit()
    return row


def approve_partner(db: Session, partner_id: str, user: object, *, note: str) -> PartnerProfile:
    if _role(user) not in QUALIFICATION_ROLES:
        raise PermissionError("Nincs partner-minősítési jogosultság.")
    row = _partner(db, partner_id)
    if row.external_score is None or not row.external_evidence_ref:
        raise ValueError("Jóváhagyás előtt külső PartnerCheck-pontszám és bizonyíték szükséges.")
    if len(note.strip()) < 10:
        raise ValueError("A minősítési döntés indokolása kötelező.")
    row.status = "approved"
    row.approved_by = _email(user)
    row.approved_at = utcnow()
    row.next_review_at = utcnow() + timedelta(days=365)
    audit(
        db,
        actor=_email(user),
        action="partner.qualification.approved",
        entity_type="partner",
        entity_id=partner_id,
        after={"status": row.status, "note": note.strip(), "next_review_at": row.next_review_at},
    )
    db.commit()
    return row


def add_certificate(
    db: Session,
    partner_id: str,
    user: object,
    *,
    certificate_type: str,
    issuer: str,
    document_ref: str,
    document_sha256: str,
    valid_from: date | None,
    valid_until: date | None,
    reference_number: str = "",
) -> PartnerCertificate:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs igazolásfelviteli jogosultság.")
    _partner(db, partner_id)
    certificate_type = certificate_type.strip().lower()
    if certificate_type not in CERTIFICATE_TYPES:
        raise ValueError("Ismeretlen igazolástípus.")
    document_sha256 = document_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", document_sha256):
        raise ValueError("Az igazolás SHA-256 lenyomata kötelező.")
    if not document_ref.strip() or len(issuer.strip()) < 2:
        raise ValueError("A kibocsátó és dokumentumhivatkozás kötelező.")
    if valid_from and valid_until and valid_from > valid_until:
        raise ValueError("A lejárat nem előzheti meg az érvényesség kezdetét.")
    row = PartnerCertificate(
        certificate_id=_id("PCERT"),
        partner_id=partner_id,
        certificate_type=certificate_type,
        issuer=issuer.strip(),
        reference_number=reference_number.strip() or None,
        valid_from=valid_from,
        valid_until=valid_until,
        document_ref=document_ref.strip(),
        document_sha256=document_sha256,
        verification_status="pending",
        created_by=_email(user),
    )
    db.add(row)
    audit(
        db,
        actor=_email(user),
        action="partner.certificate.created",
        entity_type="partner_certificate",
        entity_id=row.certificate_id,
        after={"partner_id": partner_id, "type": certificate_type, "sha256": document_sha256},
    )
    db.commit()
    db.refresh(row)
    return row


def verify_certificate(
    db: Session, certificate_id: str, user: object, *, accepted: bool, note: str = ""
) -> PartnerCertificate:
    if _role(user) not in QUALIFICATION_ROLES:
        raise PermissionError("Nincs igazolás-ellenőrzési jogosultság.")
    row = db.scalar(
        select(PartnerCertificate).where(PartnerCertificate.certificate_id == certificate_id)
    )
    if row is None:
        raise KeyError(certificate_id)
    if not accepted and len(note.strip()) < 5:
        raise ValueError("Elutasításkor indoklás kötelező.")
    row.verification_status = "verified" if accepted else "rejected"
    row.verified_by = _email(user)
    row.verified_at = utcnow()
    row.rejection_reason = None if accepted else note.strip()
    audit(
        db,
        actor=_email(user),
        action="partner.certificate.verified" if accepted else "partner.certificate.rejected",
        entity_type="partner_certificate",
        entity_id=certificate_id,
        after={"status": row.verification_status, "note": note.strip()},
    )
    db.commit()
    return row


def certificate_state(row: PartnerCertificate, *, on_date: date | None = None) -> str:
    on_date = on_date or date.today()
    if row.verification_status != "verified":
        return "incomplete" if row.verification_status == "pending" else "invalid"
    if row.valid_until is None:
        return "valid"
    if row.valid_until < on_date:
        return "expired"
    if row.valid_until <= on_date + timedelta(days=30):
        return "expires_30d"
    return "valid"


def declare_capacity(
    db: Session,
    partner_id: str,
    user: object,
    *,
    trade_category: str,
    territory: str,
    available_from: date,
    available_until: date,
    crew_count: int,
    monthly_capacity: Decimal | str,
    committed_capacity: Decimal | str = "0",
    evidence_ref: str = "",
) -> PartnerCapacityDeclaration:
    _partner(db, partner_id)
    if _role(user) not in INTERNAL_ROLES and _email(user) != _partner(db, partner_id).primary_email:
        raise PermissionError("Nincs kapacitásnyilatkozat-felviteli jogosultság.")
    monthly = Decimal(str(monthly_capacity))
    committed = Decimal(str(committed_capacity))
    if (
        available_from > available_until
        or crew_count < 1
        or monthly <= 0
        or committed < 0
        or committed > monthly
    ):
        raise ValueError("Érvénytelen kapacitásidőszak vagy kapacitásérték.")
    row = PartnerCapacityDeclaration(
        declaration_id=_id("PCAP"),
        partner_id=partner_id,
        trade_category=trade_category.strip(),
        territory=territory.strip(),
        available_from=available_from,
        available_until=available_until,
        crew_count=crew_count,
        monthly_capacity=monthly,
        committed_capacity=committed,
        status="submitted",
        evidence_ref=evidence_ref.strip() or None,
        declared_by=_email(user),
    )
    db.add(row)
    audit(
        db,
        actor=_email(user),
        action="partner.capacity.submitted",
        entity_type="partner_capacity",
        entity_id=row.declaration_id,
        after={
            "partner_id": partner_id,
            "available": str(monthly - committed),
            "period": [available_from, available_until],
        },
    )
    db.commit()
    db.refresh(row)
    return row


def review_capacity(
    db: Session, declaration_id: str, user: object, *, accepted: bool, note: str
) -> PartnerCapacityDeclaration:
    if _role(user) not in REVIEW_ROLES:
        raise PermissionError("Nincs kapacitás-ellenőrzési jogosultság.")
    row = db.scalar(
        select(PartnerCapacityDeclaration).where(
            PartnerCapacityDeclaration.declaration_id == declaration_id
        )
    )
    if row is None:
        raise KeyError(declaration_id)
    if len(note.strip()) < 5:
        raise ValueError("A felülvizsgálati megjegyzés kötelező.")
    row.status = "approved" if accepted else "rejected"
    row.reviewed_by = _email(user)
    row.reviewed_at = utcnow()
    row.review_note = note.strip()
    audit(
        db,
        actor=_email(user),
        action="partner.capacity.reviewed",
        entity_type="partner_capacity",
        entity_id=declaration_id,
        after={"status": row.status, "note": row.review_note},
    )
    db.commit()
    return row


def eligibility_report(
    db: Session,
    partner_id: str,
    *,
    tender: TenderPackage | None = None,
    trade_category: str = "",
    territory: str = "",
    required_capacity: Decimal | str = "0",
    start_date: date | None = None,
    end_date: date | None = None,
    contract_value: Decimal | str = "0",
) -> dict[str, Any]:
    row = _partner(db, partner_id)
    blockers: list[str] = []
    warnings: list[str] = []
    if row.status not in {"approved", "conditional"}:
        blockers.append(f"partner_status:{row.status}")
    if row.next_review_at is not None:
        next_review_at = row.next_review_at
        if next_review_at.tzinfo is None:
            next_review_at = next_review_at.replace(tzinfo=UTC)
        if next_review_at < utcnow():
            blockers.append("qualification_review_overdue")
    conditions: dict[str, Any] = {}
    if row.current_decision_id:
        decision = db.scalar(
            select(PartnerDecision).where(PartnerDecision.decision_id == row.current_decision_id)
        )
        conditions = _object(decision.conditions_json if decision else None, {})
        if decision is not None:
            effective_from = decision.effective_from
            if effective_from.tzinfo is None:
                effective_from = effective_from.replace(tzinfo=UTC)
            if effective_from > utcnow():
                blockers.append("decision_not_effective")
            if decision.effective_until is not None:
                effective_until = decision.effective_until
                if effective_until.tzinfo is None:
                    effective_until = effective_until.replace(tzinfo=UTC)
                if effective_until < utcnow():
                    blockers.append("decision_expired")
        if row.status == "conditional":
            allowed_trades = conditions.get("trade_categories") or []
            allowed_territories = conditions.get("territories") or []
            if trade_category and allowed_trades and trade_category not in allowed_trades:
                blockers.append("conditional_trade_scope")
            if territory and allowed_territories and territory not in allowed_territories:
                blockers.append("conditional_territory_scope")
            maximum = Decimal(str(conditions.get("max_contract_value") or "0"))
            if maximum > 0 and Decimal(str(contract_value)) > maximum:
                blockers.append("conditional_value_limit")
    if tender and tender.certificate_gate_enabled:
        required_types = _object(
            tender.required_certificate_types_json, ["liability_insurance", "tax_clearance"]
        )
        certificates = list(
            db.scalars(
                select(PartnerCertificate).where(PartnerCertificate.partner_id == partner_id)
            )
        )
        by_type: dict[str, list[PartnerCertificate]] = {}
        for certificate in certificates:
            by_type.setdefault(certificate.certificate_type, []).append(certificate)
        for cert_type in required_types:
            states = [certificate_state(certificate) for certificate in by_type.get(cert_type, [])]
            if not any(state in {"valid", "expires_30d"} for state in states):
                blockers.append(f"certificate:{cert_type}")
            elif "expires_30d" in states:
                warnings.append(f"certificate_expires_30d:{cert_type}")
    required = Decimal(str(required_capacity))
    if required > 0 or trade_category or territory:
        start_date = start_date or date.today()
        end_date = end_date or start_date
        declarations = list(
            db.scalars(
                select(PartnerCapacityDeclaration).where(
                    PartnerCapacityDeclaration.partner_id == partner_id,
                    PartnerCapacityDeclaration.status == "approved",
                    PartnerCapacityDeclaration.available_from <= start_date,
                    PartnerCapacityDeclaration.available_until >= end_date,
                )
            )
        )
        matching = [
            item
            for item in declarations
            if (not trade_category or item.trade_category == trade_category)
            and (not territory or item.territory == territory)
        ]
        available = sum(
            (item.monthly_capacity - item.committed_capacity for item in matching), Decimal("0")
        )
        if not matching:
            blockers.append("capacity_declaration_missing")
        elif available < required:
            blockers.append("capacity_insufficient")
    return {
        "partner_id": partner_id,
        "eligible": not blockers,
        "status": row.status,
        "combined_score": str(row.combined_score) if row.combined_score is not None else None,
        "blockers": blockers,
        "warnings": warnings,
        "conditions": conditions,
        "checked_at": utcnow().isoformat(),
    }


def create_project_evaluation(
    db: Session,
    partner_id: str,
    project_id: str,
    user: object,
    *,
    quality: int,
    deadline: int,
    documentation: int,
    hse: int,
    cooperation: int,
    commercial: int,
    warranty: int,
    notes: str,
) -> PartnerProjectEvaluation:
    if _role(user) not in REVIEW_ROLES:
        raise PermissionError("Nincs partnerértékelési jogosultság.")
    row = _partner(db, partner_id)
    if db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)) is None:
        raise KeyError(project_id)
    scores = [quality, deadline, documentation, hse, cooperation, commercial, warranty]
    if any(score < 1 or score > 5 for score in scores) or len(notes.strip()) < 10:
        raise ValueError("Minden szempont 1–5 pont és részletes megjegyzés kötelező.")
    score_values = {
        "quality": quality,
        "deadline": deadline,
        "documentation": documentation,
        "hse": hse,
        "cooperation": cooperation,
        "commercial": commercial,
        "warranty": warranty,
    }
    score_100 = sum(
        (Decimal(score_values[key]) / Decimal("5") * weight
        for key, weight in SCORECARD_WEIGHTS.items()),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    evaluation = PartnerProjectEvaluation(
        evaluation_id=_id("PEVAL"),
        partner_id=partner_id,
        project_id=project_id,
        quality_score=quality,
        deadline_score=deadline,
        documentation_score=documentation,
        hse_score=hse,
        cooperation_score=cooperation,
        commercial_score=commercial,
        warranty_score=warranty,
        weighting_version=SCORECARD_WEIGHTING_VERSION,
        score_100=score_100,
        notes=notes.strip(),
        evaluator_email=_email(user),
        approved_by=_email(user),
        approved_at=utcnow(),
    )
    db.add(evaluation)
    db.flush()
    _recalculate_score(db, row)
    audit(
        db,
        actor=_email(user),
        action="partner.performance.evaluated",
        entity_type="partner_evaluation",
        entity_id=evaluation.evaluation_id,
        after={
            "partner_id": partner_id,
            "project_id": project_id,
            "score_100": str(score_100),
            "weighting_version": SCORECARD_WEIGHTING_VERSION,
            "dimensions": score_values,
            "combined_score": str(row.combined_score) if row.combined_score is not None else None,
        },
    )
    db.commit()
    db.refresh(evaluation)
    return evaluation


def _recalculate_score(db: Session, partner: PartnerProfile) -> None:
    internal = db.scalar(
        select(func.avg(PartnerProjectEvaluation.score_100)).where(
            PartnerProjectEvaluation.partner_id == partner.partner_id,
            PartnerProjectEvaluation.approved_at.is_not(None),
        )
    )
    partner.internal_score = (
        Decimal(str(internal)).quantize(Decimal("0.01")) if internal is not None else None
    )
    if partner.external_score is not None and partner.internal_score is not None:
        partner.combined_score = (
            partner.external_score * Decimal("0.70") + partner.internal_score * Decimal("0.30")
        ).quantize(Decimal("0.01"))
    elif partner.external_score is not None:
        partner.combined_score = partner.external_score
    else:
        partner.combined_score = partner.internal_score


def create_incident(
    db: Session,
    partner_id: str,
    user: object,
    *,
    incident_type: str,
    severity: str,
    facts: str,
    requirement_breached: str,
    immediate_risk: str,
    project_id: str = "",
    contract_id: str = "",
    evidence_refs: list[str] | None = None,
    recurring: bool = False,
    response_due_at: datetime | None = None,
) -> PartnerIncident:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs partnerincidens-rögzítési jogosultság.")
    partner = _partner(db, partner_id)
    incident_type = incident_type.strip().lower()
    severity = severity.strip().lower()
    if incident_type not in INCIDENT_TYPES or severity not in SEVERITIES:
        raise ValueError("Ismeretlen incidens típus vagy súlyosság.")
    if (
        project_id
        and db.scalar(
            select(ProjectRegistry).where(ProjectRegistry.project_id == project_id.strip())
        )
        is None
    ):
        raise ValueError("A megadott ProjectID nem található a kanonikus projektregiszterben.")
    if min(len(facts.strip()), len(requirement_breached.strip()), len(immediate_risk.strip())) < 10:
        raise ValueError(
            "A tényállás, a megszegett követelmény és a közvetlen kockázat részletesen kötelező."
        )
    immediate = (
        severity == "critical" and incident_type in {"hse", "ethics", "legal", "quality"}
    ) or (recurring and severity in {"major", "critical"})
    row = PartnerIncident(
        incident_id=_id("PINC"),
        partner_id=partner_id,
        project_id=project_id.strip() or None,
        contract_id=contract_id.strip() or None,
        incident_type=incident_type,
        severity=severity,
        facts=facts.strip(),
        requirement_breached=requirement_breached.strip(),
        immediate_risk=immediate_risk.strip(),
        evidence_refs_json=_json(evidence_refs or []),
        recurring=recurring,
        immediate_suspension=immediate,
        response_due_at=response_due_at or utcnow() + timedelta(days=5),
        status="open",
        created_by=_email(user),
    )
    db.add(row)
    if immediate:
        partner.status = "suspended"
        partner.next_review_at = utcnow() + timedelta(days=7)
        _disable_field_access(db, partner, actor=_email(user), reason=row.incident_id)
    audit(
        db,
        actor=_email(user),
        action="partner.incident.created",
        entity_type="partner_incident",
        entity_id=row.incident_id,
        after={
            "partner_id": partner_id,
            "severity": severity,
            "type": incident_type,
            "immediate_suspension": immediate,
            "template": "TPL-PART-002",
        },
    )
    db.commit()
    db.refresh(row)
    return row


def record_incident_response(
    db: Session,
    incident_id: str,
    user: object,
    *,
    partner_statement: str,
    corrective_action: str,
    corrective_owner: str,
    corrective_due_at: datetime,
) -> PartnerIncident:
    row = db.scalar(select(PartnerIncident).where(PartnerIncident.incident_id == incident_id))
    if row is None:
        raise KeyError(incident_id)
    partner = _partner(db, row.partner_id)
    if _role(user) not in INTERNAL_ROLES and _email(user) != partner.primary_email:
        raise PermissionError("Nincs incidensválasz-rögzítési jogosultság.")
    if (
        min(
            len(partner_statement.strip()),
            len(corrective_action.strip()),
            len(corrective_owner.strip()),
        )
        < 5
        or corrective_due_at <= utcnow()
    ):
        raise ValueError("Részletes partnernyilatkozat, jövőbeli korrekció és felelős kötelező.")
    row.partner_statement = partner_statement.strip()
    row.corrective_action = corrective_action.strip()
    row.corrective_owner = corrective_owner.strip()
    row.corrective_due_at = corrective_due_at
    row.status = "corrective_action"
    audit(
        db,
        actor=_email(user),
        action="partner.incident.response_recorded",
        entity_type="partner_incident",
        entity_id=incident_id,
        after={"status": row.status, "corrective_due_at": corrective_due_at},
    )
    db.commit()
    return row


def close_incident(db: Session, incident_id: str, user: object, *, outcome: str) -> PartnerIncident:
    if _role(user) not in REVIEW_ROLES:
        raise PermissionError("Nincs incidenslezárási jogosultság.")
    row = db.scalar(select(PartnerIncident).where(PartnerIncident.incident_id == incident_id))
    if row is None:
        raise KeyError(incident_id)
    if len(outcome.strip()) < 10:
        raise ValueError("A bizonyított lezárási eredmény kötelező.")
    if row.severity in {"major", "critical"} and not all(
        (row.partner_statement, row.corrective_action, row.corrective_owner, row.corrective_due_at)
    ):
        raise ValueError(
            "Súlyos incidens csak partnernyilatkozat és dokumentált korrekció után zárható le."
        )
    row.status = "closed"
    row.closed_by = _email(user)
    row.closed_at = utcnow()
    audit(
        db,
        actor=_email(user),
        action="partner.incident.closed",
        entity_type="partner_incident",
        entity_id=incident_id,
        after={"outcome": outcome.strip()},
    )
    db.commit()
    return row


def propose_decision(
    db: Session,
    partner_id: str,
    user: object,
    *,
    decision_type: str,
    basis: dict[str, Any],
    conditions: dict[str, Any] | None = None,
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
    review_at: datetime | None = None,
) -> PartnerDecision:
    if _role(user) not in REVIEW_ROLES:
        raise PermissionError("Nincs partnerdöntés-előkészítési jogosultság.")
    partner = _partner(db, partner_id)
    decision_type = decision_type.strip().lower()
    if decision_type not in DECISION_TYPES:
        raise ValueError("Ismeretlen partnerdöntés.")
    if decision_type == "reinstatement_review" and partner.status not in {"suspended", "excluded"}:
        raise ValueError(
            "Újraengedélyezési review csak felfüggesztett vagy kizárt partnernél indítható."
        )
    if not basis or len(_json(basis)) < 20:
        raise ValueError("A döntés bizonyítékokkal alátámasztott alapja kötelező.")
    if decision_type == "conditional" and not conditions:
        raise ValueError("Feltételes megbízásnál a korlátozások kötelezők.")
    row = PartnerDecision(
        decision_id=_id("PDEC"),
        partner_id=partner_id,
        decision_type=decision_type,
        status="draft",
        basis_json=_json(basis),
        conditions_json=_json(conditions or {}),
        effective_from=effective_from or utcnow(),
        effective_until=effective_until,
        review_at=review_at,
        proposed_by=_email(user),
    )
    db.add(row)
    audit(
        db,
        actor=_email(user),
        action="partner.decision.proposed",
        entity_type="partner_decision",
        entity_id=row.decision_id,
        after={
            "partner_id": partner_id,
            "decision_type": decision_type,
            "template": "TPL-PART-003",
        },
    )
    db.commit()
    db.refresh(row)
    return row


def review_decision(
    db: Session, decision_id: str, user: object, *, review_type: str, note: str
) -> PartnerDecision:
    row = db.scalar(select(PartnerDecision).where(PartnerDecision.decision_id == decision_id))
    if row is None:
        raise KeyError(decision_id)
    if row.status not in {"draft", "reviewed"} or len(note.strip()) < 8:
        raise ValueError("A döntés nem felülvizsgálható vagy az indoklás hiányzik.")
    role = _role(user)
    if review_type == "pm":
        if role not in REVIEW_ROLES:
            raise PermissionError("Nincs PM-felülvizsgálati jogosultság.")
        row.pm_reviewed_by = _email(user)
    elif review_type == "finance_legal":
        if role not in QUALIFICATION_ROLES:
            raise PermissionError("Nincs pénzügyi/jogi felülvizsgálati jogosultság.")
        row.finance_legal_reviewed_by = _email(user)
    else:
        raise ValueError("Ismeretlen felülvizsgálattípus.")
    row.status = "reviewed"
    audit(
        db,
        actor=_email(user),
        action=f"partner.decision.{review_type}_reviewed",
        entity_type="partner_decision",
        entity_id=decision_id,
        after={"note": note.strip()},
    )
    db.commit()
    return row


def approve_decision(
    db: Session, decision_id: str, user: object, *, notification_evidence_ref: str
) -> PartnerDecision:
    if _role(user) not in LEADERSHIP_ROLES:
        raise PermissionError("Nincs partnerdöntés-jóváhagyási jogosultság.")
    row = db.scalar(select(PartnerDecision).where(PartnerDecision.decision_id == decision_id))
    if row is None:
        raise KeyError(decision_id)
    if not row.pm_reviewed_by:
        raise ValueError("Vezetői döntés előtt PM-felülvizsgálat szükséges.")
    if (
        row.decision_type in {"conditional", "suspended", "excluded", "reinstatement_review"}
        and not row.finance_legal_reviewed_by
    ):
        raise ValueError("Korlátozó döntés előtt pénzügyi/jogi felülvizsgálat szükséges.")
    if len(notification_evidence_ref.strip()) < 8:
        raise ValueError("A kézbesíthető döntésdokumentum hivatkozása kötelező.")
    partner = _partner(db, row.partner_id)
    if row.decision_type in {"approved", "conditional"} and partner.status in {
        "suspended",
        "excluded",
    }:
        reinstatement = db.scalar(
            select(PartnerDecision).where(
                PartnerDecision.decision_id == partner.current_decision_id,
                PartnerDecision.decision_type == "reinstatement_review",
                PartnerDecision.status == "approved",
            )
        )
        if reinstatement is None:
            raise ValueError("Visszaengedélyezés előtt jóváhagyott reinstatement review szükséges.")
        open_serious_incident = db.scalar(
            select(PartnerIncident).where(
                PartnerIncident.partner_id == partner.partner_id,
                PartnerIncident.severity.in_(("major", "critical")),
                PartnerIncident.status != "closed",
            )
        )
        if open_serious_incident is not None:
            raise ValueError(
                "Nyitott súlyos partnerincidens mellett visszaengedélyezés nem hagyható jóvá."
            )
    row.status = "approved"
    row.approved_by = _email(user)
    row.approved_at = utcnow()
    row.notification_evidence_ref = notification_evidence_ref.strip()
    partner.current_decision_id = row.decision_id
    partner.next_review_at = row.review_at
    if row.decision_type == "reinstatement_review":
        audit(
            db,
            actor=_email(user),
            action="partner.reinstatement_review.approved",
            entity_type="partner_decision",
            entity_id=decision_id,
            after={
                "partner_id": partner.partner_id,
                "partner_status": partner.status,
                "notification_evidence_ref": row.notification_evidence_ref,
            },
        )
        db.commit()
        return row
    partner.status = row.decision_type
    if row.decision_type in {"suspended", "excluded"}:
        _disable_field_access(db, partner, actor=_email(user), reason=row.decision_id)
    audit(
        db,
        actor=_email(user),
        action="partner.decision.approved",
        entity_type="partner_decision",
        entity_id=decision_id,
        after={
            "partner_id": partner.partner_id,
            "status": partner.status,
            "notification_evidence_ref": row.notification_evidence_ref,
        },
    )
    db.commit()
    return row


def _disable_field_access(db: Session, partner: PartnerProfile, *, actor: str, reason: str) -> None:
    queries = [PartnerFieldAccess.company_name == partner.company_name]
    if partner.tax_number:
        queries.append(PartnerFieldAccess.company_tax_number == partner.tax_number)
    rows: list[PartnerFieldAccess] = []
    for condition in queries:
        rows.extend(
            db.scalars(
                select(PartnerFieldAccess).where(condition, PartnerFieldAccess.active.is_(True))
            ).all()
        )
    seen: set[int] = set()
    for access in rows:
        if access.id in seen:
            continue
        seen.add(access.id)
        access.active = False
        audit(
            db,
            actor=actor,
            action="partner_field.access.auto_deactivated",
            entity_type="partner_field_access",
            entity_id=access.access_id,
            after={"partner_id": partner.partner_id, "reason": reason},
        )
