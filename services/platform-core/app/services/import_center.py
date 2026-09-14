from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    EnterpriseCanonicalRecord,
    ImportCommitBatch,
    ImportDataSource,
    ImportItem,
    ImportJob,
    ProjectFact,
    ProjectRegistry,
    StagedEnterpriseRecord,
)
from ..schemas import ImportItemIn, ImportJobIn, ImportReviewIn, ImportSourceIn


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:18]}"


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_tax_number(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) in {8, 11}:
        return digits
    return digits or None


def normalize_email(value: Any) -> str | None:
    text = normalize_text(value)
    return text if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text) else None


DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "finance": (
        "invoice", "számla", "amount", "összeg", "gross", "bruttó", "net", "nettó", "due_date",
        "esedékesség", "payment", "fizetés", "bank", "cashflow", "cash-flow", "profit", "margin", "fedezet",
    ),
    "project": (
        "project_id", "projektazonosító", "projekt", "helyszín", "address", "cím", "deadline", "határidő",
        "construction", "kivitelezés", "status", "státusz", "milestone", "mérföldkő",
    ),
    "partner": (
        "company_name", "cégnév", "tax_number", "adószám", "contact", "kapcsolattartó", "email", "telefon",
        "supplier", "beszállító", "subcontractor", "alvállalkozó",
    ),
    "customer": ("customer", "ügyfél", "lead", "érdeklődő", "megrendelő"),
    "procurement": ("tender", "rfq", "ajánlatkérés", "work_package", "munkacsomag", "bid", "ajánlat"),
    "contract": ("contract", "szerződés", "contract_number", "szerződésszám"),
    "product_data": ("brand", "márka", "technology", "technológia", "price", "ár", "package", "csomag"),
    "document": ("document", "dokumentum", "file", "fájl"),
}

TARGET_MODULE_BY_DOMAIN = {
    "finance": "finance",
    "project": "project_control",
    "partner": "partner_connect",
    "customer": "crm",
    "procurement": "procurement",
    "contract": "contract_generator",
    "product_data": "buildconfig",
    "document": "control_center",
}

ENTITY_TYPE_BY_DOMAIN = {
    "finance": "financial_record",
    "project": "project",
    "partner": "company",
    "customer": "customer",
    "procurement": "procurement_record",
    "contract": "contract",
    "product_data": "product_price_record",
    "document": "document_fact",
}

COMMON_ALIASES = {
    "cégnév": "company_name",
    "cegnev": "company_name",
    "vállalkozás": "company_name",
    "vallalkozas": "company_name",
    "adószám": "tax_number",
    "adoszam": "tax_number",
    "kapcsolattartó": "contact_name",
    "kapcsolattarto": "contact_name",
    "telefon": "phone",
    "e-mail": "email",
    "email cím": "email",
    "projektazonosító": "project_id",
    "projekt azonosító": "project_id",
    "projekt": "project_name",
    "helyszín": "address",
    "cím": "address",
    "számlaszám": "invoice_number",
    "számla sorszáma": "invoice_number",
    "nettó": "net_amount",
    "bruttó": "gross_amount",
    "áfa": "vat_amount",
    "esedékesség": "due_date",
    "szerződésszám": "contract_number",
    "munkacsomag": "work_package",
    "technológia": "technology",
    "márka": "brand",
    "alapterület": "gross_area_m2",
}


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, value in record.items():
        key = normalize_text(raw_key).replace(" ", "_")
        key = COMMON_ALIASES.get(normalize_text(raw_key), key)
        if isinstance(value, str):
            value = value.strip()
        if key == "tax_number":
            value = normalize_tax_number(value)
        elif key == "email":
            value = normalize_email(value) or value
        result[key] = value
    return result


def classify_domain(record: dict[str, Any], text: str = "", hint: str | None = None) -> str:
    if hint and hint not in {"enterprise", "auto", "mixed"}:
        return hint
    haystack = " ".join([" ".join(record.keys()), " ".join(str(v) for v in record.values()), text]).lower()
    scores: dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        scores[domain] = sum(1 for kw in keywords if kw in haystack)
    winner = max(scores, key=lambda domain: scores[domain])
    return winner if scores[winner] > 0 else "document"


