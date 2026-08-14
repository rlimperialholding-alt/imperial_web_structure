from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    B2BCRMDelivery,
    B2BDuplicateMatch,
    B2BFinancialReview,
    B2BProjectIntake,
    B2BQualificationDecision,
    B2BTechnicalReview,
    EnterpriseCanonicalRecord,
    MarketingLead,
    ModuleBusinessRecord,
    OutboxMessage,
    ProjectRegistry,
    TaskRecord,
    WorkspaceDocument,
)
from ..schemas import (
    B2BCRMReceiptIn,
    B2BDuplicateDecisionIn,
    B2BFinancialReviewIn,
    B2BProjectIntakeIn,
    B2BQualificationDecisionIn,
    B2BTechnicalReviewIn,
)


CAPTURE_ROLES = {"owner", "managing-director", "marketing", "sales", "platform-admin"}
SALES_ROLES = {"owner", "managing-director", "sales", "platform-admin"}
LEADERSHIP_ROLES = {"owner", "managing-director"}
VALID_PROJECT_TYPES = {"corporate", "industrial", "multifamily", "public_procurement", "partner", "international"}
VALID_LAWFUL_BASES = {"consent", "contract_request", "legitimate_interest", "public_tender", "partner_referral"}
APPROVED_REVIEW_DECISIONS = {"approved", "conditional"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _valid_sha(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError("Érvényes SHA-256 lenyomat szükséges.")
    return normalized


def _normalize_company(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    folded = re.sub(r"\b(kft|zrt|nyrt|bt|ltd|limited|gmbh|inc|rt)\b", " ", folded)
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _tax(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits or None


def _domain(value: str | None, email: str | None) -> str | None:
    raw = (value or "").strip().lower()
    if raw:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host and "." in host and not host.endswith(".local"):
            return host
        raise ValueError("Érvényes nyilvános vállalati domain szükséges.")
    if email and "@" in email:
        host = email.rsplit("@", 1)[1].strip().lower()
        if "." in host:
            return host
    return None


def _intake(db: Session, intake_id: str) -> B2BProjectIntake:
    row = db.scalar(select(B2BProjectIntake).where(B2BProjectIntake.intake_id == intake_id))
    if not row:
        raise KeyError(intake_id)
    return row


def _missing(data: B2BProjectIntakeIn, domain: str | None) -> list[str]:
    missing: list[str] = []
    if not data.tax_number and not domain: missing.append("organization_identity")
    if not data.contact_email and not data.contact_phone: missing.append("contact_channel")
    if not data.city.strip(): missing.append("city")
    if data.gross_floor_area_m2 <= 0: missing.append("gross_floor_area_m2")
    if not data.planned_start: missing.append("planned_start")
    if data.estimated_budget_huf <= 0: missing.append("estimated_budget_huf")
    if len(data.project_summary.strip()) < 30: missing.append("detailed_project_summary")
    if not data.document_ids: missing.append("verified_document")
    return missing


def _score(data: B2BProjectIntakeIn, domain: str | None, missing: list[str]) -> tuple[int, list[str]]:
    score = 0; reasons: list[str] = []
    if data.source_use_approved and data.lawful_basis in VALID_LAWFUL_BASES: score += 10; reasons.append("jóváhagyott, jogalappal rögzített forrás +10")
    if data.tax_number: score += 10; reasons.append("adóazonosító +10")
    if domain: score += 5; reasons.append("vállalati domain +5")
    if data.contact_email and data.contact_phone: score += 10; reasons.append("kétcsatornás kapcsolattartó +10")
    elif data.contact_email or data.contact_phone: score += 5; reasons.append("kapcsolattartási csatorna +5")
    if data.city and data.site_address: score += 10; reasons.append("pontos helyszín +10")
    elif data.city: score += 5; reasons.append("település +5")
    if data.gross_floor_area_m2 >= 1000: score += 10; reasons.append("1000+ m² volumen +10")
    elif data.gross_floor_area_m2 > 0: score += 5; reasons.append("azonosított volumen +5")
    if data.estimated_budget_huf >= Decimal("1000000000"): score += 15; reasons.append("1 Mrd+ keret +15")
    elif data.estimated_budget_huf >= Decimal("250000000"): score += 10; reasons.append("250 M+ keret +10")
    elif data.estimated_budget_huf > 0: score += 5; reasons.append("azonosított keret +5")
    if data.planned_start and data.requested_deadline: score += 10; reasons.append("indítás és céldátum +10")
    elif data.planned_start: score += 5; reasons.append("azonosított indítás +5")
    if data.document_ids: score += 10; reasons.append("ellenőrzött dokumentum +10")
    if len(data.project_summary.strip()) >= 100: score += 10; reasons.append("részletes projektleírás +10")
    elif len(data.project_summary.strip()) >= 30: score += 5; reasons.append("értelmezhető projektleírás +5")
    if data.project_type in VALID_PROJECT_TYPES: score += 5; reasons.append("szolgáltatási körbe sorolt projekttípus +5")
    score -= min(len(missing) * 5, 25)
    if missing: reasons.append(f"hiányzó kötelező mezők -{min(len(missing) * 5, 25)}")
    return max(0, min(score, 100)), reasons


def _validate_documents(db: Session, document_ids: list[str]) -> None:
    if len(set(document_ids)) != len(document_ids):
        raise ValueError("A dokumentumhivatkozások nem lehetnek duplikáltak.")
    if not document_ids:
        return
    docs = list(db.scalars(select(WorkspaceDocument).where(WorkspaceDocument.document_id.in_(document_ids))).all())
    if len(docs) != len(document_ids):
        raise ValueError("Legalább egy megadott dokumentum nem található a Dokumentumtárban.")
    invalid = [row.document_id for row in docs if row.verification_status != "verified" or row.approval_status not in {"approved", "active", "published"}]
    if invalid:
        raise ValueError("Csak ellenőrzött és jóváhagyott dokumentum használható: " + ", ".join(invalid))


def _complexity(data: B2BProjectIntakeIn) -> str:
    if data.project_type in {"public_procurement", "international"} or data.gross_floor_area_m2 >= 5000:
        return "high"
    if data.gross_floor_area_m2 >= 1000 or data.estimated_budget_huf >= Decimal("500000000"):
        return "medium"
    return "low"


def _refresh_status(row: B2BProjectIntake) -> None:
    missing = json.loads(row.missing_fields_json or "[]")
    row.status = "incomplete" if missing else "prescreen"


def _create_duplicate_matches(db: Session, row: B2BProjectIntake) -> list[B2BDuplicateMatch]:
    candidates = list(db.scalars(select(B2BProjectIntake).where(B2BProjectIntake.intake_id != row.intake_id, B2BProjectIntake.status != "merged").order_by(desc(B2BProjectIntake.created_at)).limit(250)).all())
    matches: list[B2BDuplicateMatch] = []
    for candidate in candidates:
        score = 0; reasons: list[str] = []; scope = "company"
        if row.tax_number and row.tax_number == candidate.tax_number: score = 100; reasons.append("azonos adószám")
        elif row.company_fingerprint == candidate.company_fingerprint: score = 95; reasons.append("azonos normalizált vállalat")
        elif row.website_domain and row.website_domain == candidate.website_domain: score = 90; reasons.append("azonos vállalati domain")
        if row.project_fingerprint == candidate.project_fingerprint:
            score = 100; scope = "project"; reasons.append("azonos vállalat, helyszín, projekttípus és indulási év")
        elif row.organization_name_normalized == candidate.organization_name_normalized and row.city.lower() == candidate.city.lower() and row.project_type == candidate.project_type:
            score = max(score, 85); scope = "project"; reasons.append("azonos vállalat, település és projekttípus")
        if score < 85:
            continue
        match = B2BDuplicateMatch(match_id=_id("B2BM"), intake_id=row.intake_id, candidate_intake_id=candidate.intake_id, match_scope=scope, match_score=score, reasons_json=_json(reasons), status="pending")
        db.add(match); matches.append(match)
    return matches


def capture_intake(db: Session, data: B2BProjectIntakeIn, actor: str, actor_role: str) -> B2BProjectIntake:
    if actor_role not in CAPTURE_ROLES:
        raise PermissionError("B2B projektigény rögzítésére nincs jogosultság.")
    if not data.source_use_approved or data.lawful_basis not in VALID_LAWFUL_BASES:
        raise ValueError("Csak jóváhagyott, rögzített jogalappal használható forrás fogadható.")
    if data.project_type not in VALID_PROJECT_TYPES:
        raise ValueError("Ismeretlen vállalati projekttípus.")
    if data.planned_start and data.requested_deadline and data.requested_deadline <= data.planned_start:
        raise ValueError("A kért céldátumnak az indulás után kell lennie.")
    existing = db.scalar(select(B2BProjectIntake).where(B2BProjectIntake.source_system == data.source_system.strip().lower(), B2BProjectIntake.source_external_id == data.source_external_id.strip()))
    if existing:
        existing.signal_count += 1; existing.updated_by = actor
        audit(db, actor=actor, action="b2b.intake.idempotent_signal", entity_type="b2b_project_intake", entity_id=existing.intake_id, after={"signal_count": existing.signal_count})
        db.commit(); db.refresh(existing); return existing
    _validate_documents(db, data.document_ids)
    if data.linked_marketing_lead_id:
        lead = db.scalar(select(MarketingLead).where(MarketingLead.lead_id == data.linked_marketing_lead_id))
        if not lead or lead.lead_type != "b2b":
            raise ValueError("Csak létező B2B Lead Intelligence jel kapcsolható az igényhez.")
    normalized = _normalize_company(data.organization_name)
    if len(normalized) < 2:
        raise ValueError("A szervezet neve normalizálás után nem azonosítható.")
    tax_number = _tax(data.tax_number); website_domain = _domain(data.website_domain, data.contact_email)
    missing = _missing(data, website_domain); score, reasons = _score(data, website_domain, missing)
    company_fingerprint = _sha({"name": normalized, "tax": tax_number, "domain": website_domain})
    project_fingerprint = _sha({"company": company_fingerprint, "city": data.city.strip().lower(), "type": data.project_type, "start_year": data.planned_start.year if data.planned_start else None})
    row = B2BProjectIntake(
        intake_id=_id("B2BI"), source_system=data.source_system.strip().lower(), source_external_id=data.source_external_id.strip(), source_reference=data.source_reference.strip(), source_content_sha256=_valid_sha(data.source_content_sha256), lawful_basis=data.lawful_basis, source_use_approved=True, linked_marketing_lead_id=data.linked_marketing_lead_id,
        organization_name=data.organization_name.strip(), organization_name_normalized=normalized, tax_number=tax_number, website_domain=website_domain, contact_name=data.contact_name.strip(), contact_email=data.contact_email.strip().lower() if data.contact_email else None, contact_phone=data.contact_phone.strip() if data.contact_phone else None,
        project_type=data.project_type, country=data.country.strip().upper(), city=data.city.strip(), site_address=data.site_address.strip() if data.site_address else None, gross_floor_area_m2=data.gross_floor_area_m2, planned_start=data.planned_start, requested_deadline=data.requested_deadline, estimated_budget_huf=data.estimated_budget_huf, project_summary=data.project_summary.strip(), document_ids_json=_json(data.document_ids),
        company_fingerprint=company_fingerprint, project_fingerprint=project_fingerprint, missing_fields_json=_json(missing), base_score=score, score_reasons_json=_json(reasons), complexity=_complexity(data), strategic_review_required=False, status="captured", created_by=actor, updated_by=actor,
    )
    db.add(row); db.flush()
    matches = _create_duplicate_matches(db, row)
    row.status = "dedupe_review" if matches else ("incomplete" if missing else "prescreen")
    audit(db, actor=actor, action="b2b.intake.capture", entity_type="b2b_project_intake", entity_id=row.intake_id, after={"score": score, "missing": missing, "duplicate_matches": len(matches), "source_sha256": row.source_content_sha256})
    db.commit(); db.refresh(row); return row


def resolve_duplicate(db: Session, match_id: str, data: B2BDuplicateDecisionIn, actor: str, actor_role: str) -> B2BDuplicateMatch:
    if actor_role not in SALES_ROLES:
        raise PermissionError("Deduplikációs döntésre nincs jogosultság.")
    match = db.scalar(select(B2BDuplicateMatch).where(B2BDuplicateMatch.match_id == match_id))
    if not match: raise KeyError(match_id)
    if match.status != "pending" or data.decision not in {"merge", "distinct"}:
        raise ValueError("Csak függő egyezésről hozható merge vagy distinct döntés.")
    row = _intake(db, match.intake_id)
    candidate = _intake(db, match.candidate_intake_id)
    match.status = data.decision
    match.reviewed_by = actor
    match.review_note = data.note.strip()
    match.reviewed_at = utcnow()
    if data.decision == "merge":
        row.status = "merged"; candidate.signal_count += row.signal_count; candidate.updated_by = actor
    else:
        remaining = db.scalar(select(B2BDuplicateMatch).where(B2BDuplicateMatch.intake_id == row.intake_id, B2BDuplicateMatch.status == "pending", B2BDuplicateMatch.match_id != match_id))
        if not remaining: _refresh_status(row)
    audit(db, actor=actor, action="b2b.duplicate.resolve", entity_type="b2b_duplicate_match", entity_id=match_id, after={"decision": data.decision, "intake_id": row.intake_id, "candidate_intake_id": candidate.intake_id})
    db.commit(); db.refresh(match); return match


def record_technical_review(db: Session, intake_id: str, data: B2BTechnicalReviewIn, actor: str, actor_role: str) -> B2BTechnicalReview:
    if actor_role != "project-manager" and actor_role not in {"owner", "managing-director"}:
        raise PermissionError("Műszaki előszűrést projektmenedzser rögzíthet.")
    row = _intake(db, intake_id)
    if row.status not in {"prescreen", "technical_review"}: raise ValueError("Az igény nem áll műszaki előszűrés alatt.")
    if data.decision not in {"approved", "conditional", "rejected"} or data.complexity not in {"low", "medium", "high"}:
        raise ValueError("Ismeretlen műszaki döntés vagy komplexitás.")
    if db.scalar(select(B2BTechnicalReview).where(B2BTechnicalReview.intake_id == intake_id)): raise ValueError("A műszaki előszűrés már megtörtént.")
    review = B2BTechnicalReview(review_id=_id("B2BTR"), intake_id=intake_id, decision=data.decision, delivery_model=data.delivery_model, capacity_fit=data.capacity_fit, site_feasibility=data.site_feasibility, complexity=data.complexity, assumptions_json=_json(data.assumptions), note=data.note.strip(), reviewer=actor)
    db.add(review); row.complexity = data.complexity; row.status = "rejected" if data.decision == "rejected" else "financial_review"; row.updated_by = actor
    audit(db, actor=actor, action="b2b.technical.review", entity_type="b2b_technical_review", entity_id=review.review_id, after={"intake_id": intake_id, "decision": data.decision, "complexity": data.complexity})
    db.commit(); db.refresh(review); return review


def record_financial_review(db: Session, intake_id: str, data: B2BFinancialReviewIn, actor: str, actor_role: str) -> B2BFinancialReview:
    if actor_role != "finance" and actor_role not in {"owner", "managing-director"}:
        raise PermissionError("Pénzügyi előszűrést pénzügyi szerepkör rögzíthet.")
    row = _intake(db, intake_id)
    if row.status != "financial_review": raise ValueError("Az igény nem áll pénzügyi előszűrés alatt.")
    if data.decision not in {"approved", "conditional", "rejected"}: raise ValueError("Ismeretlen pénzügyi döntés.")
    if db.scalar(select(B2BFinancialReview).where(B2BFinancialReview.intake_id == intake_id)): raise ValueError("A pénzügyi előszűrés már megtörtént.")
    review = B2BFinancialReview(review_id=_id("B2BFR"), intake_id=intake_id, decision=data.decision, budget_credibility=data.budget_credibility, funding_status=data.funding_status, preliminary_margin_band=data.preliminary_margin_band, assumptions_json=_json(data.assumptions), note=data.note.strip(), reviewer=actor)
    db.add(review); row.status = "rejected" if data.decision == "rejected" else "commercial_review"; row.updated_by = actor
    audit(db, actor=actor, action="b2b.financial.review", entity_type="b2b_financial_review", entity_id=review.review_id, after={"intake_id": intake_id, "decision": data.decision, "funding_status": data.funding_status})
    db.commit(); db.refresh(review); return review


def qualify_intake(db: Session, intake_id: str, data: B2BQualificationDecisionIn, actor: str, actor_role: str) -> B2BQualificationDecision:
    if actor_role not in SALES_ROLES: raise PermissionError("Kereskedelmi minősítésre nincs jogosultság.")
    row = _intake(db, intake_id)
    if row.status != "commercial_review": raise ValueError("Az igény nem áll kereskedelmi döntés alatt.")
    if data.decision not in {"qualified", "rejected"}: raise ValueError("A kereskedelmi döntés qualified vagy rejected lehet.")
    assignee = data.assigned_sales_email.strip().lower()
    if "@" not in assignee: raise ValueError("Érvényes értékesítői e-mail szükséges.")
    if actor_role == "sales" and actor.lower() != assignee: raise PermissionError("Értékesítő csak saját felelősségre veheti át az igényt.")
    strategic = row.complexity == "high" or row.estimated_budget_huf >= Decimal("1000000000") or row.project_type in {"public_procurement", "international"}
    decision = B2BQualificationDecision(decision_id=_id("B2BD"), intake_id=intake_id, decision_type="sales", decision=data.decision, route=data.route, next_action=data.next_action.strip(), note=data.note.strip(), decided_by=actor)
    db.add(decision); row.assigned_sales_email = assignee; row.strategic_review_required = strategic; row.status = "rejected" if data.decision == "rejected" else ("leadership_review" if strategic else "crm_ready"); row.updated_by = actor
    if data.decision == "qualified" and strategic:
        db.add(TaskRecord(task_id=_id("TASK-B2B"), project_id="COMMERCIAL-PIPELINE", source_event_id=intake_id, title=f"Stratégiai B2B projektigény vezetői döntése: {row.organization_name}", description=row.project_summary, assignee="managing-director", priority="high", status="open", executive_relevance=True))
    audit(db, actor=actor, action="b2b.qualification.sales", entity_type="b2b_qualification_decision", entity_id=decision.decision_id, after={"intake_id": intake_id, "decision": data.decision, "strategic_review_required": strategic, "route": data.route})
    db.commit(); db.refresh(decision); return decision


def leadership_decision(db: Session, intake_id: str, data: B2BQualificationDecisionIn, actor: str, actor_role: str) -> B2BQualificationDecision:
    if actor_role not in LEADERSHIP_ROLES: raise PermissionError("Stratégiai döntésre csak ügyvezető vagy tulajdonos jogosult.")
    row = _intake(db, intake_id)
    if row.status != "leadership_review": raise ValueError("Az igény nem vár stratégiai döntésre.")
    if data.decision not in {"approved", "rejected"}: raise ValueError("A vezetői döntés approved vagy rejected lehet.")
    decision = B2BQualificationDecision(decision_id=_id("B2BD"), intake_id=intake_id, decision_type="leadership", decision=data.decision, route=data.route, next_action=data.next_action.strip(), note=data.note.strip(), decided_by=actor)
    db.add(decision); row.status = "crm_ready" if data.decision == "approved" else "rejected"; row.updated_by = actor
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == intake_id, TaskRecord.status == "open", TaskRecord.executive_relevance.is_(True)))
    if task: task.status = "done"
    audit(db, actor=actor, action="b2b.qualification.leadership", entity_type="b2b_qualification_decision", entity_id=decision.decision_id, after={"intake_id": intake_id, "decision": data.decision, "route": data.route})
    db.commit(); db.refresh(decision); return decision


def _ensure_pipeline(db: Session, responsible: str) -> None:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == "COMMERCIAL-PIPELINE")):
        db.add(ProjectRegistry(project_id="COMMERCIAL-PIPELINE", name="Értékesítési lead pipeline", project_type="commercial_pipeline", status="active", responsible=responsible, next_action="Minősített B2B igények feldolgozása")); db.flush()


