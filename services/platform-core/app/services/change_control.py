from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    CalendarEntry,
    ChangeControlCase,
    ChangeControlLine,
    ChangeControlVersion,
    CustomerDecisionRequest,
    CustomerDecisionResponse,
    ProjectRegistry,
    TaskRecord,
    WorkspaceDocument,
)
from ..schemas import ChangeControlEventIn
from .change_control_documents import render_change_control_pdf
from .commercial_integration import ingest_change_control_event
from .my_imperial import create_decision_request

EDIT_ROLES = {"owner", "platform-admin", "project-manager", "technical-prep"}
TECHNICAL_ROLES = {"owner", "platform-admin", "project-manager", "technical-prep"}
FINANCE_ROLES = {"owner", "platform-admin", "finance"}
LEADERSHIP_ROLES = {"owner", "platform-admin", "managing-director"}
WORK_AUTH_ROLES = {"owner", "platform-admin", "project-manager", "technical-prep"}
MINIMUM_MARGIN_PERCENT = Decimal("35.00")
LEADERSHIP_VALUE_THRESHOLD_HUF = Decimal("5000000")
LEADERSHIP_DEADLINE_THRESHOLD_DAYS = 5
CUSTOMER_ACCEPT_OPTION = "Elfogadom a ChangeID és verzió szerinti módosítást"
CUSTOMER_REJECT_OPTION = "Elutasítom a módosítást"


def _identity(user: object) -> tuple[str, str]:
    return (
        str(getattr(user, "role", "")),
        str(getattr(user, "email", "")).strip().lower(),
    )


def _require(user: object, roles: set[str]) -> tuple[str, str]:
    role, email = _identity(user)
    if role not in roles:
        raise PermissionError("Ehhez a ChangeControl művelethez nincs jogosultsága.")
    return role, email