def infer_entity_type(domain: str, record: dict[str, Any]) -> str:
    if domain == "finance":
        if "invoice_number" in record or "számlaszám" in record:
            return "supplier_invoice"
        if "payment_date" in record or "paid" in record:
            return "payment"
        if "budget" in record or "forecast" in record:
            return "financial_plan"
    if domain == "project" and ("milestone" in record or "deadline" in record):
        return "project_milestone"
    if domain == "partner" and ("contact_name" in record and not record.get("company_name")):
        return "contact"
    if domain == "procurement" and ("tender" in record or "work_package" in record):
        return "tender"
    return ENTITY_TYPE_BY_DOMAIN.get(domain, "enterprise_record")


def infer_project_id(record: dict[str, Any], text: str = "") -> str | None:
    for key in ("project_id", "project_code", "projekt_id", "ügyazonosító", "ugyazonosito"):
        if record.get(key):
            return str(record[key]).strip()
    match = re.search(r"\b(?:IMP|PROJ|PRJ)-[A-Z0-9_-]{3,30}\b", text, re.IGNORECASE)
    return match.group(0).upper() if match else None


def infer_external_key(domain: str, entity_type: str, record: dict[str, Any], project_id: str | None) -> str | None:
    priority_keys = {
        "supplier_invoice": ("invoice_number", "számlaszám", "id"),
        "payment": ("payment_id", "transaction_id", "id"),
        "project": ("project_id", "project_code", "id"),
        "project_milestone": ("milestone_id", "id"),
        "company": ("tax_number", "company_id", "email", "id"),
        "contact": ("email", "phone", "id"),
        "customer": ("email", "phone", "customer_id", "id"),
        "contract": ("contract_number", "id"),
        "tender": ("tender_id", "rfq_id", "id"),
        "product_price_record": ("source_key", "brand", "technology", "id"),
    }
    for key in priority_keys.get(entity_type, ("external_id", "id")):
        value = record.get(key)
        if value not in (None, ""):
            if key == "tax_number":
                value = normalize_tax_number(value)
            return f"{domain}:{entity_type}:{value}"
    if project_id and entity_type != "project":
        name = record.get("name") or record.get("title") or record.get("milestone")
        if name:
            return f"{domain}:{entity_type}:{project_id}:{normalize_text(name)}"
    return None


def infer_name(record: dict[str, Any], domain: str, entity_type: str) -> str | None:
    keys = (
        "canonical_name", "company_name", "project_name", "customer_name", "contact_name", "name", "title",
        "invoice_number", "contract_number", "work_package", "technology",
    )
    for key in keys:
        if record.get(key) not in (None, ""):
            return str(record[key]).strip()
    return f"{domain} / {entity_type}"


def confidence_score(record: dict[str, Any], domain: str, entity_type: str, external_key: str | None) -> Decimal:
    populated = sum(1 for v in record.values() if v not in (None, "", [], {}))
    score = Decimal("0.45") + min(Decimal(populated) * Decimal("0.035"), Decimal("0.28"))
    if external_key:
        score += Decimal("0.12")
    if domain != "document":
        score += Decimal("0.06")
    if entity_type in {"supplier_invoice", "project", "company", "contract", "tender"}:
        score += Decimal("0.04")
    return min(score, Decimal("0.99"))


def validation_result(record: dict[str, Any], domain: str, entity_type: str, external_key: str | None) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    if not external_key:
        warnings.append("Nincs stabil üzleti azonosító; emberi felülvizsgálat szükséges.")
    if domain == "finance":
        if not any(k in record for k in ("gross_amount", "net_amount", "amount", "összeg")):
            warnings.append("Pénzügyi rekord összeg nélkül.")
        if entity_type == "supplier_invoice" and not record.get("invoice_number"):
            errors.append("Számlarekord számlaszám nélkül.")
    if domain == "partner" and not any(record.get(k) for k in ("tax_number", "email", "phone", "company_name")):
        errors.append("Partnerrekord azonosítható cég- vagy kapcsolati adat nélkül.")
    return {"valid": not errors, "warnings": warnings, "errors": errors}