def queue_crm_handoff(db: Session, intake_id: str, actor: str, actor_role: str) -> B2BCRMDelivery:
    if actor_role not in SALES_ROLES: raise PermissionError("CRM-átadásra nincs jogosultság.")
    row = _intake(db, intake_id)
    if row.status != "crm_ready": raise ValueError("Csak minden emberi kapun átment igény adható át a CRM-nek.")
    if actor_role == "sales" and row.assigned_sales_email != actor.lower(): raise PermissionError("Az igény másik értékesítőhöz tartozik.")
    if db.scalar(select(B2BCRMDelivery).where(B2BCRMDelivery.intake_id == intake_id)): raise ValueError("Az igény CRM-átadása már létrejött.")
    technical = db.scalar(select(B2BTechnicalReview).where(B2BTechnicalReview.intake_id == intake_id)); financial = db.scalar(select(B2BFinancialReview).where(B2BFinancialReview.intake_id == intake_id))
    if not technical or technical.decision not in APPROVED_REVIEW_DECISIONS or not financial or financial.decision not in APPROVED_REVIEW_DECISIONS:
        raise ValueError("Érvényes műszaki és pénzügyi emberi előszűrés szükséges.")
    payload = {"event": "B2B_PROJECT_QUALIFIED", "intakeId": row.intake_id, "leadType": "b2b_project", "organizationName": row.organization_name, "taxNumber": row.tax_number, "websiteDomain": row.website_domain, "contactName": row.contact_name, "contactEmail": row.contact_email, "contactPhone": row.contact_phone, "projectType": row.project_type, "location": {"country": row.country, "city": row.city, "address": row.site_address}, "grossFloorAreaM2": str(row.gross_floor_area_m2), "plannedStart": row.planned_start.isoformat() if row.planned_start else None, "requestedDeadline": row.requested_deadline.isoformat() if row.requested_deadline else None, "estimatedBudgetHuf": str(row.estimated_budget_huf), "summary": row.project_summary, "score": row.base_score, "complexity": row.complexity, "assignedSalesEmail": row.assigned_sales_email, "source": {"system": row.source_system, "externalId": row.source_external_id, "reference": row.source_reference, "sha256": row.source_content_sha256, "lawfulBasis": row.lawful_basis}, "documents": json.loads(row.document_ids_json), "technicalReviewId": technical.review_id, "financialReviewId": financial.review_id}
    payload_sha = _sha(payload); canonical_id = f"CAN-{row.intake_id}"; crm_record_id = f"CRM-{row.intake_id}"
    canonical = EnterpriseCanonicalRecord(record_id=canonical_id, domain="customer", entity_type="lead", external_key=row.intake_id, canonical_name=row.organization_name, target_module="crm", status="active", data_json=_json(payload), provenance_json=_json({"source": "b2b-project-intake", "sourceReference": row.source_reference, "sourceSha256": row.source_content_sha256, "createdAt": row.created_at.isoformat()}))
    db.add(canonical)
    db.add(ModuleBusinessRecord(record_id=crm_record_id, module_key="crm", record_type="B2B Project Lead", title=f"{row.organization_name} – {row.project_type}", description=row.project_summary, status="qualified", customer_reference=row.intake_id, assignee=row.assigned_sales_email, priority="high" if row.strategic_review_required else "normal", amount_huf=row.estimated_budget_huf, data_json=_json(payload), created_by=actor, updated_by=actor))
    _ensure_pipeline(db, row.assigned_sales_email or actor)
    delivery = B2BCRMDelivery(delivery_id=_id("B2BC"), intake_id=intake_id, idempotency_key=f"b2b-crm:{intake_id}", payload_sha256=payload_sha, status="pending", queued_by=actor)
    db.add(delivery)
    db.add(OutboxMessage(message_id=_id("MSG-B2B"), destination_module="crm", endpoint="/b2b-project-intakes", payload_json=_json({**payload, "deliveryId": delivery.delivery_id, "idempotencyKey": delivery.idempotency_key, "payloadSha256": payload_sha}), status="pending", max_retries=5, next_attempt_at=utcnow()))
    db.add(TaskRecord(task_id=_id("TASK-B2B"), project_id="COMMERCIAL-PIPELINE", source_event_id=intake_id, title=f"B2B projektigény értékesítési feldolgozása: {row.organization_name}", description=f"Következő lépés: CRM receipt után {row.assigned_sales_email} veszi át. {row.project_summary}", assignee=row.assigned_sales_email, priority="high" if row.strategic_review_required else "normal", status="open", executive_relevance=row.strategic_review_required))
    row.status = "crm_dispatch"; row.canonical_record_id = canonical_id; row.crm_record_id = crm_record_id; row.updated_by = actor
    audit(db, actor=actor, action="b2b.crm.queue", entity_type="b2b_crm_delivery", entity_id=delivery.delivery_id, after={"intake_id": intake_id, "payload_sha256": payload_sha, "canonical_record_id": canonical_id, "crm_record_id": crm_record_id})
    db.commit(); db.refresh(delivery); return delivery


