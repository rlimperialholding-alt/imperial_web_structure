from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..config import settings
from ..models import (
    ModuleBusinessApproval,
    ModuleBusinessComment,
    ModuleBusinessRecord,
)
from ..schemas import EventIn, ModuleBusinessRecordIn, ModuleBusinessRecordUpdateIn
from .crm_transport import crm_service_headers
from .integration import ingest_event

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "platform_demo_seed.json"
COMMON_STATUSES = (
    "draft",
    "new",
    "in_progress",
    "in_review",
    "approved",
    "active",
    "blocked",
    "completed",
    "rejected",
    "archived",
)

SOURCE_RECORD_TYPES: dict[str, set[str]] = {
    "crm": {"lead_source"},
    "sales": {"lead_source"},
    "lead-intelligence": {"lead_source"},
    "b2b-project-intake": {"lead_source", "project"},
    "contract-generator": {"contract"},
    "financial-control": {"contract"},
    "finance-intelligence": {"contract", "project"},
    "project-control": {"project"},
    "pm-cockpit": {"project"},
    "operations-workspace": {"project"},
    "digital-project-managers": {"project"},
    "my-imperial": {"project", "project_document"},
    "document-center": {"project_document", "contract"},
    "document-evidence": {"project_document", "contract"},
    "partner-connect": {"partner_source"},
    "partner-control": {"partner_source"},
    "partner-field": {"partner_source", "project"},
    "procurement": {"partner_source", "project"},
}