def create_source(db: Session, data: ImportSourceIn) -> ImportDataSource:
    row = db.scalar(select(ImportDataSource).where(ImportDataSource.source_key == data.source_key))
    if row:
        row.name = data.name
        row.source_type = data.source_type
        row.domain_scope = data.domain_scope
        row.connector_reference = data.connector_reference
        row.query_or_path = data.query_or_path
        row.sync_mode = data.sync_mode
        row.owner = data.owner
        row.enabled = data.enabled
        row.settings_json = dumps(data.settings)
    else:
        row = ImportDataSource(
            source_key=data.source_key,
            name=data.name,
            source_type=data.source_type,
            domain_scope=data.domain_scope,
            connector_reference=data.connector_reference,
            query_or_path=data.query_or_path,
            sync_mode=data.sync_mode,
            owner=data.owner,
            enabled=data.enabled,
            settings_json=dumps(data.settings),
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_job(db: Session, data: ImportJobIn) -> ImportJob:
    if not db.scalar(select(ImportDataSource).where(ImportDataSource.source_key == data.source_key)):
        raise ValueError("Ismeretlen importforrás.")
    row = ImportJob(
        job_id=new_id("JOB"),
        source_key=data.source_key,
        name=data.name,
        status="created",
        requested_by=data.requested_by,
        domain_hint=data.domain_hint,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_item(db: Session, job_id: str, data: ImportItemIn) -> ImportItem:
    job = db.scalar(select(ImportJob).where(ImportJob.job_id == job_id))
    if not job:
        raise ValueError("Importfutás nem található.")
    row = ImportItem(
        item_id=new_id("ITEM"),
        job_id=job_id,
        external_id=data.external_id,
        file_name=data.file_name,
        mime_type=data.mime_type,
        source_url=data.source_url,
        sha256=data.sha256,
        domain_hint=data.domain_hint,
        content_json=dumps(data.content),
    )
    db.add(row)
    job.items_total += 1
    if job.status == "created":
        job.status = "received"
    db.commit()
    db.refresh(row)
    return row


def _records_from_text(text: str) -> list[dict[str, Any]]:
    record: dict[str, Any] = {"text_excerpt": text[:4000]}
    emails = sorted(set(re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.IGNORECASE)))
    phones = sorted(set(re.findall(r"(?:\+36|06)[\s-]?(?:20|30|31|50|70)[\s-]?\d{3}[\s-]?\d{4}", text)))
    tax_numbers = sorted(set(re.findall(r"\b\d{8}-\d-\d{2}\b", text)))
    invoice_numbers = sorted(set(re.findall(r"\b(?:INV|SZLA|SZÁMLA)[-/A-Z0-9]{3,30}\b", text, re.IGNORECASE)))
    if emails:
        record["email"] = emails[0]
        record["all_emails"] = emails
    if phones:
        record["phone"] = phones[0]
        record["all_phones"] = phones
    if tax_numbers:
        record["tax_number"] = tax_numbers[0]
    if invoice_numbers:
        record["invoice_number"] = invoice_numbers[0]
    project_id = infer_project_id({}, text)
    if project_id:
        record["project_id"] = project_id
    return [record]


def extract_item(db: Session, item: ImportItem, job: ImportJob) -> list[StagedEnterpriseRecord]:
    content = loads(item.content_json, {})
    source_records: list[dict[str, Any]] = []
    text = str(content.get("text") or "")
    if isinstance(content.get("records"), list):
        source_records.extend(r for r in content["records"] if isinstance(r, dict))
    if isinstance(content.get("rows"), list):
        source_records.extend(r for r in content["rows"] if isinstance(r, dict))
    if not source_records and text:
        source_records.extend(_records_from_text(text))
    if not source_records and content:
        source_records.append({k: v for k, v in content.items() if k not in {"metadata"}})

    staged_rows: list[StagedEnterpriseRecord] = []
    for raw in source_records:
        normalized = normalize_record(raw)
        domain = classify_domain(normalized, text=text, hint=item.domain_hint or job.domain_hint)
        entity_type = infer_entity_type(domain, normalized)
        project_id = infer_project_id(normalized, text)
        external_key = infer_external_key(domain, entity_type, normalized, project_id)
        canonical_name = infer_name(normalized, domain, entity_type)
        confidence = confidence_score(normalized, domain, entity_type, external_key)
        validation = validation_result(normalized, domain, entity_type, external_key)
        duplicate = None
        if external_key:
            duplicate = db.scalar(
                select(EnterpriseCanonicalRecord).where(
                    EnterpriseCanonicalRecord.domain == domain,
                    EnterpriseCanonicalRecord.entity_type == entity_type,
                    EnterpriseCanonicalRecord.external_key == external_key,
                )
            )
        review_status = "ready" if validation["valid"] and confidence >= Decimal("0.90") else "pending"
        row = StagedEnterpriseRecord(
            staged_id=new_id("STG"),
            job_id=job.job_id,
            item_id=item.item_id,
            domain=domain,
            entity_type=entity_type,
            external_key=external_key,
            canonical_name=canonical_name,
            project_id=project_id,
            target_module=TARGET_MODULE_BY_DOMAIN.get(domain, "control_center"),
            confidence=confidence,
            review_status=review_status,
            duplicate_status="exact" if duplicate else "new",
            duplicate_record_id=duplicate.record_id if duplicate else None,
            payload_json=dumps(raw),
            normalized_json=dumps(normalized),
            provenance_json=dumps({
                "source_key": job.source_key,
                "job_id": job.job_id,
                "item_id": item.item_id,
                "external_id": item.external_id,
                "file_name": item.file_name,
                "source_url": item.source_url,
                "sha256": item.sha256,
                "extraction": "deterministic_fallback_or_connector_payload",
            }),
            validation_json=dumps(validation),
        )
        db.add(row)
        staged_rows.append(row)
    item.status = "processed"
    item.processed_at = utcnow()
    job.items_processed += 1
    return staged_rows


def process_job(db: Session, job_id: str) -> ImportJob:
    job = db.scalar(select(ImportJob).where(ImportJob.job_id == job_id))
    if not job:
        raise ValueError("Importfutás nem található.")
    job.status = "processing"
    job.started_at = job.started_at or utcnow()
    items = db.scalars(select(ImportItem).where(ImportItem.job_id == job_id, ImportItem.status == "received")).all()
    for item in items:
        try:
            extract_item(db, item, job)
        except Exception as exc:  # isolated item failure; job may continue
            item.status = "error"
            item.error_message = str(exc)
            job.error_count += 1
            job.items_processed += 1
    db.flush()
    staged = db.scalars(select(StagedEnterpriseRecord).where(StagedEnterpriseRecord.job_id == job_id)).all()
    job.records_extracted = len(staged)
    job.records_review_required = sum(1 for r in staged if r.review_status == "pending")
    job.status = "review" if staged else ("error" if job.error_count else "empty")
    job.completed_at = utcnow()
    job.summary_json = dumps({
        "domains": _count_by(staged, lambda x: x.domain),
        "entity_types": _count_by(staged, lambda x: x.entity_type),
        "duplicates": _count_by(staged, lambda x: x.duplicate_status),
    })
    source = db.scalar(select(ImportDataSource).where(ImportDataSource.source_key == job.source_key))
    if source:
        source.last_sync_at = utcnow()
    db.commit()
    db.refresh(job)
    return job


def _count_by(rows: Iterable[Any], key_fn) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(key_fn(row))
        result[key] = result.get(key, 0) + 1
    return result


def review_record(db: Session, staged_id: str, data: ImportReviewIn) -> StagedEnterpriseRecord:
    row = db.scalar(select(StagedEnterpriseRecord).where(StagedEnterpriseRecord.staged_id == staged_id))
    if not row:
        raise ValueError("Előkészített rekord nem található.")
    if data.review_status not in {"approved", "rejected", "pending", "ready"}:
        raise ValueError("Érvénytelen felülvizsgálati státusz.")
    row.review_status = data.review_status
    if data.canonical_name is not None:
        row.canonical_name = data.canonical_name
    if data.target_module is not None:
        row.target_module = data.target_module
    if data.project_id is not None:
        row.project_id = data.project_id
    if data.normalized is not None:
        row.normalized_json = dumps(data.normalized)
    db.commit()
    db.refresh(row)
    return row


def _upsert_project_registry(db: Session, staged: StagedEnterpriseRecord, normalized: dict[str, Any]) -> None:
    if not staged.project_id:
        return
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == staged.project_id))
    if not project:
        project = ProjectRegistry(
            project_id=staged.project_id,
            name=str(normalized.get("project_name") or staged.canonical_name or staged.project_id),
            customer_name=normalized.get("customer_name"),
            project_type=normalized.get("project_type"),
            status=str(normalized.get("status") or "imported"),
            responsible=normalized.get("responsible"),
            next_action=normalized.get("next_action"),
        )
        db.add(project)
    else:
        if normalized.get("project_name"):
            project.name = str(normalized["project_name"])
        if normalized.get("customer_name"):
            project.customer_name = str(normalized["customer_name"])
        if normalized.get("status"):
            project.status = str(normalized["status"])