def _decimal(value: object, *, quantity: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Érvénytelen számérték a változtatási ügyben.") from exc
    if amount < 0 or (quantity and amount <= 0):
        raise ValueError("Negatív összeg vagy nem pozitív mennyiség nem rögzíthető.")
    return amount.quantize(Decimal("0.001") if quantity else Decimal("0.01"))


def _case(db: Session, change_id: str) -> ChangeControlCase:
    row = db.scalar(select(ChangeControlCase).where(ChangeControlCase.change_id == change_id))
    if not row:
        raise KeyError(change_id)
    return row


def _version(db: Session, change_id: str, version: int | None = None) -> ChangeControlVersion:
    case = _case(db, change_id)
    number = version or case.current_version
    row = db.scalar(
        select(ChangeControlVersion).where(
            ChangeControlVersion.change_id_fk == case.id,
            ChangeControlVersion.version == number,
        )
    )
    if not row:
        raise KeyError(f"{change_id}/v{number}")
    return row


def _lines(db: Session, version: ChangeControlVersion) -> list[ChangeControlLine]:
    return list(db.scalars(
        select(ChangeControlLine)
        .where(ChangeControlLine.version_id_fk == version.id)
        .order_by(ChangeControlLine.id)
    ).all())


def _recalculate(db: Session, version: ChangeControlVersion) -> list[ChangeControlLine]:
    lines = _lines(db, version)
    cost = sum((row.total_cost_net for row in lines), Decimal("0"))
    sale = sum((row.total_sale_net for row in lines), Decimal("0"))
    early = sum((row.total_cost_net for row in lines if row.early_direct_cost), Decimal("0"))
    margin = sale - cost
    margin_percent = (
        (margin / sale * Decimal("100")).quantize(Decimal("0.01")) if sale else Decimal("0")
    )
    vat = (sale * version.vat_rate / Decimal("100")).quantize(Decimal("0.01"))
    version.cost_net = cost
    version.sale_net = sale
    version.early_direct_cost_net = early
    version.margin_net = margin
    version.margin_percent = margin_percent
    version.vat_amount = vat
    version.sale_gross = sale + vat
    version.leadership_required = (
        sale >= LEADERSHIP_VALUE_THRESHOLD_HUF
        or abs(version.deadline_impact_days) >= LEADERSHIP_DEADLINE_THRESHOLD_DAYS
    )
    return lines


def _snapshot(version: ChangeControlVersion, lines: list[ChangeControlLine]) -> dict:
    return {
        "version_id": version.version_id,
        "version": version.version,
        "reason": version.reason,
        "technical_scope": version.technical_scope,
        "exclusions": version.exclusions,
        "assumptions": version.assumptions,
        "deadline_impact_days": version.deadline_impact_days,
        "vat_rate": str(version.vat_rate),
        "customer_advance_net": str(version.customer_advance_net),
        "cost_net": str(version.cost_net),
        "sale_net": str(version.sale_net),
        "sale_gross": str(version.sale_gross),
        "margin_percent": str(version.margin_percent),
        "early_direct_cost_net": str(version.early_direct_cost_net),
        "lines": [
            {
                "line_id": row.line_id,
                "category": row.category,
                "description": row.description,
                "quantity": str(row.quantity),
                "unit": row.unit,
                "unit_cost_net": str(row.unit_cost_net),
                "unit_sale_net": str(row.unit_sale_net),
                "early_direct_cost": row.early_direct_cost,
            }
            for row in lines
        ],
    }


def _hash_snapshot(snapshot: dict) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _document_snapshot(
    db: Session,
    case: ChangeControlCase,
    version: ChangeControlVersion,
    *,
    title_prefix: str,
    owner: str,
) -> WorkspaceDocument:
    audience = "customer" if title_prefix == "Ügyfélcsomag" else "internal"
    variant = (
        "customer"
        if audience == "customer"
        else "internal-approved"
        if "jóváhagyott" in title_prefix.lower()
        else "internal-review"
    )
    document_id = f"DOC-CHG-{case.change_id}-V{version.version}-{title_prefix.upper()}"[:120]
    row = db.scalar(select(WorkspaceDocument).where(WorkspaceDocument.document_id == document_id))
    if row:
        metadata = json.loads(row.metadata_json or "{}")
        existing_path = Path(metadata.get("local_path") or "")
        if (
            metadata.get("content_sha256") == version.content_sha256
            and metadata.get("variant") == variant
            and existing_path.is_file()
            and hashlib.sha256(existing_path.read_bytes()).hexdigest()
            == metadata.get("artifact_sha256")
        ):
            return row
    if not row:
        row = WorkspaceDocument(
            document_id=document_id,
            project_id=case.project_id,
            title=f"{title_prefix}: {case.title} – {case.change_id} v{version.version}",
            category="change_order",
            source_system="change-control",
            version_label=f"v{version.version}",
            approval_status="approved" if audience == "customer" else "review",
            verification_status="pending_artifact",
            confidentiality=audience,
            owner=owner,
            extracted_summary=(
                f"Nettó eladási ár {version.sale_net} HUF; fedezet "
                f"{version.margin_percent}%; határidőhatás {version.deadline_impact_days} nap."
            ),
            metadata_json="{}",
        )
        db.add(row)
    output_path, artifact_sha = render_change_control_pdf(
        case,
        version,
        _lines(db, version),
        audience=audience,
        variant=variant,
    )
    row.mime_type = "application/pdf"
    row.source_url = (
        f"/my-imperial/{case.project_id}/documents/{document_id}"
        if audience == "customer"
        else f"/change-control/files/{document_id}"
    )
    row.verification_status = "sha256_verified"
    row.metadata_json = json.dumps(
        {
            "change_id": case.change_id,
            "version": version.version,
            "audience": audience,
            "variant": variant,
            "content_sha256": version.content_sha256,
            "artifact_sha256": artifact_sha,
            "local_path": str(output_path),
            "immutable_snapshot": True,
        },
        ensure_ascii=False,
    )
    return row


def change_control_workspace(db: Session, *, project_id: str | None = None) -> dict:
    stmt = select(ChangeControlCase)
    if project_id:
        stmt = stmt.where(ChangeControlCase.project_id == project_id)
    cases = db.scalars(stmt.order_by(desc(ChangeControlCase.updated_at))).all()
    versions = {
        row.change_id_fk: row
        for row in db.scalars(
            select(ChangeControlVersion).where(
                ChangeControlVersion.id.in_(
                    select(func.max(ChangeControlVersion.id)).group_by(
                        ChangeControlVersion.change_id_fk
                    )
                )
            )
        ).all()
    }
    return {
        "cases": [{"row": row, "version": versions.get(row.id)} for row in cases],
        "projects": db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all(),
        "metrics": {
            "cases": len(cases),
            "review": sum(row.status in {"internal_review", "customer_review"} for row in cases),
            "authorized": sum(row.status == "work_authorized" for row in cases),
            "completed": sum(row.status == "completed" for row in cases),
        },
        "policy": {
            "minimum_margin_percent": MINIMUM_MARGIN_PERCENT,
            "leadership_value_threshold_huf": LEADERSHIP_VALUE_THRESHOLD_HUF,
            "leadership_deadline_threshold_days": LEADERSHIP_DEADLINE_THRESHOLD_DAYS,
        },
    }


def change_control_detail(db: Session, change_id: str) -> dict:
    case = _case(db, change_id)
    versions = db.scalars(
        select(ChangeControlVersion)
        .where(ChangeControlVersion.change_id_fk == case.id)
        .order_by(desc(ChangeControlVersion.version))
    ).all()
    current = next(row for row in versions if row.version == case.current_version)
    lines = _recalculate(db, current)
    decision = (
        db.scalar(
            select(CustomerDecisionRequest).where(
                CustomerDecisionRequest.decision_id == current.customer_decision_id
            )
        )
        if current.customer_decision_id
        else None
    )
    response = (
        db.scalar(
            select(CustomerDecisionResponse).where(
                CustomerDecisionResponse.decision_id_fk == decision.id
            )
        )
        if decision
        else None
    )
    documents = db.scalars(
        select(WorkspaceDocument)
        .where(
            WorkspaceDocument.project_id == case.project_id,
            WorkspaceDocument.source_system == "change-control",
        )
        .order_by(desc(WorkspaceDocument.created_at))
    ).all()
    return {
        "case": case,
        "current": current,
        "versions": versions,
        "lines": lines,
        "decision": decision,
        "response": response,
        "documents": [
            row
            for row in documents
            if json.loads(row.metadata_json or "{}").get("change_id") == change_id
        ],
        "policy": change_control_workspace(db)["policy"],
    }


def ensure_change_documents(
    db: Session, change_id: str, user: object
) -> list[WorkspaceDocument]:
    _role, email = _require(
        user,
        EDIT_ROLES | FINANCE_ROLES | LEADERSHIP_ROLES | {"legal"},
    )
    case = _case(db, change_id)
    version = _version(db, change_id)
    if version.status == "draft" or not version.content_sha256:
        raise ValueError("Piszkozatból nem készíthető végleges ChangeControl dokumentum.")
    before_artifacts = {
        row.document_id: json.loads(row.metadata_json or "{}").get("artifact_sha256")
        for row in db.scalars(
            select(WorkspaceDocument).where(
                WorkspaceDocument.project_id == case.project_id,
                WorkspaceDocument.source_system == "change-control",
            )
        ).all()
    }
    documents = [
        _document_snapshot(
            db,
            case,
            version,
            title_prefix=(
                "Belső változtatási lap"
                if version.status in {"internal_review", "internal_rejected"}
                else "Belső jóváhagyott változtatási lap"
            ),
            owner=email,
        )
    ]
    if version.status in {
        "customer_review",
        "customer_accepted",
        "customer_rejected",
        "work_authorized",
        "completed",
    }:
        documents.append(
            _document_snapshot(
                db,
                case,
                version,
                title_prefix="Ügyfélcsomag",
                owner=email,
            )
        )
    after_artifacts = {
        row.document_id: json.loads(row.metadata_json or "{}").get("artifact_sha256")
        for row in documents
    }
    if any(before_artifacts.get(key) != value for key, value in after_artifacts.items()):
        audit(
            db,
            actor=email,
            action="change_documents_verified",
            entity_type="change_control",
            entity_id=change_id,
            after={"version": version.version, "document_ids": list(after_artifacts)},
        )
    db.commit()
    return documents


def create_change_case(
    db: Session,
    user: object,
    *,
    project_id: str,
    title: str,
    change_type: str,
    reason: str,
    technical_scope: str,
    exclusions: str,
    assumptions: str,
    deadline_impact_days: int,
    vat_rate: object,
    customer_advance_net: object,
    responsible: str,
) -> ChangeControlCase:
    _role, email = _require(user, EDIT_ROLES)
    project_id, title, change_type = (
        project_id.strip(),
        title.strip(),
        change_type.strip().lower(),
    )
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)):
        raise ValueError("A ChangeControl ügyhöz kanonikus ProjectID szükséges.")
    if change_type not in {"scope", "design", "quantity", "site_condition", "customer_request"}:
        raise ValueError("Ismeretlen változtatástípus.")
    if not title or not responsible.strip():
        raise ValueError("A cím és a felelős kötelező.")
    change_id = f"CHG-{uuid4().hex[:12].upper()}"
    vat = _decimal(vat_rate)
    if vat > 100:
        raise ValueError("Az áfakulcs legfeljebb 100% lehet.")
    case = ChangeControlCase(
        change_id=change_id,
        project_id=project_id,
        title=title,
        change_type=change_type,
        responsible=responsible.strip(),
        created_by=email,
    )
    db.add(case)
    db.flush()
    version = ChangeControlVersion(
        version_id=f"{change_id}-V1",
        change_id_fk=case.id,
        version=1,
        reason=reason.strip(),
        technical_scope=technical_scope.strip(),
        exclusions=exclusions.strip(),
        assumptions=assumptions.strip(),
        deadline_impact_days=deadline_impact_days,
        vat_rate=vat,
        customer_advance_net=_decimal(customer_advance_net),
        created_by=email,
    )
    db.add(version)
    audit(
        db,
        actor=email,
        action="change_case_created",
        entity_type="change_control",
        entity_id=change_id,
        after={"project_id": project_id, "version": 1, "change_type": change_type},
    )
    db.commit()
    db.refresh(case)
    return case


