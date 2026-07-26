from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from integrations.contract_generator_v0_4.imperial_contract_generator.core import (
    GENERATOR_VERSION,
    ContractValidationError,
    generate_package,
    validate_contract,
)

from ..audit import audit
from ..models import EventRecord, PartnerChangeNotice, ProjectObjectState, ProjectRegistry, WorkspaceDocument
from ..schemas import ChangeControlEventIn, EventIn
from .integration import ingest_event

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_CONTRACT_ROOT = PROJECT_ROOT / "integrations" / "contract_generator_v0_4"
CANONICAL_CONTRACT_ZIP = PROJECT_ROOT / "integrations" / "source_artifacts" / "Imperial_Contract_Generator_v0.4.zip"
CONTRACT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "contract_packages"
EXPECTED_CONTRACT_ZIP_SHA256 = "3634378bbc90f885b54e787f6de06e57cabf4d6a594e1351463388814e191a42"
CONTRACT_DRIVE_FILE_ID = "1kL92i1Z8Zk5V_1W4wmTbJB0pRAVVhSHV"
CONTRACT_DRIVE_URL = f"https://drive.google.com/file/d/{CONTRACT_DRIVE_FILE_ID}/view"


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
    _register_workspace_document(
        db, project_id=project_id, title=f"Szerződéscsomag – {contract_number}", category="contract_package",
        local_path=zip_path, contract_number=contract_number, sha256=zip_sha, mime_type="application/zip", actor=actor,
    )
    _register_workspace_document(
        db, project_id=project_id, title=f"Szerződésmanifest – {contract_number}", category="contract_manifest",
        local_path=manifest_path, contract_number=contract_number, sha256=manifest_sha, mime_type="application/json", actor=actor,
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
        },
        route_to=["crm", "myimperial"],
    )
    record, _created = ingest_event(db, event, actor=actor)
    return {
        "event_id": record.event_id,
        "project_id": project_id,
        "contract_number": contract_number,
        "zip_path": str(zip_path),
        "zip_sha256": zip_sha,
        "manifest": manifest,
        "canonical_source": source,
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