def _upsert_project_fact(db: Session, staged: StagedEnterpriseRecord, normalized: dict[str, Any]) -> None:
    if not staged.project_id:
        return
    fact_key = f"legacy_import.{staged.domain}.{staged.entity_type}.{staged.external_key or staged.staged_id}"
    fact = db.scalar(select(ProjectFact).where(
        ProjectFact.project_id == staged.project_id,
        ProjectFact.source_module == "import_center",
        ProjectFact.fact_key == fact_key,
    ))
    if not fact:
        fact = ProjectFact(
            project_id=staged.project_id,
            source_module="import_center",
            fact_key=fact_key,
            value_json=dumps(normalized),
        )
        db.add(fact)
    else:
        fact.value_json = dumps(normalized)


def commit_records(db: Session, job_id: str, staged_ids: list[str], actor: str | None, auto_approve_high_confidence: bool = False) -> ImportCommitBatch:
    job = db.scalar(select(ImportJob).where(ImportJob.job_id == job_id))
    if not job:
        raise ValueError("Importfutás nem található.")
    query = select(StagedEnterpriseRecord).where(StagedEnterpriseRecord.job_id == job_id)
    if staged_ids:
        query = query.where(StagedEnterpriseRecord.staged_id.in_(staged_ids))
    rows = db.scalars(query).all()
    eligible: list[StagedEnterpriseRecord] = []
    for row in rows:
        validation = loads(row.validation_json, {})
        approved = row.review_status == "approved"
        auto = auto_approve_high_confidence and row.review_status == "ready" and Decimal(row.confidence) >= Decimal("0.93")
        if (approved or auto) and validation.get("valid", False):
            eligible.append(row)
    if not eligible:
        raise ValueError("Nincs jóváhagyott, érvényes rekord a commit művelethez.")

    changes: list[dict[str, Any]] = []
    for staged in eligible:
        normalized = loads(staged.normalized_json, {})
        canonical = None
        if staged.external_key:
            canonical = db.scalar(select(EnterpriseCanonicalRecord).where(
                EnterpriseCanonicalRecord.domain == staged.domain,
                EnterpriseCanonicalRecord.entity_type == staged.entity_type,
                EnterpriseCanonicalRecord.external_key == staged.external_key,
            ))
        created = canonical is None
        if canonical is None:
            canonical = EnterpriseCanonicalRecord(
                record_id=new_id("REC"),
                domain=staged.domain,
                entity_type=staged.entity_type,
                external_key=staged.external_key,
                canonical_name=staged.canonical_name,
                project_id=staged.project_id,
                target_module=staged.target_module,
                data_json=staged.normalized_json,
                provenance_json=staged.provenance_json,
                source_job_id=job_id,
            )
            db.add(canonical)
            db.flush()
            before = None
        else:
            before = {
                "canonical_name": canonical.canonical_name,
                "project_id": canonical.project_id,
                "target_module": canonical.target_module,
                "status": canonical.status,
                "data_json": canonical.data_json,
                "provenance_json": canonical.provenance_json,
                "source_job_id": canonical.source_job_id,
            }
            canonical.canonical_name = staged.canonical_name
            canonical.project_id = staged.project_id
            canonical.target_module = staged.target_module
            canonical.status = "active"
            canonical.data_json = staged.normalized_json
            canonical.provenance_json = staged.provenance_json
            canonical.source_job_id = job_id
        project_change = None
        fact_change = None
        if staged.project_id:
            project_before = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == staged.project_id))
            project_change = {
                "project_id": staged.project_id,
                "created": project_before is None,
                "before": None if project_before is None else {
                    "name": project_before.name, "customer_name": project_before.customer_name,
                    "project_type": project_before.project_type, "status": project_before.status,
                    "risk_level": project_before.risk_level, "blocked": project_before.blocked,
                    "financial_impact_huf": str(project_before.financial_impact_huf),
                    "deadline_impact_days": project_before.deadline_impact_days,
                    "responsible": project_before.responsible, "next_action": project_before.next_action,
                },
            }
            fact_key = f"legacy_import.{staged.domain}.{staged.entity_type}.{staged.external_key or staged.staged_id}"
            fact_before = db.scalar(select(ProjectFact).where(
                ProjectFact.project_id == staged.project_id,
                ProjectFact.source_module == "import_center",
                ProjectFact.fact_key == fact_key,
            ))
            fact_change = {
                "project_id": staged.project_id, "fact_key": fact_key, "created": fact_before is None,
                "before_value_json": None if fact_before is None else fact_before.value_json,
            }
        staged.committed_record_id = canonical.record_id
        staged.review_status = "committed"
        _upsert_project_registry(db, staged, normalized)
        _upsert_project_fact(db, staged, normalized)
        changes.append({
            "record_id": canonical.record_id, "created": created, "before": before,
            "project_change": project_change, "fact_change": fact_change,
        })

    batch = ImportCommitBatch(
        batch_id=new_id("BATCH"),
        job_id=job_id,
        status="committed",
        actor=actor,
        committed_count=len(changes),
        record_ids_json=dumps(changes),
    )
    db.add(batch)
    job.records_committed += len(changes)
    job.status = "committed" if job.records_committed >= job.records_extracted - job.records_rejected else "partially_committed"
    db.commit()
    db.refresh(batch)
    return batch