def record_crm_receipt(db: Session, data: B2BCRMReceiptIn, actor: str, actor_role: str) -> B2BCRMDelivery:
    if actor_role not in {"adapter", "platform-admin"}: raise PermissionError("CRM receipt rögzítésére nincs jogosultság.")
    delivery = db.scalar(select(B2BCRMDelivery).where(B2BCRMDelivery.delivery_id == data.delivery_id))
    if not delivery: raise KeyError(data.delivery_id)
    if data.idempotency_key != delivery.idempotency_key or _valid_sha(data.payload_sha256) != delivery.payload_sha256:
        raise ValueError("A CRM receipt idempotency kulcsa vagy payload hash-e eltér.")
    if delivery.status == "accepted" and data.accepted and delivery.external_crm_id == data.external_crm_id: return delivery
    if delivery.status != "pending": raise ValueError("Receipt csak pending CRM-átadáshoz fogadható.")
    row = _intake(db, delivery.intake_id)
    if data.accepted:
        if not data.external_crm_id: raise ValueError("Elfogadott CRM receipthez külső rekordazonosító szükséges.")
        delivery.status = "accepted"; delivery.external_crm_id = data.external_crm_id; row.status = "crm_handoff"
    else:
        delivery.status = "rejected"; delivery.failure_reason = data.error_message or "Ismeretlen CRM adapterhiba"; row.status = "handoff_failed"
        db.add(TaskRecord(task_id=_id("TASK-B2B"), project_id="COMMERCIAL-PIPELINE", source_event_id=row.intake_id, title=f"B2B CRM-átadás javítása: {row.organization_name}", description=delivery.failure_reason, assignee="platform-admin", priority="high", status="open", executive_relevance=False))
    delivery.receipt_at = utcnow(); row.updated_by = actor
    audit(db, actor=actor, action="b2b.crm.receipt", entity_type="b2b_crm_delivery", entity_id=delivery.delivery_id, after={"accepted": data.accepted, "external_crm_id": data.external_crm_id, "status": delivery.status})
    db.commit(); db.refresh(delivery); return delivery