# Entity and three domain-specific capture fields for every registered module.
BUSINESS_PROFILES: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "workspace": (
        "Személyes munkatétel",
        (
            ("outcome", "Elvárt eredmény"),
            ("context", "Kontextus"),
            ("next_step", "Következő lépés"),
        ),
    ),
    "executive-dashboard": (
        "Vezetői döntés",
        (
            ("decision_owner", "Döntéshozó"),
            ("business_impact", "Üzleti hatás"),
            ("recommendation", "Javaslat"),
        ),
    ),
    "control-center": (
        "Irányítási kivétel",
        (("control_area", "Kontrollterület"), ("risk", "Kockázat"), ("remediation", "Intézkedés")),
    ),
    "completion-audit": (
        "Teljességi ellenőrzés",
        (("release", "Kiadás"), ("gate", "Ellenőrzési kapu"), ("evidence", "Bizonyíték")),
    ),
    "integration-control-room": (
        "Integrációs incidens",
        (("connector", "Kapcsolat"), ("failure", "Hiba"), ("recovery", "Helyreállítás")),
    ),
    "admin": (
        "Rendszerbeállítás",
        (("setting", "Beállítás"), ("scope", "Hatókör"), ("change_reason", "Módosítás oka")),
    ),
    "workflow-center": (
        "Feladatfolyam",
        (
            ("process", "Folyamat"),
            ("dependency", "Függőség"),
            ("acceptance", "Elfogadási feltétel"),
        ),
    ),
    "pm-cockpit": (
        "Projektkapu",
        (("phase", "Fázis"), ("readiness", "Készültség"), ("blocker", "Blokkoló tényező")),
    ),
    "operations-workspace": (
        "Munkacsomag",
        (
            ("trade", "Szakág"),
            ("progress", "Készültség"),
            ("site_constraint", "Helyszíni feltétel"),
        ),
    ),
    "digital-project-managers": (
        "Projektterv",
        (("method", "Módszer"), ("milestone", "Mérföldkő"), ("capacity", "Kapacitás")),
    ),
    "crm": (
        "Ügyfél / érdeklődő",
        (
            ("contact", "Kapcsolattartó"),
            ("source", "Forrás"),
            ("next_step", "Következő értékesítési lépés"),
        ),
    ),
    "sales": (
        "Értékesítési lehetőség",
        (("stage", "Értékesítési szakasz"), ("probability", "Valószínűség"), ("offer", "Ajánlat")),
    ),
    "booking-engine": (
        "Időpontfoglalás",
        (("service", "Szolgáltatás"), ("location", "Helyszín"), ("slot", "Idősáv")),
    ),
    "reservation-engine": (
        "Foglalás / árzár",
        (("product", "Termék"), ("valid_until", "Érvényesség"), ("deposit", "Foglaló")),
    ),
    "contract-generator": (
        "Szerződés",
        (
            ("template", "Sablon"),
            ("counterparty", "Szerződő fél"),
            ("signature", "Aláírási állapot"),
        ),
    ),
    "my-imperial": (
        "Ügyfélkérelem",
        (
            ("customer_action", "Ügyfél teendője"),
            ("visibility", "Láthatóság"),
            ("response", "Válasz"),
        ),
    ),
    "house-catalog": (
        "Típusház",
        (("brand", "Márka"), ("area", "Alapterület"), ("technology", "Technológia")),
    ),
    "housebuild-agent": (
        "Házgenerálási feladat",
        (("brief", "Tervezési brief"), ("variant", "Változat"), ("output", "Eredmény")),
    ),
    "housematch": (
        "Házválasztási eset",
        (("budget", "Keret"), ("needs", "Igények"), ("recommendation", "Ajánlás")),
    ),
    "house-designer": (
        "Ügyfél által szerkesztett házterv",
        (
            ("floor_program", "Szint- és helyiségprogram"),
            ("regulatory_scope", "OTÉK/HÉSZ ellenőrzési kör"),
            ("configuration", "Technológia és műszaki tartalom"),
        ),
    ),
    "plotcheck": (
        "Telekvizsgálat",
        (("plot", "Telek"), ("constraint", "Korlátozás"), ("finding", "Megállapítás")),
    ),
    "buildconfig": (
        "Építési konfiguráció",
        (("package", "Csomag"), ("options", "Opciók"), ("price_basis", "Áralap")),
    ),
    "plancheck": (
        "Tervellenőrzés",
        (("plan_set", "Tervcsomag"), ("discipline", "Szakág"), ("finding", "Eltérés")),
    ),
    "engineering-workspace": (
        "Mérnöki tervcsomag",
        (("discipline", "Szakág"), ("revision", "Revízió"), ("deliverable", "Szállítandó anyag")),
    ),
    "housevision": (
        "Látványtervi igény",
        (("view", "Nézet"), ("style", "Stílus"), ("revision", "Revízió")),
    ),
    "project-control": (
        "Projektirányítási tétel",
        (("scope", "Terjedelem"), ("milestone", "Mérföldkő"), ("variance", "Eltérés")),
    ),
    "smart-calendar": (
        "Ütemezési esemény",
        (("calendar", "Naptár"), ("dependency", "Függőség"), ("resource", "Erőforrás")),
    ),
    "change-control": (
        "Változtatási igény",
        (
            ("change_scope", "Változás"),
            ("schedule_impact", "Ütemezési hatás"),
            ("cost_impact", "Költséghatás"),
        ),
    ),
    "document-center": (
        "Dokumentum",
        (("category", "Kategória"), ("version", "Verzió"), ("retention", "Megőrzés")),
    ),
    "document-evidence": (
        "Bizonyíték",
        (
            ("evidence_type", "Bizonyíték típusa"),
            ("source", "Forrás"),
            ("verification", "Ellenőrzés"),
        ),
    ),
    "import-center": (
        "Importfeladat",
        (("source", "Forrás"), ("entity", "Adattípus"), ("quality", "Adatminőség")),
    ),
    "tendermail": (
        "Tenderkampány",
        (
            ("trade", "Szakág"),
            ("recipient_group", "Címzettcsoport"),
            ("deadline", "Ajánlati határidő"),
        ),
    ),
    "partner-connect": (
        "Partnerkapcsolat",
        (
            ("partner_type", "Partnertípus"),
            ("qualification", "Minősítés"),
            ("capacity", "Kapacitás"),
        ),
    ),
    "partner-control": (
        "Partnerértékelés",
        (("partner", "Partner"), ("criterion", "Szempont"), ("rating", "Értékelés")),
    ),
    "partner-field": (
        "Partner helyszíni jelentés",
        (("crew", "Csapat"), ("work_done", "Elvégzett munka"), ("evidence", "Bizonyíték")),
    ),
    "field-pwa": (
        "Helyszíni napló",
        (("weather", "Időjárás"), ("headcount", "Létszám"), ("progress", "Előrehaladás")),
    ),
    "procurement": (
        "Beszerzési igény / rendelés",
        (
            ("supplier", "Beszállító"),
            ("material", "Anyag / szolgáltatás"),
            ("delivery", "Szállítás"),
        ),
    ),
    "finance-intelligence": (
        "Cash-flow / előrejelzés",
        (("period", "Időszak"), ("scenario", "Forgatókönyv"), ("variance", "Eltérés")),
    ),
    "financial-control": (
        "Számla / pénzügyi tétel",
        (
            ("counterparty", "Partner"),
            ("document_number", "Bizonylatszám"),
            ("payment_status", "Fizetési állapot"),
        ),
    ),
    "imperial-care": (
        "Garanciális ügy",
        (("warranty_type", "Ügytípus"), ("location", "Helyszín"), ("resolution", "Megoldás")),
    ),
    "marketing-control": (
        "Marketingportfólió-tétel",
        (("brand", "Márka"), ("objective", "Cél"), ("attribution", "Attribúció")),
    ),
    "market-creative-intelligence": (
        "Piaci kutatási bizonyítékcsomag",
        (
            ("source_scope", "Jóváhagyott forráskör"),
            ("evidence", "Bizonyíték és provenance"),
            ("intended_use", "Engedélyezett belső felhasználás"),
        ),
    ),
    "campaign-factory": (
        "Kampány",
        (
            ("channel", "Csatorna"),
            ("audience", "Célközönség"),
            ("conversion_goal", "Konverziós cél"),
        ),
    ),
    "content-factory": (
        "Tartalmi elem",
        (("channel", "Csatorna"), ("format", "Formátum"), ("brief", "Brief")),
    ),
    "claim-registry": (
        "Állítás / bizonyíték",
        (("claim", "Állítás"), ("source", "Forrás"), ("validity", "Érvényesség")),
    ),
    "website-content-control": (
        "Webes tartalom",
        (("site", "Webhely"), ("page", "Oldal"), ("publication", "Publikáció")),
    ),
    "answer-center": (
        "Tudásbázis-válasz",
        (("question", "Kérdés"), ("audience", "Célközönség"), ("source", "Hiteles forrás")),
    ),
    "lead-intelligence": (
        "Lead-minősítés",
        (("lead", "Lead"), ("score", "Pontszám"), ("signal", "Jelzés")),
    ),
    "b2b-project-intake": (
        "B2B projektigény",
        (("company", "Vállalat"), ("scope", "Projektigény"), ("qualification", "Minősítés")),
    ),
}