def update_change_draft(
    db: Session,
    change_id: str,
    user: object,
    *,
    reason: str,
    technical_scope: str,
    exclusions: str,
    assumptions: str,
    deadline_impact_days: int,
    vat_rate: object,
    customer_advance_net: object,
) -> ChangeControlVersion:
    _role, email = _require(user, EDIT_ROLES)
    version = _version(db, change_id)
    if version.status != "draft":
        raise ValueError("Csak piszkozat ChangeControl-verzió módosítható.")
    vat = _decimal(vat_rate)
    if vat > 100:
        raise ValueError("Az áfakulcs legfeljebb 100% lehet.")
    version.reason = reason.strip()
    version.technical_scope = technical_scope.strip()
    version.exclusions = exclusions.strip()
    version.assumptions = assumptions.strip()
    version.deadline_impact_days = deadline_impact_days
    version.vat_rate = vat
    version.customer_advance_net = _decimal(customer_advance_net)
    _recalculate(db, version)
    audit(
        db,
        actor=email,
        action="change_draft_updated",
        entity_type="change_control",
        entity_id=change_id,
        after={"version": version.version},
    )
    db.commit()
    db.refresh(version)
    return version


def add_change_line(
    db: Session,
    change_id: str,
    user: object,
    *,
    category: str,
    description: str,
    quantity: object,
    unit: str,
    unit_cost_net: object,
    unit_sale_net: object,
    early_direct_cost: bool,
) -> ChangeControlLine:
    _role, email = _require(user, EDIT_ROLES)
    version = _version(db, change_id)
    if version.status != "draft":
        raise ValueError("Beküldött verzió nem módosítható; készítsen új verziót.")
    quantity_value = _decimal(quantity, quantity=True)
    cost = _decimal(unit_cost_net)
    sale = _decimal(unit_sale_net)
    if not category.strip() or not description.strip() or not unit.strip():
        raise ValueError("A tételkategória, leírás és mértékegység kötelező.")
    row = ChangeControlLine(
        line_id=f"CHG-LINE-{uuid4().hex[:12].upper()}",
        version_id_fk=version.id,
        category=category.strip(),
        description=description.strip(),
        quantity=quantity_value,
        unit=unit.strip(),
        unit_cost_net=cost,
        unit_sale_net=sale,
        total_cost_net=(quantity_value * cost).quantize(Decimal("0.01")),
        total_sale_net=(quantity_value * sale).quantize(Decimal("0.01")),
        early_direct_cost=early_direct_cost,
    )
    db.add(row)
    db.flush()
    _recalculate(db, version)
    audit(
        db,
        actor=email,
        action="change_line_added",
        entity_type="change_control",
        entity_id=change_id,
        after={"line_id": row.line_id, "total_sale_net": str(row.total_sale_net)},
    )
    db.commit()
    db.refresh(row)
    return row