def workspace(db: Session) -> dict:
    intakes = list(db.scalars(select(B2BProjectIntake).order_by(desc(B2BProjectIntake.created_at))).all())
    matches = list(db.scalars(select(B2BDuplicateMatch).order_by(desc(B2BDuplicateMatch.created_at))).all())
    technical = list(db.scalars(select(B2BTechnicalReview).order_by(desc(B2BTechnicalReview.created_at))).all())
    financial = list(db.scalars(select(B2BFinancialReview).order_by(desc(B2BFinancialReview.created_at))).all())
    decisions = list(db.scalars(select(B2BQualificationDecision).order_by(desc(B2BQualificationDecision.decided_at))).all())
    deliveries = list(db.scalars(select(B2BCRMDelivery).order_by(desc(B2BCRMDelivery.queued_at))).all())
    documents = list(db.scalars(select(WorkspaceDocument).where(WorkspaceDocument.verification_status == "verified", WorkspaceDocument.approval_status.in_({"approved", "active", "published"})).order_by(WorkspaceDocument.title)).all())
    return {"intakes": intakes, "matches": matches, "technical_reviews": technical, "financial_reviews": financial, "decisions": decisions, "deliveries": deliveries, "documents": documents, "metrics": {"total": len(intakes), "dedupe_review": sum(row.status == "dedupe_review" for row in intakes), "incomplete": sum(row.status == "incomplete" for row in intakes), "prescreen": sum(row.status in {"prescreen", "technical_review", "financial_review", "commercial_review"} for row in intakes), "leadership_review": sum(row.status == "leadership_review" for row in intakes), "crm_handoff": sum(row.status == "crm_handoff" for row in intakes), "handoff_failed": sum(row.status == "handoff_failed" for row in intakes)}}