GENERIC_ACTIONS = (
    {
        "id": "submit",
        "label": "Beküldés ellenőrzésre",
        "nextStatus": "in_review",
        "eventKey": "BUSINESS_RECORD_SUBMITTED",
        "consumers": [],
    },
    {
        "id": "approve",
        "label": "Jóváhagyás",
        "nextStatus": "approved",
        "eventKey": "BUSINESS_RECORD_APPROVED",
        "consumers": [],
    },
    {
        "id": "activate",
        "label": "Aktiválás",
        "nextStatus": "active",
        "eventKey": "BUSINESS_RECORD_ACTIVATED",
        "consumers": [],
    },
    {
        "id": "complete",
        "label": "Lezárás",
        "nextStatus": "completed",
        "eventKey": "BUSINESS_RECORD_COMPLETED",
        "consumers": [],
    },
    {
        "id": "reject",
        "label": "Elutasítás",
        "nextStatus": "rejected",
        "eventKey": "BUSINESS_RECORD_REJECTED",
        "consumers": [],
    },
    {
        "id": "reopen",
        "label": "Újranyitás",
        "nextStatus": "in_progress",
        "eventKey": "BUSINESS_RECORD_REOPENED",
        "consumers": [],
    },
)

MODULE_WORKFLOW_FAMILY: dict[str, str] = {
    "workspace": "work",
    "executive-dashboard": "governance",
    "control-center": "governance",
    "completion-audit": "governance",
    "integration-control-room": "data",
    "admin": "governance",
    "workflow-center": "work",
    "pm-cockpit": "operations",
    "operations-workspace": "operations",
    "digital-project-managers": "operations",
    "crm": "commercial",
    "sales": "commercial",
    "booking-engine": "booking",
    "reservation-engine": "booking",
    "contract-generator": "contract",
    "my-imperial": "customer",
    "house-catalog": "product",
    "housebuild-agent": "technical",
    "housematch": "commercial",
    "house-designer": "technical",
    "plotcheck": "technical",
    "buildconfig": "technical",
    "plancheck": "technical",
    "engineering-workspace": "technical",
    "housevision": "technical",
    "project-control": "operations",
    "smart-calendar": "booking",
    "change-control": "change",
    "document-center": "document",
    "document-evidence": "document",
    "import-center": "data",
    "tendermail": "procurement",
    "partner-connect": "partner",
    "partner-control": "partner",
    "partner-field": "operations",
    "field-pwa": "operations",
    "procurement": "procurement",
    "finance-intelligence": "finance",
    "financial-control": "finance",
    "imperial-care": "customer",
    "marketing-control": "content",
    "market-creative-intelligence": "knowledge",
    "campaign-factory": "content",
    "content-factory": "content",
    "claim-registry": "knowledge",
    "website-content-control": "content",
    "answer-center": "knowledge",
    "lead-intelligence": "commercial",
    "b2b-project-intake": "commercial",
}