def delete_change_line(
    db: Session, change_id: str, line_id: str, user: object
) -> ChangeControlVersion:
    _role, email = _require(user, EDIT_ROLES)
    version = _version(db, change_id)
    if version.status != "draft":
        raise ValueError("Csak piszkozat ChangeControl-tétel törölhető.")
    row = db.scalar(
        select(ChangeControlLine).where(
            ChangeControlLine.version_id_fk == version.id,
            ChangeControlLine.line_id == line_id,
        )
    )
    if not row:
        raise KeyError(line_id)
    db.delete(row)
    db.flush()
    _recalculate(db, version)
    audit(
        db,
        actor=email,
        action="change_line_deleted",
        entity_type="change_control",
        entity_id=change_id,
        before={"line_id": line_id},
    )
    db.commit()
    db.refresh(version)
    return version


def submit_change(db: Session, change_id: str, user: object) -> ChangeControlVersion:
    _role, email = _require(user, EDIT_ROLES)
    case = _case(db, change_id)
    version = _version(db, change_id)
    if version.status != "draft":
        raise ValueError("Csak piszkozat verzió indítható belső ellenőrzésre.")
    lines = _recalculate(db, version)
    if not lines:
        raise ValueError("Legalább egy tételes műszaki-pénzügyi sor kötelező.")
    if (
        min(
            len(version.reason.strip()),
            len(version.technical_scope.strip()),
            len(version.exclusions.strip()),
            len(version.assumptions.strip()),
        )
        < 10
    ):
        raise ValueError("Az indok, scope, kizárás és feltételezés részletes kitöltése kötelező.")
    if version.margin_percent < MINIMUM_MARGIN_PERCENT:
        raise ValueError("35% alatti fedezetnél a változtatás nem küldhető ki.")
    if version.customer_advance_net < version.early_direct_cost_net:
        raise ValueError("Az ügyfélelőleg nem lehet kisebb a korai közvetlen költségnél.")
    snapshot = _snapshot(version, lines)
    version.content_sha256 = _hash_snapshot(snapshot)
    version.status = "internal_review"
    case.status = "internal_review"
    _document_snapshot(db, case, version, title_prefix="Belső változtatási lap", owner=email)
    db.add(
        TaskRecord(
            task_id=f"TASK-CHG-TECH-{uuid4().hex[:10].upper()}",
            project_id=case.project_id,
            source_event_id=version.version_id,
            title=f"Műszaki ChangeControl-jóváhagyás: {case.title}",
            description=f"{change_id} v{version.version}; hash {version.content_sha256}",
            assignee="technical-prep@imperial.local",
            priority="high",
            status="open",
        )
    )
    audit(
        db,
        actor=email,
        action="change_submitted",
        entity_type="change_control",
        entity_id=change_id,
        after={"version": version.version, "content_sha256": version.content_sha256},
    )
    db.commit()
    db.refresh(version)
    return version


