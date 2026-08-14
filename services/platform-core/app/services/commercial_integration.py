from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from integrations.contract_generator_v0_4.imperial_contract_generator.core import (
    GENERATOR_VERSION,
    ContractValidationError,
    ValidationIssue,
    generate_package,
    validate_contract,
)

from ..audit import audit
from ..models import (
    EventRecord,
    PartnerChangeNotice,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
    WorkspaceDocument,
)
from ..schemas import ChangeControlEventIn, EventIn
from .integration import ingest_event

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_CONTRACT_ROOT = PROJECT_ROOT / "integrations" / "contract_generator_v0_4"
CANONICAL_CONTRACT_ZIP = PROJECT_ROOT / "integrations" / "source_artifacts" / "Imperial_Contract_Generator_v0.4.zip"
CONTRACT_OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "contract_packages"
EXPECTED_CONTRACT_ZIP_SHA256 = "3634378bbc90f885b54e787f6de06e57cabf4d6a594e1351463388814e191a42"
CONTRACT_DRIVE_FILE_ID = "1kL92i1Z8Zk5V_1W4wmTbJB0pRAVVhSHV"
CONTRACT_DRIVE_URL = f"https://drive.google.com/file/d/{CONTRACT_DRIVE_FILE_ID}/view"
CONTRACT_TEMPLATE_REGISTRY_DRIVE_FILE_ID = "1S7M2hfQY1mjqxTBUx8vlRl9h5pZ3Coz0oyrQs21DJow"
CONTRACT_TEMPLATE_FOLDER_DRIVE_ID = "19HDyanu46lVbfC7Ki2zSqz9m0SEKgyGz"
CONTRACT_EXAMPLES = {
    "customer_type_house_design_build": "customer_type_house_design_build_valid.json",
    "customer_construction": "customer_construction_valid.json",
    "customer_design_execution_plans": "customer_design_execution_plans_valid.json",
    "subcontractor_design": "subcontractor_design_valid.json",
    "subcontractor_execution": "subcontractor_execution_valid.json",
}
CONTRACT_TYPE_LABELS = {
    "customer_type_house_design_build": "Ügyfél · típusház tervezés és kivitelezés",
    "customer_construction": "Ügyfél · kivitelezés",
    "customer_design_execution_plans": "Ügyfél · kiviteli tervezés",
    "subcontractor_design": "Alvállalkozó · tervezés",
    "subcontractor_execution": "Alvállalkozó · kivitelezés",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "contract"


def resolve_contract_artifact(document: WorkspaceDocument) -> Path:
    metadata = json.loads(document.metadata_json or "{}")
    raw_path = str(metadata.get("local_path") or "").strip()
    if not raw_path:
        raise FileNotFoundError(document.document_id)
    root = CONTRACT_OUTPUT_ROOT.resolve()
    path = Path(raw_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError(document.document_id)
    expected_sha256 = str(metadata.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ContractValidationError("A szerződésartifact SHA-256 bizonyítéka hiányzik.")
    if sha256_file(path) != expected_sha256:
        raise ContractValidationError("A szerződésartifact sérült; a letöltés blokkolva.")
    return path


def _contract_example(contract_type: str) -> dict[str, Any]:
    file_name = CONTRACT_EXAMPLES.get(contract_type)
    if not file_name:
        raise ContractValidationError("Ismeretlen szerződéstípus.")
    path = CANONICAL_CONTRACT_ROOT / "examples" / file_name
    return json.loads(path.read_text(encoding="utf-8"))


def contract_intake_options() -> list[dict[str, str]]:
    return [
        {"value": key, "label": label}
        for key, label in CONTRACT_TYPE_LABELS.items()
    ]


def _text(form: Mapping[str, Any], key: str) -> str:
    return str(form.get(key) or "").strip()


def _table_rows(
    value: str,
    *,
    columns: tuple[str, ...],
    label: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(value.splitlines(), 1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != len(columns) or any(not part for part in parts):
            raise ContractValidationError(
                f"{label}: a(z) {line_number}. sor {len(columns)} kitöltött, "
                "| jellel elválasztott mezőt igényel."
            )
        rows.append(dict(zip(columns, parts, strict=True)))
    if not rows:
        raise ContractValidationError(f"{label}: legalább egy sor kötelező.")
    return rows


def contract_form_values(payload: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {
        "contract_type": str(payload.get("contract_type") or ""),
        "contract_number": str(payload.get("contract_number") or ""),
        "contract_date": str(payload.get("contract_date") or ""),
        "contract_place": str(payload.get("contract_place") or ""),
    }
    for prefix in ("ids", "internal_entity", "counterparty", "project", "schedule"):
        for key, value in payload.get(prefix, {}).items():
            if not isinstance(value, (dict, list)):
                values[f"{prefix}.{key}"] = str(value or "")
    commercial = payload.get("commercial", {})
    for key in ("net_price", "vat_percent", "currency"):
        values[f"commercial.{key}"] = str(commercial.get(key) or "")
    values["payment_schedule"] = "\n".join(
        f"{row.get('milestone', '')}|{row.get('percent', '')}|{row.get('due_rule', '')}"
        for row in commercial.get("payment_schedule", [])
    )
    values["attachments"] = "\n".join(
        f"{row.get('type', '')}|{row.get('version', '')}|"
        f"{row.get('file_id') or row.get('source_url') or ''}"
        for row in payload.get("attachments", [])
    )
    milestones = payload.get("schedule", {}).get("milestones", [])
    values["schedule.milestones"] = "\n".join(
        f"{row.get('name', '')}|{row.get('deadline', '')}" for row in milestones
    )
    insurance = payload.get("designer_controls", {}).get(
        "professional_liability_insurance", {}
    )
    for key in ("insurer", "policy_number", "coverage_amount"):
        values[f"designer.{key}"] = str(insurance.get(key) or "")
    values["workflow.project_manager_email"] = str(
        payload.get("workflow", {}).get("project_manager_email") or ""
    )
    return values


def blank_contract_form_values(contract_type: str) -> dict[str, str]:
    example = _contract_example(contract_type)
    values = {key: "" for key in contract_form_values(example)}
    values.update(
        {
            "contract_type": contract_type,
            "contract_date": date.today().isoformat(),
            "contract_place": "Budapest",
            "counterparty.party_type": (
                "company" if contract_type.startswith("subcontractor_") else "natural_person"
            ),
            "internal_entity.party_type": "company",
            "commercial.currency": "HUF",
            "payment_schedule": "Szerződéskötés|100|jóváhagyott számla alapján",
            "attachments": "\n".join(
                f"{attachment_type}|1.0|"
                for attachment_type in example["required_attachments"]
            ),
        }
    )
    return values


def build_contract_intake_payload(form: Mapping[str, Any]) -> dict[str, Any]:
    contract_type = _text(form, "contract_type")
    example = _contract_example(contract_type)
    relationship = "partner" if contract_type.startswith("subcontractor_") else "customer"
    if contract_type == "customer_type_house_design_build":
        service = "design_build"
    elif contract_type in {"customer_design_execution_plans", "subcontractor_design"}:
        service = "design"
    else:
        service = "construction"

    def party(prefix: str) -> dict[str, str]:
        return {
            key: _text(form, f"{prefix}.{key}")
            for key in (
                "party_type",
                "name",
                "short_name",
                "registration_number",
                "tax_number",
                "registered_office",
                "address",
                "postal_address",
                "bank_account",
                "representative",
                "representative_title",
                "email",
                "phone",
                "birth_place",
                "birth_date",
                "mother_name",
                "identity_document_type",
                "identity_document_number",
            )
        }

    payment_rows = _table_rows(
        _text(form, "payment_schedule"),
        columns=("milestone", "percent", "due_rule"),
        label="Fizetési ütemezés",
    )
    attachment_rows = _table_rows(
        _text(form, "attachments"),
        columns=("type", "version", "file_id"),
        label="Mellékletjegyzék",
    )
    required_attachments = list(example["required_attachments"])
    supplied = {row["type"] for row in attachment_rows}
    missing = sorted(set(required_attachments) - supplied)
    if missing:
        raise ContractValidationError(
            "Hiányzó kötelező melléklet-bizonyíték: " + ", ".join(missing)
        )
    net_price = _text(form, "commercial.net_price")
    vat_percent = _text(form, "commercial.vat_percent")
    try:
        net = Decimal(net_price)
        vat_rate = Decimal(vat_percent)
    except Exception as exc:
        raise ContractValidationError("A nettó ár és az áfakulcs számként kötelező.") from exc
    vat_amount = (net * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
    gross_price = net + vat_amount
    schedule: dict[str, Any] = {
        "start_date": _text(form, "schedule.start_date"),
        "deadline": _text(form, "schedule.deadline"),
    }
    site_handover = _text(form, "schedule.site_handover_date")
    if site_handover:
        schedule["site_handover_date"] = site_handover
    milestone_text = _text(form, "schedule.milestones")
    if contract_type == "subcontractor_design":
        schedule["milestones"] = _table_rows(
            milestone_text,
            columns=("name", "deadline"),
            label="Tervezési mérföldkövek",
        )

    payload: dict[str, Any] = {
        "contract_type": contract_type,
        "relationship": relationship,
        "service": service,
        "contract_number": _text(form, "contract_number"),
        "contract_date": _text(form, "contract_date"),
        "contract_place": _text(form, "contract_place"),
        "ids": {
            key: _text(form, f"ids.{key}")
            for key in ("CompanyID", "PersonID", "OpportunityID", "ProjectID", "PartnerID")
        },
        "internal_entity": party("internal_entity"),
        "counterparty": party("counterparty"),
        "project": {
            key: _text(form, f"project.{key}")
            for key in (
                "name",
                "site_address",
                "parcel_number",
                "scope",
                "gross_floor_area_m2",
                "procedure_type",
            )
        },
        "commercial": {
            "net_price": str(net),
            "vat_percent": str(vat_rate),
            "vat_amount": str(vat_amount),
            "gross_price": str(gross_price),
            "currency": _text(form, "commercial.currency") or "HUF",
            "payment_schedule": payment_rows,
        },
        "schedule": schedule,
        "delivery_requirements": deepcopy(example["delivery_requirements"]),
        "required_attachments": required_attachments,
        "attachments": [
            {**row, "status": "APPROVED"} for row in attachment_rows
        ],
        "status": {
            "contract_status": "DRAFT",
            "signed_contract_present": False,
            "master_hash_verified": True,
            "all_required_annexes_present": True,
            "commercial_approval": "PENDING",
            "technical_approval": "PENDING",
            "all_fields_complete": True,
            "both_parties_signed": False,
            "signed_contract_file_id": "",
            "owner_policy_version": "ICG-PAY-2026-07-18",
        },
        "dispatch_status": {
            "internal_signed_original_present": False,
            "internal_signature_date": "",
            "signed_document_sha256": "",
            "postal": {
                "sent": False,
                "sent_at": "",
                "recipient_address": party("counterparty")["postal_address"],
                "original_copy_count": 0,
                "tracking_number": "",
                "proof_file_id": "",
            },
            "electronic": {
                "sent": False,
                "sent_at": "",
                "recipient_email": party("counterparty")["email"],
                "message_id": "",
                "attachment_sha256": "",
            },
        },
        "workflow": {
            "project_manager_email": _text(form, "workflow.project_manager_email")
        },
    }
    if contract_type == "customer_type_house_design_build":
        payload["type_house"] = True
    if contract_type == "customer_design_execution_plans":
        payload["execution_plans"] = True
    if contract_type == "subcontractor_design":
        payload["designer_controls"] = {
            "professional_liability_insurance": {
                "insurer": _text(form, "designer.insurer"),
                "policy_number": _text(form, "designer.policy_number"),
                "coverage_amount": _text(form, "designer.coverage_amount"),
            }
        }
        payload["invoice_controls"] = deepcopy(example["invoice_controls"])
    if contract_type == "subcontractor_execution":
        payload["subcontractor_controls"] = deepcopy(example["subcontractor_controls"])
    return payload


def _due_at(value: str | None, fallback_days: int) -> datetime:
    if value:
        try:
            return datetime.combine(date.fromisoformat(value), time(hour=16), tzinfo=timezone.utc)
        except ValueError:
            pass
    return utcnow() + timedelta(days=fallback_days)


def _ensure_contract_workflow_tasks(
    db: Session,
    *,
    payload: dict[str, Any],
    event_id: str,
) -> list[str]:
    """Persist approval, delivery and start gates as actionable calendar cards."""
    project_id = str(payload["ids"]["ProjectID"])
    contract_number = str(payload["contract_number"])
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    preferred = str(payload.get("workflow", {}).get("project_manager_email") or (project.responsible if project else "") or "").strip()
    assignee = preferred if "@" in preferred else None
    schedule = payload.get("schedule", {})
    steps: list[tuple[str, str, str, datetime, str]] = [
        ("legal-review", "01 · Jogi és tartalmi ellenőrzés", "A betűhív minta, változó mezők, mellékletek és SHA-256 manifest ellenőrzése.", _due_at(None, 1), "high"),
        ("signature", "02 · Belső jóváhagyás és aláírás", "A jóváhagyási kapu lezárása és a cégszerűen aláírt példány visszamentése.", _due_at(None, 2), "high"),
        ("dual-delivery", "03 · Kettős kézbesítés igazolása", "Eredeti és elektronikus példány kiküldése; tracking, MessageID és hash rögzítése.", _due_at(None, 3), "high"),
        ("work-start", "04 · Projektindítási kapu", "Az aláírt szerződés, kötelező mellékletek és kézbesítési bizonyítékok ellenőrzése.", _due_at(schedule.get("start_date"), 5), "high"),
        ("final-deadline", "05 · Szerződéses véghatáridő", "A végső teljesítési határidő és függőségeinek naptári követése.", _due_at(schedule.get("deadline"), 30), "normal"),
    ]
    for index, milestone in enumerate(schedule.get("milestones", []), 1):
        name = str(milestone.get("name") or f"Mérföldkő {index}")
        steps.append((f"milestone-{index}", f"Mérföldkő · {name}", "Szerződéses mérföldkő teljesítése, bizonyíték és jóváhagyás rögzítése.", _due_at(milestone.get("deadline"), 7 + index), "normal"))
    if payload.get("contract_type") in {"subcontractor_design", "subcontractor_execution"}:
        steps.append(("invoice-gate", "06 · Teljesítésigazolási és számlakapu", "TIG, szerződés-, projekt- és számlaadatok egyezőségének ellenőrzése befogadás előtt.", _due_at(schedule.get("deadline"), 30), "high"))

    task_ids: list[str] = []
    for key, title, description, due_at, priority in steps:
        digest = hashlib.sha256(f"{project_id}:{contract_number}:{key}".encode("utf-8")).hexdigest()[:16].upper()
        task_id = f"TASK-CON-{digest}"
        task_ids.append(task_id)
        if db.scalar(select(TaskRecord).where(TaskRecord.task_id == task_id)):
            continue
        db.add(TaskRecord(
            task_id=task_id, project_id=project_id, source_event_id=event_id,
            title=f"{title} · {contract_number}", description=description,
            assignee=assignee, due_at=due_at, priority=priority, status="open",
            executive_relevance=priority == "high",
        ))
    db.commit()
    return task_ids


def contract_source_status() -> dict[str, Any]:
    registry = CANONICAL_CONTRACT_ROOT / "config" / "templates.json"
    template_dir = CANONICAL_CONTRACT_ROOT / "master_templates"
    issues: list[str] = []
    actual_zip_sha = sha256_file(CANONICAL_CONTRACT_ZIP) if CANONICAL_CONTRACT_ZIP.exists() else None
    archive_verified = actual_zip_sha == EXPECTED_CONTRACT_ZIP_SHA256
    if actual_zip_sha is not None and not archive_verified:
        issues.append("A kanonikus Contract Generator ZIP SHA-256 lenyomata eltér.")
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except Exception as exc:
        data = {}
        issues.append(f"A templates.json nem olvasható: {exc}")
    template_checks: list[dict[str, Any]] = []
    for contract_type, entry in data.items():
        path = template_dir / entry["file_name"]
        actual = sha256_file(path) if path.exists() else None
        ok = actual == entry.get("sha256")
        if not ok:
            issues.append(f"Sablonhash eltérés: {contract_type}")
        template_checks.append({
            "contract_type": contract_type,
            "template_id": entry.get("template_id"),
            "file_name": entry.get("file_name"),
            "drive_file_id": entry.get("drive_file_id"),
            "expected_sha256": entry.get("sha256"),
            "actual_sha256": actual,
            "ok": ok,
        })
    return {
        "module_key": "contract_generator",
        "version": GENERATOR_VERSION,
        "canonical_source": True,
        "template_registry_drive_file_id": CONTRACT_TEMPLATE_REGISTRY_DRIVE_FILE_ID,
        "template_folder_drive_id": CONTRACT_TEMPLATE_FOLDER_DRIVE_ID,
        "drive_file_id": CONTRACT_DRIVE_FILE_ID,
        "drive_url": CONTRACT_DRIVE_URL,
        "zip_expected_sha256": EXPECTED_CONTRACT_ZIP_SHA256,
        "zip_actual_sha256": actual_zip_sha,
        "archive_present": CANONICAL_CONTRACT_ZIP.exists(),
        "archive_verified": archive_verified,
        "provenance_mode": "verified_archive" if archive_verified else "verified_source_tree",
        "templates": template_checks,
        "healthy": not issues,
        "issues": issues,
    }


def validate_contract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    issues = validate_contract(payload)
    for index, attachment in enumerate(payload.get("attachments", []), 1):
        if not str(attachment.get("file_id") or attachment.get("source_url") or "").strip():
            issues.append(
                ValidationIssue(
                    "ATTACHMENT_EVIDENCE_MISSING",
                    f"A(z) {index}. melléklethez Drive- vagy dokumentumbizonyíték kötelező.",
                )
            )
    return {
        "valid": not any(i.blocking for i in issues),
        "issues": [i.as_dict() for i in issues],
        "source": contract_source_status(),
    }


def _register_workspace_document(
    db: Session,
    *,
    project_id: str,
    title: str,
    category: str,
    local_path: Path,
    contract_number: str,
    sha256: str,
    mime_type: str,
    actor: str,
) -> WorkspaceDocument:
    doc_id = f"DOC-{uuid.uuid4().hex[:12].upper()}"
    row = WorkspaceDocument(
        document_id=doc_id,
        project_id=project_id,
        title=title,
        category=category,
        source_system="contract_generator",
        source_url=f"file://{local_path}",
        mime_type=mime_type,
        version_label=GENERATOR_VERSION,
        approval_status="draft",
        verification_status="sha256_verified",
        confidentiality="confidential",
        owner="Jogi / operáció",
        extracted_summary=f"Contract Generator v{GENERATOR_VERSION}; szerződésszám: {contract_number}; SHA-256: {sha256}",
        metadata_json=json.dumps({
            "canonical_module_key": "contract_generator",
            "contract_number": contract_number,
            "generator_version": GENERATOR_VERSION,
            "sha256": sha256,
            "local_path": str(local_path),
            "canonical_source_drive_file_id": CONTRACT_DRIVE_FILE_ID,
        }, ensure_ascii=False),
    )
    db.add(row)
    audit(db, actor=actor, action="commercial.document.register", entity_type="workspace_document", entity_id=doc_id,
          after={"project_id": project_id, "contract_number": contract_number, "sha256": sha256})
    return row


def generate_contract_package(db: Session, payload: dict[str, Any], *, actor: str = "api") -> dict[str, Any]:
    source = contract_source_status()
    if not source["healthy"]:
        raise ContractValidationError("A kanonikus Contract Generator forrásellenőrzése sikertelen: " + " | ".join(source["issues"]))
    validation = validate_contract_payload(payload)
    if not validation["valid"]:
        raise ContractValidationError(" | ".join(i["message"] for i in validation["issues"] if i.get("blocking")))
    project_id = str(payload.get("ids", {}).get("ProjectID") or "").strip()
    if not project_id:
        raise ContractValidationError("ProjectID kötelező.")
    contract_number = str(payload.get("contract_number") or "").strip()
    output_dir = CONTRACT_OUTPUT_ROOT / safe_name(project_id) / safe_name(contract_number)
    if output_dir.exists():
        # Ugyanaz a szerződés nem generálható csendben újra; a verziószám a forrásmodul feladata.
        raise ContractValidationError("Ehhez a ContractID/szerződésszámhoz már létezik generált csomag. Új verziót a Contract Generatorban kell létrehozni.")
    result = generate_package(
        payload,
        CANONICAL_CONTRACT_ROOT / "config" / "templates.json",
        CANONICAL_CONTRACT_ROOT / "master_templates",
        output_dir,
    )
    manifest = result["manifest"]
    zip_path = Path(result["zip_path"])
    zip_sha = sha256_file(zip_path)
    manifest_path = output_dir / "manifest.json"
    manifest_sha = sha256_file(manifest_path)
    package_document = _register_workspace_document(
        db, project_id=project_id, title=f"Szerződéscsomag – {contract_number}", category="contract_package",
        local_path=zip_path, contract_number=contract_number, sha256=zip_sha, mime_type="application/zip", actor=actor,
    )
    manifest_document = _register_workspace_document(
        db, project_id=project_id, title=f"Szerződésmanifest – {contract_number}", category="contract_manifest",
        local_path=manifest_path, contract_number=contract_number, sha256=manifest_sha, mime_type="application/json", actor=actor,
    )
    from .contract_workflow import create_contract_workflow

    contract_workflow = create_contract_workflow(
        db,
        payload=payload,
        package_document_id=package_document.document_id,
        manifest_document_id=manifest_document.document_id,
        actor=actor,
    )
    event = EventIn(
        event_id=f"EVT-CONTRACT-{uuid.uuid4().hex[:12].upper()}",
        dedupe_key=f"CONTRACT_PACKAGE_GENERATED:{project_id}:{contract_number}:{GENERATOR_VERSION}",
        project_id=project_id,
        source_module="contract_generator",
        event_type="CONTRACT_PACKAGE_GENERATED",
        object_type="Contract",
        object_id=contract_number,
        severity="info",
        status=manifest.get("signing_queue_status", "READY_FOR_APPROVAL").lower(),
        responsible="Jogi / operáció",
        next_action="A generált szerződéscsomag ellenőrzése és aláírási jóváhagyása.",
        evidence_url=f"file://{zip_path}",
        payload={
            "summary": f"A {contract_number} szerződéscsomag a kanonikus Contract Generator v{GENERATOR_VERSION} motorral elkészült.",
            "contract_number": contract_number,
            "contract_type": payload.get("contract_type"),
            "signing_queue_status": manifest.get("signing_queue_status"),
            "zip_sha256": zip_sha,
            "canonical_source_sha256": EXPECTED_CONTRACT_ZIP_SHA256,
            "canonical_source_drive_file_id": CONTRACT_DRIVE_FILE_ID,
            "duplicate_business_engine_created": False,
            "workflow_checklist_enabled": True,
        },
        route_to=["crm", "myimperial"],
    )
    record, _created = ingest_event(db, event, actor=actor)
    workflow_task_ids = _ensure_contract_workflow_tasks(db, payload=payload, event_id=record.event_id)
    return {
        "event_id": record.event_id,
        "project_id": project_id,
        "contract_number": contract_number,
        "contract_id": contract_workflow.contract_id,
        "zip_path": str(zip_path),
        "zip_sha256": zip_sha,
        "manifest": manifest,
        "canonical_source": source,
        "workflow_task_ids": workflow_task_ids,
    }


def ingest_contract_signed(db: Session, *, project_id: str, contract_number: str, evidence_url: str | None, actor: str) -> EventRecord:
    event = EventIn(
        event_id=f"EVT-CONTRACT-SIGNED-{uuid.uuid4().hex[:10].upper()}",
        dedupe_key=f"CONTRACT_SIGNED:{project_id}:{contract_number}",
        project_id=project_id,
        source_module="contract_generator",
        event_type="CONTRACT_SIGNED",
        object_type="Contract",
        object_id=contract_number,
        status="signed",
        responsible="Projektindítás",
        evidence_url=evidence_url,
        payload={"summary": f"A {contract_number} szerződés mindkét fél által aláírt és kézbesítési bizonyítékkal rendelkezik."},
    )
    record, _ = ingest_event(db, event, actor=actor)
    return record


def ingest_change_control_event(db: Session, data: ChangeControlEventIn, *, actor: str = "api") -> EventRecord:
    status_map = {
        "approved": "CHANGE_APPROVED",
        "customer_accepted": "CHANGE_CUSTOMER_ACCEPTED",
        "work_authorized": "CHANGE_WORK_AUTHORIZED",
        "completed": "CHANGE_COMPLETED",
        "rejected": "CHANGE_REJECTED",
    }
    event_type = status_map.get(data.status, "CHANGE_STATUS_UPDATED")
    margin = Decimal("0")
    if data.net_revenue_huf:
        margin = (data.net_revenue_huf - data.net_cost_huf) / data.net_revenue_huf
    event = EventIn(
        event_id=f"EVT-CHANGE-{uuid.uuid4().hex[:12].upper()}",
        dedupe_key=f"CHANGE_CONTROL:{data.change_id}:V{data.version}:{data.status}",
        project_id=data.project_id,
        source_module="change_control",
        event_type=event_type,
        object_type="Change",
        object_id=data.change_id,
        status=data.status,
        severity="high" if data.status in {"rejected", "blocked"} else "info",
        financial_impact_huf=data.net_revenue_huf,
        deadline_impact_days=data.deadline_impact_days,
        responsible="Projektvezetés / ChangeControl",
        next_action="A ChangeControl forrásmodulban szükséges következő lépés végrehajtása.",
        evidence_url=data.source_url,
        payload={
            "summary": data.summary,
            "version": data.version,
            "net_revenue_huf": str(data.net_revenue_huf),
            "net_cost_huf": str(data.net_cost_huf),
            "margin_ratio": str(margin),
            "customer_decision": data.customer_decision,
            "source_module_is_authoritative": True,
            "workspace_is_projection_only": True,
        },
    )
    record, _ = ingest_event(db, event, actor=actor)
    return record


def commercial_workspace(db: Session, project_id: str | None = None) -> dict[str, Any]:
    from .contract_workflow import list_contract_workflows

    contract_q = select(ProjectObjectState).where(ProjectObjectState.source_module == "contract_generator")
    change_q = select(ProjectObjectState).where(ProjectObjectState.source_module == "change_control")
    notice_q = select(PartnerChangeNotice)
    if project_id:
        contract_q = contract_q.where(ProjectObjectState.project_id == project_id)
        change_q = change_q.where(ProjectObjectState.project_id == project_id)
        notice_q = notice_q.where(PartnerChangeNotice.project_id == project_id)
    contracts = db.scalars(contract_q.order_by(desc(ProjectObjectState.updated_at))).all()
    changes = db.scalars(change_q.order_by(desc(ProjectObjectState.updated_at))).all()
    notices = db.scalars(notice_q.order_by(desc(PartnerChangeNotice.created_at)).limit(100)).all()
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return {
        "contracts": contracts,
        "contract_workflows": list_contract_workflows(db, project_id=project_id),
        "changes": changes,
        "partner_change_notices": notices,
        "projects": projects,
        "contract_source": contract_source_status(),
        "rules": {
            "contract_generator_owner": "contract_generator",
            "change_control_owner": "change_control",
            "workspace_role": "projection_and_orchestration_only",
            "duplicate_engine_prohibited": True,
        },
    }