FAMILY_LIFECYCLES: dict[str, dict[str, Any]] = {
    "work": {"initial": "new", "review": "in_review", "required_core": ("assignee",)},
    "governance": {
        "initial": "draft",
        "review": "in_review",
        "required_core": ("assignee",),
        "approval": "management_approval",
    },
    "data": {"initial": "received", "review": "validated", "required_data": "all"},
    "operations": {
        "initial": "planned",
        "review": "ready",
        "required_core": ("project_id", "assignee"),
    },
    "commercial": {
        "initial": "new",
        "review": "qualified",
        "required_core": ("customer_reference", "assignee"),
    },
    "booking": {
        "initial": "requested",
        "review": "confirmed",
        "required_core": ("customer_reference", "due_at"),
    },
    "contract": {
        "initial": "draft",
        "review": "legal_review",
        "required_core": ("customer_reference", "project_id"),
        "approval": "legal_approval",
    },
    "customer": {
        "initial": "new",
        "review": "triaged",
        "required_core": ("customer_reference", "assignee"),
    },
    "product": {"initial": "draft", "review": "technical_review", "required_data": "all"},
    "technical": {
        "initial": "draft",
        "review": "technical_review",
        "required_core": ("project_id",),
        "required_data": "all",
        "approval": "technical_approval",
    },
    "change": {
        "initial": "draft",
        "review": "impact_review",
        "required_core": ("project_id", "assignee"),
        "required_data": "all",
        "approval": "change_approval",
    },
    "document": {
        "initial": "draft",
        "review": "verification",
        "required_core": ("project_id",),
        "required_data": "all",
    },
    "procurement": {
        "initial": "draft",
        "review": "commercial_review",
        "required_core": ("project_id", "assignee"),
        "required_data": "all",
        "approval": "procurement_approval",
    },
    "partner": {
        "initial": "prospect",
        "review": "qualification",
        "required_core": ("assignee",),
        "required_data": "all",
    },
    "finance": {
        "initial": "draft",
        "review": "validated",
        "required_core": ("project_id",),
        "approval": "finance_approval",
        "positive_amount": True,
    },
    "content": {
        "initial": "draft",
        "review": "human_review",
        "required_data": "all",
        "approval": "publication_approval",
    },
    "knowledge": {
        "initial": "draft",
        "review": "expert_review",
        "required_data": "all",
        "approval": "expert_approval",
    },
}


def utcnow() -> datetime:
    return datetime.now(UTC)


@lru_cache(maxsize=1)
def _seed_modules() -> dict[str, dict[str, Any]]:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return {module["id"]: module for module in data["modules"]}