def review_change(
    db: Session,
    change_id: str,
    user: object,
    *,
    gate: str,
    decision: str,
    note: str,
) -> ChangeControlVersion:
    roles = {
        "technical": TECHNICAL_ROLES,
        "finance": FINANCE_ROLES,
        "leadership": LEADERSHIP_ROLES,
    }
    if gate not in roles:
        raise ValueError("Ismeretlen ChangeControl jóváhagyási kapu.")
    _role, email = _require(user, roles[gate])
    case = _case(db, change_id)
    version = _version(db, change_id)
    if version.status != "internal_review":
        raise ValueError("Csak belső ellenőrzés alatt álló verzió bírálható.")
    if decision not in {"approve", "reject"} or len(note.strip()) < 15:
        raise ValueError("Érvényes döntés és legalább 15 karakteres indoklás kötelező.")
    if email == version.created_by.lower():
        raise ValueError("A készítő a saját ChangeControl-verzióját nem hagyhatja jóvá.")
    if gate == "finance" and not version.technical_approved_by:
        raise ValueError("Pénzügyi döntés előtt műszaki jóváhagyás szükséges.")
    if gate == "leadership" and not version.finance_approved_by:
        raise ValueError("Vezetői döntés előtt pénzügyi jóváhagyás szükséges.")
    if gate == "leadership" and not version.leadership_required:
        raise ValueError("Ez a verzió nem igényel külön vezetői jóváhagyást.")
    previous_approvers = {
        version.technical_approved_by,
        version.finance_approved_by,
    } - {None}
    if decision == "approve" and email in {item.lower() for item in previous_approvers if item is not None}:
        raise ValueError("A kötelező jóváhagyási kapukat külön személyeknek kell lezárniuk.")
    if decision == "reject":
        version.status = "internal_rejected"
        case.status = "internal_rejected"
        setattr(version, f"{gate}_approval_note", note.strip())
        audit(
            db,
            actor=email,
            action=f"change_{gate}_rejected",
            entity_type="change_control",
            entity_id=change_id,
            after={"version": version.version, "note": note.strip()},
        )
        db.commit()
        db.refresh(version)
        return version
    now = datetime.now(UTC)
    setattr(version, f"{gate}_approved_by", email)
    setattr(version, f"{gate}_approval_note", note.strip())
    setattr(version, f"{gate}_approved_at", now)
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.project_id == case.project_id,
            TaskRecord.source_event_id == version.version_id,
            TaskRecord.status != "done",
        )
    ).all():
        task.status = "done"
    next_gate = None
    if gate == "technical":
        next_gate = "finance"
        assignee = "finance@imperial.local"
    elif gate == "finance" and version.leadership_required:
        next_gate = "leadership"
        assignee = "managing-director@imperial.local"
    else:
        assignee = ""
    if next_gate:
        db.add(
            TaskRecord(
                task_id=f"TASK-CHG-{next_gate.upper()}-{uuid4().hex[:10].upper()}",
                project_id=case.project_id,
                source_event_id=version.version_id,
                title=f"{next_gate.title()} ChangeControl-jóváhagyás: {case.title}",
                description=(
                    f"{change_id} v{version.version}; változatlan hash {version.content_sha256}"
                ),
                assignee=assignee,
                priority="high",
                status="open",
                executive_relevance=next_gate == "leadership",
            )
        )
    final_internal = gate == "leadership" or (gate == "finance" and not version.leadership_required)
    if final_internal:
        version.status = "customer_review"
        case.status = "customer_review"
        _document_snapshot(
            db,
            case,
            version,
            title_prefix="Belső jóváhagyott változtatási lap",
            owner=email,
        )
        _document_snapshot(db, case, version, title_prefix="Ügyfélcsomag", owner=email)
        decision_actor = (
            user
            if _identity(user)[0]
            in {"owner", "managing-director", "platform-admin", "project-manager"}
            else SimpleNamespace(role="project-manager", email=email)
        )
        decision_request = create_decision_request(
            db,
            case.project_id,
            decision_actor,
            title=f"Pótmunka / változtatás elfogadása: {case.title}",
            description=(
                f"{change_id} v{version.version}; nettó {version.sale_net} HUF, "
                f"bruttó {version.sale_gross} HUF, határidőhatás "
                f"{version.deadline_impact_days} nap. Dokumentumhash: {version.content_sha256}."
            ),
            options=[CUSTOMER_ACCEPT_OPTION, CUSTOMER_REJECT_OPTION],
            due_at=None,
            source_module="change-control",
            source_object_id=change_id,
            source_version=version.version,
        )
        version.customer_decision_id = decision_request.decision_id
    audit(
        db,
        actor=email,
        action=f"change_{gate}_approved",
        entity_type="change_control",
        entity_id=change_id,
        after={"version": version.version, "final_internal": final_internal},
    )
    db.commit()
    db.refresh(version)
    return version