def rollback_batch(db: Session, batch_id: str, actor: str | None = None) -> ImportCommitBatch:
    batch = db.scalar(select(ImportCommitBatch).where(ImportCommitBatch.batch_id == batch_id))
    if not batch:
        raise ValueError("Commit csomag nem található.")
    if batch.status == "rolled_back":
        return batch
    changes = loads(batch.record_ids_json, [])
    rolled_back = 0
    for change in reversed(changes):
        canonical = db.scalar(select(EnterpriseCanonicalRecord).where(EnterpriseCanonicalRecord.record_id == change["record_id"]))
        if canonical:
            if change.get("created"):
                db.execute(delete(EnterpriseCanonicalRecord).where(EnterpriseCanonicalRecord.record_id == canonical.record_id))
            else:
                before = change.get("before") or {}
                canonical.canonical_name = before.get("canonical_name")
                canonical.project_id = before.get("project_id")
                canonical.target_module = before.get("target_module") or canonical.target_module
                canonical.status = before.get("status") or "active"
                canonical.data_json = before.get("data_json") or "{}"
                canonical.provenance_json = before.get("provenance_json") or "{}"
                canonical.source_job_id = before.get("source_job_id")
        fact_change = change.get("fact_change") or {}
        if fact_change.get("project_id") and fact_change.get("fact_key"):
            fact = db.scalar(select(ProjectFact).where(
                ProjectFact.project_id == fact_change["project_id"],
                ProjectFact.source_module == "import_center",
                ProjectFact.fact_key == fact_change["fact_key"],
            ))
            if fact_change.get("created") and fact:
                db.delete(fact)
            elif fact and fact_change.get("before_value_json") is not None:
                fact.value_json = fact_change["before_value_json"]
        project_change = change.get("project_change") or {}
        if project_change.get("project_id"):
            project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_change["project_id"]))
            if project_change.get("created") and project:
                remaining = db.scalar(select(EnterpriseCanonicalRecord.id).where(EnterpriseCanonicalRecord.project_id == project.project_id).limit(1))
                if not remaining:
                    db.delete(project)
            elif project:
                before_project = project_change.get("before") or {}
                for field in ("name", "customer_name", "project_type", "status", "risk_level", "blocked", "deadline_impact_days", "responsible", "next_action"):
                    if field in before_project:
                        setattr(project, field, before_project[field])
                if "financial_impact_huf" in before_project:
                    project.financial_impact_huf = Decimal(before_project["financial_impact_huf"])
        rolled_back += 1
    staged = db.scalars(select(StagedEnterpriseRecord).where(
        StagedEnterpriseRecord.job_id == batch.job_id,
        StagedEnterpriseRecord.committed_record_id.in_([c["record_id"] for c in changes]),
    )).all()
    for row in staged:
        row.review_status = "approved"
        row.committed_record_id = None
    job = db.scalar(select(ImportJob).where(ImportJob.job_id == batch.job_id))
    if job:
        job.records_committed = max(0, job.records_committed - rolled_back)
        job.status = "review"
    batch.status = "rolled_back"
    batch.rollback_count = rolled_back
    batch.actor = actor or batch.actor
    batch.rolled_back_at = utcnow()
    db.commit()
    db.refresh(batch)
    return batch


def import_metrics(db: Session) -> dict[str, Any]:
    sources = db.scalars(select(ImportDataSource)).all()
    jobs = db.scalars(select(ImportJob)).all()
    staged = db.scalars(select(StagedEnterpriseRecord)).all()
    canonical = db.scalars(select(EnterpriseCanonicalRecord)).all()
    return {
        "sources": len(sources),
        "enabled_sources": sum(1 for s in sources if s.enabled),
        "jobs": len(jobs),
        "jobs_in_review": sum(1 for j in jobs if j.status == "review"),
        "staged": len(staged),
        "pending_review": sum(1 for r in staged if r.review_status == "pending"),
        "ready": sum(1 for r in staged if r.review_status == "ready"),
        "committed_records": len(canonical),
        "domains": _count_by(canonical, lambda x: x.domain),
    }