def module_profile(module_key: str) -> dict[str, Any]:
    seed = _seed_modules().get(module_key)
    profile = BUSINESS_PROFILES.get(module_key)
    if not seed or not profile:
        raise ValueError(f"Ismeretlen üzleti modul: {module_key}")
    entity_label, fields = profile
    family_name = MODULE_WORKFLOW_FAMILY[module_key]
    lifecycle = FAMILY_LIFECYCLES[family_name]
    initial = lifecycle["initial"]
    review = lifecycle["review"]
    seed_actions = [
        {
            **action,
            "fromStatuses": [initial, review, "in_progress", "approved"],
            "requiredCore": list(lifecycle.get("required_core", ())),
            "requiredData": lifecycle.get("required_data"),
            "positiveAmount": bool(lifecycle.get("positive_amount")),
            "requiredApproval": lifecycle.get("approval"),
        }
        for action in seed.get("actions", [])
    ]
    review_states = [
        review,
        "in_review",
        "technical_review",
        "legal_review",
        "impact_review",
        "commercial_review",
        "human_review",
        "expert_review",
        "verification",
        "validated",
        "qualification",
        "triaged",
        "ready",
    ]
    generic_actions = [
        {
            **GENERIC_ACTIONS[0],
            "label": "Beküldés szakmai ellenőrzésre",
            "nextStatus": review,
            "fromStatuses": [initial, "rejected"],
            "requiredCore": list(lifecycle.get("required_core", ())),
            "requiredData": lifecycle.get("required_data"),
            "positiveAmount": bool(lifecycle.get("positive_amount")),
        },
        {
            **GENERIC_ACTIONS[1],
            "fromStatuses": review_states,
            "requiredApproval": lifecycle.get("approval"),
        },
        {
            **GENERIC_ACTIONS[2],
            "fromStatuses": [
                "approved",
                "confirmed",
                "qualified",
                "verified",
                "released",
                "published",
            ],
        },
        {
            **GENERIC_ACTIONS[3],
            "fromStatuses": [
                "active",
                "approved",
                "in_progress",
                "reconciled",
                "acknowledged",
                "evidence_submitted",
                "ordered",
                "signed",
                "locked",
                "selected",
                "published",
                "verified",
                "consistent",
                "reviewed",
                "dispatched",
                "triaged",
                "confirmed",
                "qualified",
            ],
        },
        {**GENERIC_ACTIONS[4], "fromStatuses": review_states},
        {
            **GENERIC_ACTIONS[5],
            "fromStatuses": ["completed", "rejected", "blocked", "closed", "archived"],
        },
    ]
    actions = [*seed_actions, *generic_actions]
    seen: set[str] = set()
    deduplicated_actions = []
    for action in actions:
        if action["id"] not in seen:
            deduplicated_actions.append(action)
            seen.add(action["id"])
    statuses = list(dict.fromkeys([initial, review, *COMMON_STATUSES]))
    for action in deduplicated_actions:
        if action["nextStatus"] not in statuses:
            statuses.append(action["nextStatus"])
    return {
        "module_key": module_key,
        "name": seed["name"],
        "source_release": seed.get("sourceRelease"),
        "entity_label": entity_label,
        "fields": [{"key": key, "label": label} for key, label in fields],
        "statuses": statuses,
        "actions": deduplicated_actions,
        "initial_status": initial,
        "workflow_family": family_name,
    }


def _validate_transition(record: ModuleBusinessRecord, action: dict[str, Any]) -> None:
    if record.status not in (action.get("fromStatuses") or []):
        raise ValueError(
            f"A(z) {action['label']} művelet nem indítható {record.status} állapotból."
        )
    missing = [
        field
        for field in action.get("requiredCore", [])
        if getattr(record, field, None) in (None, "")
    ]
    data = json.loads(record.data_json or "{}")
    if action.get("requiredData") == "all":
        missing.extend(
            f"data.{key}"
            for key, _label in BUSINESS_PROFILES[record.module_key][1]
            if data.get(key) in (None, "")
        )
    if action.get("positiveAmount") and Decimal(str(record.amount_huf or 0)) <= 0:
        missing.append("amount_huf")
    if missing:
        raise ValueError("A művelethez kötelező mezők hiányoznak: " + ", ".join(missing))
    approval_stage = action.get("requiredApproval")
    if approval_stage and not any(
        item.stage == approval_stage and item.decision == "approved" for item in record.approvals
    ):
        raise ValueError(f"A művelethez jóváhagyott {approval_stage} kontroll szükséges.")