def create_change_revision(
    db: Session,
    change_id: str,
    user: object,
    *,
    reason: str,
) -> ChangeControlVersion:
    _role, email = _require(user, EDIT_ROLES)
    case = _case(db, change_id)
    previous = _version(db, change_id)
    if previous.status in {"draft", "work_authorized", "completed"}:
        raise ValueError("Ebben az állapotban nem nyitható új ChangeControl-verzió.")
    if len(reason.strip()) < 15:
        raise ValueError("Az új verzió indoklása legalább 15 karakteres legyen.")
    previous_lines = _lines(db, previous)
    previous.status = "superseded"
    version_number = previous.version + 1
    row = ChangeControlVersion(
        version_id=f"{change_id}-V{version_number}",
        change_id_fk=case.id,
        version=version_number,
        reason=reason.strip(),
        technical_scope=previous.technical_scope,
        exclusions=previous.exclusions,
        assumptions=previous.assumptions,
        deadline_impact_days=previous.deadline_impact_days,
        vat_rate=previous.vat_rate,
        customer_advance_net=previous.customer_advance_net,
        created_by=email,
    )
    db.add(row)
    db.flush()
    for source in previous_lines:
        db.add(
            ChangeControlLine(
                line_id=f"CHG-LINE-{uuid4().hex[:12].upper()}",
                version_id_fk=row.id,
                category=source.category,
                description=source.description,
                quantity=source.quantity,
                unit=source.unit,
                unit_cost_net=source.unit_cost_net,
                unit_sale_net=source.unit_sale_net,
                total_cost_net=source.total_cost_net,
                total_sale_net=source.total_sale_net,
                early_direct_cost=source.early_direct_cost,
            )
        )
    case.current_version = version_number
    case.status = "draft"
    audit(
        db,
        actor=email,
        action="change_revision_created",
        entity_type="change_control",
        entity_id=change_id,
        before={"version": previous.version},
        after={"version": version_number, "approvals_reset": True},
    )
    db.commit()
    db.refresh(row)
    return row


def sync_customer_decision(db: Session, change_id: str, user: object) -> ChangeControlVersion:
    _role, email = _require(user, WORK_AUTH_ROLES | FINANCE_ROLES | LEADERSHIP_ROLES)
    case = _case(db, change_id)
    version = _version(db, change_id)
    if version.status not in {"customer_review", "customer_accepted", "customer_rejected"}:
        raise ValueError("A változtatás nincs ügyféldöntési állapotban.")
    decision = db.scalar(
        select(CustomerDecisionRequest).where(
            CustomerDecisionRequest.decision_id == version.customer_decision_id
        )
    )
    response = (
        db.scalar(
            select(CustomerDecisionResponse).where(
                CustomerDecisionResponse.decision_id_fk == decision.id
            )
        )
        if decision
        else None
    )
    if not response:
        raise ValueError("Az ügyfél még nem rögzítette a döntését a MyImperialban.")
    if response.selected_option == CUSTOMER_ACCEPT_OPTION:
        version.status = "customer_accepted"
        case.status = "approved"
        event_status = "customer_accepted"
    else:
        version.status = "customer_rejected"
        case.status = "customer_rejected"
        event_status = "rejected"
    audit(
        db,
        actor=email,
        action="change_customer_decision_synchronized",
        entity_type="change_control",
        entity_id=change_id,
        after={
            "version": version.version,
            "customer_email": response.customer_email,
            "selected_option": response.selected_option,
        },
    )
    db.commit()
    ingest_change_control_event(
        db,
        ChangeControlEventIn(
            change_id=change_id,
            project_id=case.project_id,
            status=event_status,
            version=version.version,
            summary=f"Ügyféldöntés rögzítve: {response.selected_option}",
            net_revenue_huf=version.sale_net,
            net_cost_huf=version.cost_net,
            deadline_impact_days=version.deadline_impact_days,
            customer_decision=response.selected_option,
            source_url=f"change-control://{change_id}/versions/{version.version}",
        ),
        actor=email,
    )
    db.refresh(version)
    return version