def module_source_projection(module_key: str) -> dict[str, Any] | None:
    """Return a read-only projection of the canonical CRM migration inventory."""
    record_types = SOURCE_RECORD_TYPES.get(module_key)
    if not record_types:
        return None
    if not settings.crm_read_base_url or not settings.crm_read_token:
        return {
            "connected": False,
            "message": "A CRM forráskapcsolat nincs konfigurálva.",
            "total": 0,
            "counts": [],
            "recent": [],
        }
    query = urllib.parse.urlencode({"workspaceId": settings.crm_workspace_id})
    request = urllib.request.Request(
        f"{settings.crm_read_base_url}/api/integrations/migration/full/status?{query}",
        headers=crm_service_headers("X-ITEP-CRM-Token", settings.crm_read_token),
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {
            "connected": False,
            "message": f"A CRM forráspillanatkép nem elérhető: {type(exc).__name__}",
            "total": 0,
            "counts": [],
            "recent": [],
        }
    counts = [
        row for row in payload.get("recordCounts", []) if row.get("recordType") in record_types
    ]
    recent = [
        row for row in payload.get("recentRecords", []) if row.get("recordType") in record_types
    ][:8]
    return {
        "connected": True,
        "message": "Kanonikus CRM migrációs forrás",
        "total": sum(int(row.get("count") or 0) for row in counts),
        "counts": counts,
        "recent": recent,
        "open_reviews": payload.get("openReviews", []),
        "workspace_id": payload.get("workspaceId"),
    }


def list_records(
    db: Session,
    module_key: str,
    *,
    include_archived: bool = False,
) -> list[ModuleBusinessRecord]:
    module_profile(module_key)
    query = select(ModuleBusinessRecord).where(ModuleBusinessRecord.module_key == module_key)
    if not include_archived:
        query = query.where(ModuleBusinessRecord.archived.is_(False))
    return list(db.scalars(query.order_by(desc(ModuleBusinessRecord.updated_at))).all())


def get_record(db: Session, module_key: str, record_id: str) -> ModuleBusinessRecord:
    record = db.scalar(
        select(ModuleBusinessRecord)
        .options(
            selectinload(ModuleBusinessRecord.comments),
            selectinload(ModuleBusinessRecord.approvals),
        )
        .where(
            ModuleBusinessRecord.module_key == module_key,
            ModuleBusinessRecord.record_id == record_id,
        )
    )
    if not record:
        raise ValueError("Az üzleti rekord nem található.")
    return record


def create_record(
    db: Session,
    module_key: str,
    payload: ModuleBusinessRecordIn,
    *,
    actor: str,
) -> ModuleBusinessRecord:
    if module_key == "imperial-care":
        raise ValueError(
            "Ügyfélhibát kizárólag a dedikált Imperial Care felületen lehet rögzíteni."
        )
    profile = module_profile(module_key)
    status = payload.status or profile["initial_status"]
    if status != profile["initial_status"]:
        raise ValueError("Új rekord csak a modul kezdőállapotában hozható létre.")
    record = ModuleBusinessRecord(
        record_id=f"MBR-{uuid.uuid4().hex[:12].upper()}",
        module_key=module_key,
        record_type=payload.record_type or profile["entity_label"],
        title=payload.title.strip(),
        description=payload.description,
        status=status,
        project_id=payload.project_id or None,
        customer_reference=payload.customer_reference or None,
        assignee=payload.assignee or None,
        priority=payload.priority,
        due_at=payload.due_at,
        amount_huf=payload.amount_huf,
        data_json=json.dumps(payload.data, ensure_ascii=False, default=str),
        created_by=actor,
        updated_by=actor,
    )
    db.add(record)
    db.flush()
    audit(
        db,
        actor=actor,
        action="module_business_record_created",
        entity_type=module_key,
        entity_id=record.record_id,
        after=serialize_record(record),
    )
    db.commit()
    return get_record(db, module_key, record.record_id)


def update_record(
    db: Session,
    module_key: str,
    record_id: str,
    payload: ModuleBusinessRecordUpdateIn,
    *,
    actor: str,
) -> ModuleBusinessRecord:
    module_profile(module_key)
    record = get_record(db, module_key, record_id)
    before = serialize_record(record)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes:
        if changes["status"] != record.status:
            raise ValueError("Állapotot csak naplózott üzleti művelettel lehet módosítani.")
        changes.pop("status")
    if "data" in changes:
        record.data_json = json.dumps(changes.pop("data") or {}, ensure_ascii=False, default=str)
    for field, value in changes.items():
        setattr(record, field, value)
    record.version += 1
    record.updated_by = actor
    record.updated_at = utcnow()
    audit(
        db,
        actor=actor,
        action="module_business_record_updated",
        entity_type=module_key,
        entity_id=record.record_id,
        before=before,
        after=serialize_record(record),
    )
    db.commit()
    return get_record(db, module_key, record.record_id)


def add_comment(
    db: Session,
    module_key: str,
    record_id: str,
    body: str,
    *,
    actor: str,
) -> ModuleBusinessComment:
    record = get_record(db, module_key, record_id)
    comment = ModuleBusinessComment(
        comment_id=f"MBC-{uuid.uuid4().hex[:12].upper()}",
        record_id_fk=record.id,
        body=body.strip(),
        author=actor,
    )
    db.add(comment)
    audit(
        db,
        actor=actor,
        action="module_business_comment_added",
        entity_type=module_key,
        entity_id=record.record_id,
        after={"comment_id": comment.comment_id},
    )
    db.commit()
    db.refresh(comment)
    return comment


def add_approval(
    db: Session,
    module_key: str,
    record_id: str,
    *,
    stage: str,
    decision: str,
    note: str | None,
    actor: str,
) -> ModuleBusinessApproval:
    if decision not in {"pending", "approved", "rejected"}:
        raise ValueError("Érvénytelen jóváhagyási döntés.")
    record = get_record(db, module_key, record_id)
    decided = decision != "pending"
    approval = ModuleBusinessApproval(
        approval_id=f"MBA-{uuid.uuid4().hex[:12].upper()}",
        record_id_fk=record.id,
        stage=stage.strip(),
        decision=decision,
        note=note,
        requested_by=actor,
        decided_by=actor if decided else None,
        decided_at=utcnow() if decided else None,
    )
    db.add(approval)
    audit(
        db,
        actor=actor,
        action=f"module_business_approval_{decision}",
        entity_type=module_key,
        entity_id=record.record_id,
        after={"approval_id": approval.approval_id, "stage": stage},
    )
    db.commit()
    db.refresh(approval)
    return approval


def transition_record(
    db: Session,
    module_key: str,
    record_id: str,
    action_id: str,
    *,
    actor: str,
    project_id: str | None = None,
    note: str | None = None,
) -> ModuleBusinessRecord:
    profile = module_profile(module_key)
    action = next((item for item in profile["actions"] if item["id"] == action_id), None)
    if not action:
        raise ValueError("Ismeretlen modulművelet.")
    record = get_record(db, module_key, record_id)
    _validate_transition(record, action)
    before_status = record.status
    record.status = action["nextStatus"]
    record.updated_by = actor
    record.updated_at = utcnow()
    record.version += 1
    audit(
        db,
        actor=actor,
        action=f"module_business_transition:{action_id}",
        entity_type=module_key,
        entity_id=record.record_id,
        before={"status": before_status},
        after={"status": record.status, "note": note},
    )
    effective_project_id = project_id or record.project_id
    if effective_project_id:
        ingest_event(
            db,
            EventIn(
                event_id=f"EVT-{uuid.uuid4().hex[:12].upper()}",
                dedupe_key=f"{module_key}:{record.record_id}:{record.version}:{action_id}",
                project_id=effective_project_id,
                source_module=module_key,
                event_type=action["eventKey"],
                object_type=record.record_type,
                object_id=record.record_id,
                status=record.status,
                responsible=record.assignee,
                financial_impact_huf=record.amount_huf,
                payload={"summary": note or record.title, "record_id": record.record_id},
                route_to=list(action.get("consumers", [])),
            ),
            actor=actor,
        )
    else:
        db.commit()
    return get_record(db, module_key, record.record_id)


def serialize_record(
    record: ModuleBusinessRecord, *, include_threads: bool = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "record_id": record.record_id,
        "module_key": record.module_key,
        "record_type": record.record_type,
        "title": record.title,
        "description": record.description,
        "status": record.status,
        "project_id": record.project_id,
        "customer_reference": record.customer_reference,
        "assignee": record.assignee,
        "priority": record.priority,
        "due_at": record.due_at,
        "amount_huf": Decimal(str(record.amount_huf or 0)),
        "data": json.loads(record.data_json or "{}"),
        "version": record.version,
        "archived": record.archived,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if include_threads:
        payload["comments"] = [
            {
                "comment_id": item.comment_id,
                "body": item.body,
                "author": item.author,
                "created_at": item.created_at,
            }
            for item in sorted(record.comments, key=lambda item: item.created_at)
        ]
        payload["approvals"] = [
            {
                "approval_id": item.approval_id,
                "stage": item.stage,
                "decision": item.decision,
                "note": item.note,
                "requested_by": item.requested_by,
                "decided_by": item.decided_by,
                "requested_at": item.requested_at,
                "decided_at": item.decided_at,
            }
            for item in sorted(record.approvals, key=lambda item: item.requested_at)
        ]
    return payload