def authorize_change_work(
    db: Session,
    change_id: str,
    user: object,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> ChangeControlVersion:
    _role, email = _require(user, WORK_AUTH_ROLES)
    case = _case(db, change_id)
    version = _version(db, change_id)
    if version.status == "customer_review":
        version = sync_customer_decision(db, change_id, user)
    if version.status != "customer_accepted":
        raise ValueError("Ügyfél-elfogadás nélkül munkakezdési engedély nem adható ki.")
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=UTC)
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=UTC)
    if ends_at <= starts_at:
        raise ValueError("A munkavégzés vége csak a kezdés után lehet.")
    calendar = CalendarEntry(
        entry_id=f"CAL-CHG-{uuid4().hex[:10].upper()}",
        project_id=case.project_id,
        entry_type="milestone",
        title=f"Jóváhagyott változtatás: {case.title}",
        description=f"{change_id} v{version.version}; munkakezdési engedély kiadva.",
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=False,
        assignee=case.responsible,
        participants_json="[]",
        status="confirmed",
        priority="high",
        source_module="change-control",
        source_object_id=version.version_id,
        contractual_deadline=version.deadline_impact_days != 0,
        capacity_hours=Decimal("0"),
        created_by=email,
        updated_by=email,
    )
    db.add(calendar)
    db.flush()
    version.status = "work_authorized"
    version.work_authorized_by = email
    version.work_authorized_at = datetime.now(UTC)
    version.calendar_entry_id = calendar.entry_id
    case.status = "work_authorized"
    db.add(
        TaskRecord(
            task_id=f"TASK-CHG-WORK-{uuid4().hex[:10].upper()}",
            project_id=case.project_id,
            source_event_id=version.version_id,
            title=f"Jóváhagyott változtatás végrehajtása: {case.title}",
            description=f"Munkakezdési engedély: {change_id} v{version.version}",
            assignee=case.responsible,
            due_at=ends_at,
            priority="high",
            status="open",
        )
    )
    audit(
        db,
        actor=email,
        action="change_work_authorized",
        entity_type="change_control",
        entity_id=change_id,
        after={"version": version.version, "calendar_entry_id": calendar.entry_id},
    )
    db.commit()
    ingest_change_control_event(
        db,
        ChangeControlEventIn(
            change_id=change_id,
            project_id=case.project_id,
            status="work_authorized",
            version=version.version,
            summary=f"Munkakezdési engedély kiadva: {case.title}",
            net_revenue_huf=version.sale_net,
            net_cost_huf=version.cost_net,
            deadline_impact_days=version.deadline_impact_days,
            customer_decision=CUSTOMER_ACCEPT_OPTION,
            source_url=f"change-control://{change_id}/versions/{version.version}",
        ),
        actor=email,
    )
    db.refresh(version)
    return version


def complete_change(
    db: Session,
    change_id: str,
    user: object,
    *,
    evidence_url: str,
    note: str,
) -> ChangeControlVersion:
    _role, email = _require(user, WORK_AUTH_ROLES)
    case = _case(db, change_id)
    version = _version(db, change_id)
    if version.status != "work_authorized":
        raise ValueError("Csak munkakezdési engedéllyel rendelkező változtatás zárható le.")
    if not evidence_url.strip() or len(note.strip()) < 15:
        raise ValueError("Teljesítési bizonyíték és legalább 15 karakteres lezárási jegyzet kell.")
    version.status = "completed"
    version.completion_evidence_url = evidence_url.strip()
    version.completed_by = email
    version.completed_at = datetime.now(UTC)
    case.status = "completed"
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.project_id == case.project_id,
            TaskRecord.source_event_id == version.version_id,
            TaskRecord.status != "done",
        )
    ).all():
        task.status = "done"
    if version.calendar_entry_id:
        calendar = db.scalar(
            select(CalendarEntry).where(CalendarEntry.entry_id == version.calendar_entry_id)
        )
        if calendar:
            calendar.status = "done"
            calendar.updated_by = email
    audit(
        db,
        actor=email,
        action="change_completed",
        entity_type="change_control",
        entity_id=change_id,
        after={"version": version.version, "evidence_url": evidence_url, "note": note},
    )
    db.commit()
    ingest_change_control_event(
        db,
        ChangeControlEventIn(
            change_id=change_id,
            project_id=case.project_id,
            status="completed",
            version=version.version,
            summary=f"Változtatás dokumentáltan lezárva: {case.title}. {note.strip()}",
            net_revenue_huf=version.sale_net,
            net_cost_huf=version.cost_net,
            deadline_impact_days=version.deadline_impact_days,
            customer_decision=CUSTOMER_ACCEPT_OPTION,
            source_url=evidence_url.strip(),
        ),
        actor=email,
    )
    db.refresh(version)
    return version
