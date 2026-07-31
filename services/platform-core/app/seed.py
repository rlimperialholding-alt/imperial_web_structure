from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    CalculationSourceRegistry,
    CopySourceRecord,
    DeliveryNoteProjection,
    DevelopmentDiscoveryRecord,
    EnvironmentRecord,
    EventRecord,
    ImportDataSource,
    MailSendingDomain,
    MaterialLot,
    MaterialMovement,
    MaterialUsageControl,
    ModuleRegistry,
    PartnerFieldAccess,
    PartnerWorker,
    PMGateCheck,
    PMPhase,
    PMWorkPackage,
    ProcurementOrderProjection,
    ProjectFact,
    ProjectObjectState,
    ProjectRegistry,
    SiteDailyReport,
    SiteIssue,
    TaskRecord,
    User,
    WorkspaceDocument,
)
from .security import hash_password
from .roles import ROLE_DEFINITIONS
from .services.development_governance import seed_canonical_discoveries

DEMO_PASSWORD = "Imperial2026!"
# Synthetic accounts share one process-local hash so test database resets do
# not repeat the intentionally expensive PBKDF2 operation twelve times.
DEMO_PASSWORD_HASH = hash_password(DEMO_PASSWORD)
DEMO_USER_NAMES = {
    "owner": "Imperial Tulajdonos",
    "managing-director": "Imperial Ügyvezető",
    "marketing": "Imperial Marketing",
    "copywriter": "Imperial Direct-response Szövegíró",
    "creative-director": "Imperial Kreatív Igazgató",
    "technical-prep": "Imperial Műszaki Előkészítő",
    "sales": "Imperial Értékesítő",
    "finance": "Imperial Pénzügy",
    "project-manager": "Imperial Projektmenedzser",
    "designer": "Imperial Tervező",
    "subcontractor": "Imperial Alvállalkozó",
    "customer": "Imperial Ügyfél",
    "legal": "Imperial Jogász",
    "platform-admin": "Imperial Platform Admin",
}

DEMO_MODULE_SEED = (
    Path(__file__).resolve().parents[1] / "data" / "platform_demo_seed.json"
)

MODULE_METADATA = {
    "crm": ("1.3.0", "Értékesítés", "critical"),
    "contract-generator": ("0.4.0", "Jogi / operáció", "high"),
    "pm-cockpit": ("1.0.0", "Projektvezetés", "critical"),
    "smart-calendar": ("1.1.0", "Projektvezetés", "high"),
    "my-imperial": ("0.1.0", "Ügyfélkapcsolat", "high"),
    "change-control": ("0.1.0", "Projektvezetés", "critical"),
    "partner-connect": ("0.3.0", "Beszerzés", "high"),
    "procurement": ("1.0.0", "Projektvezetés / beszerzés", "critical"),
    "finance-intelligence": ("1.0.0", "Pénzügy", "critical"),
    "imperial-care": ("0.1.0", "Garancia", "high"),
    "housematch": ("0.3.0", "Marketing / értékesítés", "medium"),
    "plotcheck": ("0.2.0", "Műszaki", "medium"),
    "buildconfig": ("0.2.0", "Árazás / műszaki", "high"),
    "plancheck": ("0.1.0", "Műszaki", "high"),
    "control-center": ("1.1.0", "Tulajdonos / ügyvezető", "critical"),
    "import-center": ("0.1.0", "Adatgazdák / vezetés", "critical"),
    "tendermail": ("0.1.0", "Beszerzés / partnerkapcsolat", "high"),
    "operations-workspace": (
        "1.0.0",
        "Projektvezetés / helyszín / beszerzés",
        "critical",
    ),
    "field-pwa": ("1.0.0", "Helyszíni csapat", "high"),
    "integration-control-room": (
        "1.0.0",
        "Jogi / operáció / projektvezetés",
        "critical",
    ),
}

LEGACY_MODULE_ALIASES = {
    "calendar": "smart-calendar",
    "change_control": "change-control",
    "commercial_integration": "integration-control-room",
    "contract_generator": "contract-generator",
    "control_center": "control-center",
    "field_pwa": "field-pwa",
    "finance": "finance-intelligence",
    "imperial_care": "imperial-care",
    "import_center": "import-center",
    "myimperial": "my-imperial",
    "operations_workspace": "operations-workspace",
    "partner_connect": "partner-connect",
    "project_control": "pm-cockpit",
    "tender_mail": "tendermail",
}


def _release_version(source_release: str | None) -> str:
    match = re.search(r"\b(?:v)?(\d+(?:\.\d+){1,2})\b", source_release or "")
    if not match:
        return "0.1.0"
    parts = match.group(1).split(".")
    return ".".join(parts + ["0"] * (3 - len(parts)))


def _canonical_modules() -> list[tuple[str, str, str, str, str]]:
    data = json.loads(DEMO_MODULE_SEED.read_text(encoding="utf-8"))
    modules = []
    for module in data["modules"]:
        module_id = module["id"]
        version, owner, criticality = MODULE_METADATA.get(
            module_id,
            (_release_version(module.get("sourceRelease")), "Imperial Intelligence", "medium"),
        )
        modules.append((module_id, module["name"], version, owner, criticality))
    return modules


MODULES = _canonical_modules()


IMPORT_SOURCES = [
    ("google_drive_enterprise", "Google Drive – vállalati dokumentumok", "google_drive", "enterprise", "google-drive://connected"),
    ("onedrive_enterprise", "Microsoft OneDrive / SharePoint – vállalati dokumentumok", "onedrive", "enterprise", None),
    ("gmail_enterprise", "Gmail – üzleti levelezés és mellékletek", "gmail", "enterprise", "gmail://connected"),
    ("google_sheets_enterprise", "Google Sheets – pénzügyi és projekt táblák", "google_sheets", "finance,project,procurement", "google-sheets://connected"),
    ("manual_upload", "Kézi Excel / CSV / JSON feltöltés", "file_upload", "enterprise", None),
    ("legacy_crm_export", "Korábbi CRM- és partnerexportok", "file_upload", "partner,customer,project", None),
]

CALCULATION_SOURCES = [
    {
        "source_key": "technology_completion_price_model_2026_07",
        "name": "Imperial 100m² technológia–készültség ármodell 2026-07",
        "source_role": "primary_internal_price_model",
        "priority": 10,
        "drive_file_id": "1jlkCJLRbSr4cP0TbUEFCVnd1yh9adMB-",
        "drive_url": "https://drive.google.com/file/d/1jlkCJLRbSr4cP0TbUEFCVnd1yh9adMB-",
        "sha256": "49b76433fe97da468092d55fcc8290b56e8d801daaf11235a0b76b033e791ab7",
        "effective_date": "2026-07-14",
        "usage_rule": "Elsődleges belső all-in önköltség, 35%-os minimum, optimum, piaci plafon és javasolt ár.",
    },
    {
        "source_key": "brand_web_prices_2026_07",
        "name": "Kalkulációs oldalak frissített márkaárai 2026-07",
        "source_role": "public_brand_price",
        "priority": 20,
        "drive_file_id": "1pFiXUVRIOqkDf40pgM5jUgNX2gUHpxZ4",
        "drive_url": "https://drive.google.com/file/d/1pFiXUVRIOqkDf40pgM5jUgNX2gUHpxZ4",
        "sha256": "d5f69604709882ba6469ecaaf1be2a622328c6e896e2da572260f50bb782cabc",
        "effective_date": "2026-07-14",
        "usage_rule": "Márka- és piaci pozicionálás, ügyféloldali induló árforrás.",
    },
    {
        "source_key": "artukor_labor_material_2026_07",
        "name": "Generálkivitelezői Ártükör – munkadíj és anyag 2026-07",
        "source_role": "line_item_control",
        "priority": 30,
        "drive_file_id": "1fnfXGxWR9Du8gFIV94eqLkVVU_Si0xPH",
        "drive_url": "https://drive.google.com/file/d/1fnfXGxWR9Du8gFIV94eqLkVVU_Si0xPH",
        "sha256": "93bfcfe63437ff6be24eb54a770823863a6f144e3819d2fbad577aac5dc21f36",
        "effective_date": "2026-07-14",
        "usage_rule": "Tételes ellenőrzés és felújítási tételkatalógus; újépítési all-in önköltséghez tilos automatikusan hozzáadni.",
    },
    {
        "source_key": "housematch_catalog_score_v0_1",
        "name": "HouseMatch katalógus és pontozási modell v0.1",
        "source_role": "housematch_catalog",
        "priority": 10,
        "drive_file_id": "1Jrs_RIkLoino40nYPUibpfkKW7lQ27DHP-jJblNpAlE",
        "drive_url": "https://docs.google.com/spreadsheets/d/1Jrs_RIkLoino40nYPUibpfkKW7lQ27DHP-jJblNpAlE",
        "sha256": "05ceddb57b39e6b36f7ec35b405ac05f1ce142ae28dd5f00accc9f5eefd81b07",
        "effective_date": "2026-07-17",
        "usage_rule": "A v0.3 működő HouseMatch pontozásának és aktív katalógusának forrása.",
    },
    {
        "source_key": "legacy_banded_calculator",
        "name": "Imperial sávos kalkulátor – legacy referencia",
        "source_role": "legacy_area_band_reference",
        "priority": 90,
        "drive_file_id": "1V_IpqMJJgO-I4cGS1ArIhzKnIeNLRjai",
        "drive_url": "https://drive.google.com/file/d/1V_IpqMJJgO-I4cGS1ArIhzKnIeNLRjai",
        "sha256": "f73729d7adc688d5b93afc12b44dec67dbde2ad3ece218aee0d1089a661d28e7",
        "effective_date": "2025-10-02",
        "usage_rule": "Csak referencia; a 2026-07 ármodellel történő scope- és képletrekonsziliáció után aktiválható.",
        "status": "reference_only",
    },
]



def seed_workspace_demo(db: Session) -> None:
    if settings.environment.lower() != "development":
        return
    if db.scalar(select(ProjectRegistry).limit(1)):
        return
    now = datetime.now(timezone.utc)
    projects = [
        ProjectRegistry(project_id="IMP-POMAZ-001", name="Pomáz – Athén családi ház", customer_name="T. János", project_type="Tégla családi ház", status="active", risk_level="yellow", blocked=False, financial_impact_huf=Decimal("1900000"), deadline_impact_days=5, responsible="Projektvezetés", next_action="Ügyféldöntés és módosított gépészeti csomag jóváhagyása"),
        ProjectRegistry(project_id="IMP-GOD-014", name="Göd – szerkezetépítési projekt", customer_name="Imperial Holding", project_type="Aktív kivitelezés", status="active", risk_level="critical", blocked=True, financial_impact_huf=Decimal("4850000"), deadline_impact_days=9, responsible="Beszerzés", next_action="Hiányzó szállítólevél és teljesítménynyilatkozat pótlása"),
        ProjectRegistry(project_id="IMP-FONYOD-011", name="Fonyód – lejtős telek és támfal", customer_name="Magánmegrendelő", project_type="Előkészítés / pótmunka", status="planning", risk_level="green", blocked=False, financial_impact_huf=Decimal("0"), deadline_impact_days=0, responsible="Műszaki előkészítés", next_action="Módosított pótmunka-ajánlat műszaki ellenőrzése"),
    ]
    db.add_all(projects)
    db.flush()
    tasks = [
        TaskRecord(task_id="TASK-DEMO-001", project_id="IMP-GOD-014", title="Szállítólevél pótlása", description="A beszállítói számla kifizetése dokumentumhiány miatt blokkolt.", assignee="owner@imperial.local", due_at=now-timedelta(days=1), priority="critical", status="open", executive_relevance=True),
        TaskRecord(task_id="TASK-DEMO-002", project_id="IMP-POMAZ-001", title="Ügyféldöntés visszaigazolása", description="A gépészeti csomag módosítása öt napja döntésre vár.", assignee="owner@imperial.local", due_at=now+timedelta(hours=5), priority="high", status="open", executive_relevance=True),
        TaskRecord(task_id="TASK-DEMO-003", project_id="IMP-FONYOD-011", title="Pótmunka-ajánlat felülvizsgálata", description="Támfal- és tereprendezési teljesítés összevetése a friss dokumentumokkal.", assignee="owner@imperial.local", due_at=now+timedelta(days=2), priority="normal", status="in_progress", executive_relevance=False),
    ]
    db.add_all(tasks)
    events = [
        EventRecord(event_id="EVT-DEMO-001", dedupe_key="DEMO-DELIVERY-GOD", project_id="IMP-GOD-014", source_module="procurement", event_type="DELIVERY_NOTE_MISSING", object_type="Delivery", object_id="DEL-GOD-114", severity="critical", status="open", financial_impact_huf=Decimal("4850000"), deadline_impact_days=9, responsible="Beszerzés", next_action="Szállítólevél és teljesítménynyilatkozat bekérése", executive_relevance=True, payload_json=json.dumps({"summary":"Fizetési blokk dokumentumhiány miatt"}), occurred_at=now-timedelta(hours=2)),
        EventRecord(event_id="EVT-DEMO-002", dedupe_key="DEMO-CUSTOMER-POMAZ", project_id="IMP-POMAZ-001", source_module="myimperial", event_type="CUSTOMER_DECISION_OVERDUE", severity="high", status="open", financial_impact_huf=Decimal("1900000"), deadline_impact_days=5, responsible="Értékesítés", next_action="Ügyfél megkeresése és döntés rögzítése", executive_relevance=True, payload_json=json.dumps({"summary":"Gépészeti csomag döntése késik"}), occurred_at=now-timedelta(hours=8)),
    ]
    db.add_all(events)
    facts = [
        ProjectFact(project_id="IMP-POMAZ-001", source_module="contract_generator", fact_key="approved_revenue", value_json=json.dumps(69400000)),
        ProjectFact(project_id="IMP-POMAZ-001", source_module="finance", fact_key="received_customer_payments", value_json=json.dumps(24290000)),
        ProjectFact(project_id="IMP-POMAZ-001", source_module="finance", fact_key="forecast_margin_percent", value_json=json.dumps(36.8)),
        ProjectFact(project_id="IMP-GOD-014", source_module="procurement", fact_key="committed_total", value_json=json.dumps(18450000)),
        ProjectFact(project_id="IMP-GOD-014", source_module="finance", fact_key="blocked_supplier_payment", value_json=json.dumps(4850000)),
    ]
    db.add_all(facts)
    documents = [
        WorkspaceDocument(document_id="DOC-DEMO-001", project_id="IMP-POMAZ-001", title="Jóváhagyott kivitelezési szerződés", category="contract", source_system="google_drive", source_url="https://drive.google.com/", version_label="v1.0", approval_status="approved", verification_status="verified", confidentiality="confidential", owner="Jogi / operáció", extracted_summary="69,4 millió Ft szerződéses értékű, téglatechnológiás családi ház kivitelezési szerződése."),
        WorkspaceDocument(document_id="DOC-DEMO-002", project_id="IMP-GOD-014", title="Szerkezetépítési szállítólevél – hiányos", category="delivery_note", source_system="google_drive", source_url="https://drive.google.com/", version_label="beérkezett", approval_status="pending_review", verification_status="unverified", owner="Beszerzés", extracted_summary="A dokumentum nem tartalmazza az átvett mennyiséget igazoló aláírást."),
        WorkspaceDocument(document_id="DOC-DEMO-003", project_id="IMP-FONYOD-011", title="Támfalak és tereprendezés tervcsomag", category="plan", source_system="google_drive", source_url="https://drive.google.com/", version_label="2024-07", approval_status="approved", verification_status="verified", owner="Műszaki előkészítés", extracted_summary="Felső és alsó támfalak, valamint a már elkészült tereprendezési munkák tervdokumentációja."),
    ]
    db.add_all(documents)



def seed_operations_demo(db: Session) -> None:
    if settings.environment.lower() != "development":
        return
    if db.scalar(select(PMPhase).limit(1)):
        return
    now = datetime.now(timezone.utc)
    phases = [
        PMPhase(phase_id="PH-GOD-01", project_id="IMP-GOD-014", phase_key="structure", name="Szerkezetépítés", sequence=30, status="in_progress", planned_start=now-timedelta(days=18), planned_end=now+timedelta(days=12), actual_start=now-timedelta(days=16), progress_pct=58, readiness_status="passed", owner="Projektvezetés", source_object_id="PM-PH-201", source_version="1.0"),
        PMPhase(phase_id="PH-GOD-02", project_id="IMP-GOD-014", phase_key="roof", name="Tetőszerkezet", sequence=40, status="planned", planned_start=now+timedelta(days=10), planned_end=now+timedelta(days=28), progress_pct=0, readiness_status="at_risk", owner="Projektvezetés", source_object_id="PM-PH-202", source_version="1.0"),
        PMPhase(phase_id="PH-POM-01", project_id="IMP-POMAZ-001", phase_key="design", name="Tervezés és döntések", sequence=10, status="in_progress", planned_start=now-timedelta(days=35), planned_end=now+timedelta(days=9), actual_start=now-timedelta(days=32), progress_pct=72, readiness_status="at_risk", owner="Műszaki előkészítés", source_object_id="PM-PH-101", source_version="1.0"),
        PMPhase(phase_id="PH-FON-01", project_id="IMP-FONYOD-011", phase_key="change_scope", name="Pótmunka-előkészítés", sequence=10, status="in_progress", planned_start=now-timedelta(days=5), planned_end=now+timedelta(days=6), actual_start=now-timedelta(days=4), progress_pct=45, readiness_status="passed", owner="Műszaki előkészítés", source_object_id="PM-PH-301", source_version="1.0"),
    ]
    db.add_all(phases)
    packages = [
        PMWorkPackage(work_package_id="WP-GOD-FOUND", project_id="IMP-GOD-014", phase_id="PH-GOD-01", name="Alapozás és fogadószint", trade="Szerkezet", assignee="Szerkezetépítő brigád", status="done", progress_pct=100, planned_start=now-timedelta(days=18), planned_end=now-timedelta(days=5), actual_start=now-timedelta(days=17), actual_end=now-timedelta(days=4), budget_huf=Decimal("9700000"), committed_huf=Decimal("9450000"), actual_huf=Decimal("9520000"), source_object_id="PM-WP-401", source_version="1.0"),
        PMWorkPackage(work_package_id="WP-GOD-WALL", project_id="IMP-GOD-014", phase_id="PH-GOD-01", name="Falszerkezet és áthidalók", trade="Kőműves", assignee="Falazó brigád", status="in_progress", progress_pct=61, planned_start=now-timedelta(days=4), planned_end=now+timedelta(days=7), actual_start=now-timedelta(days=3), budget_huf=Decimal("12800000"), committed_huf=Decimal("12100000"), actual_huf=Decimal("7300000"), blocked=True, block_reason="Teljesítménynyilatkozat és e-napló bizonyíték hiányzik.", next_action="Beszállítói dokumentumok pótlása", source_object_id="PM-WP-402", source_version="1.0"),
        PMWorkPackage(work_package_id="WP-GOD-ROOF", project_id="IMP-GOD-014", phase_id="PH-GOD-02", name="Tetőszerkezet és fedés", trade="Ács / tetőfedő", assignee="Ács partner", status="planned", progress_pct=0, planned_start=now+timedelta(days=10), planned_end=now+timedelta(days=28), budget_huf=Decimal("14900000"), committed_huf=Decimal("0"), actual_huf=Decimal("0"), blocked=False, next_action="Tenderlezárás és kapacitáslekötés", source_object_id="PM-WP-403", source_version="1.0"),
        PMWorkPackage(work_package_id="WP-POM-MEP", project_id="IMP-POMAZ-001", phase_id="PH-POM-01", name="Gépészeti csomag véglegesítése", trade="Gépészet", assignee="Tervező / ügyfél", status="in_progress", progress_pct=70, planned_start=now-timedelta(days=10), planned_end=now+timedelta(days=3), actual_start=now-timedelta(days=9), budget_huf=Decimal("4600000"), committed_huf=Decimal("0"), actual_huf=Decimal("320000"), blocked=True, block_reason="Ügyféldöntés késik.", next_action="Döntés rögzítése a MyImperialban", source_object_id="PM-WP-201", source_version="1.0"),
        PMWorkPackage(work_package_id="WP-FON-CHANGE", project_id="IMP-FONYOD-011", phase_id="PH-FON-01", name="Támfal és tereprendezés pótmunka", trade="Földmunka / vasbeton", assignee="Műszaki előkészítés", status="in_progress", progress_pct=45, planned_start=now-timedelta(days=5), planned_end=now+timedelta(days=6), actual_start=now-timedelta(days=4), budget_huf=Decimal("6900000"), committed_huf=Decimal("0"), actual_huf=Decimal("0"), next_action="Elkészült munkák levonása a scope-ból", source_object_id="PM-WP-301", source_version="1.0"),
    ]
    db.add_all(packages)
    gates=[]
    for wp in packages:
        for code,label in [("approved_plan","Jóváhagyott terv/revízió"),("predecessor","Előző munkafázis lezárva"),("capacity","Brigád és kapacitás lekötve"),("material","Anyag és logisztika biztosítva"),("site","Munkaterület átadható")]:
            passed = wp.status in {"done","in_progress"} and not (wp.work_package_id=="WP-GOD-WALL" and code=="material")
            gates.append(PMGateCheck(gate_id=f"GATE-{wp.work_package_id}-{code}"[:120], project_id=wp.project_id, work_package_id=wp.work_package_id, gate_code=code, label=label, status="passed" if passed else "pending", checked_by="Projektvezetés" if passed else None, checked_at=now-timedelta(days=2) if passed else None))
    db.add_all(gates)
    db.add(SiteDailyReport(report_id="RPT-GOD-DEMO", project_id="IMP-GOD-014", report_date=now-timedelta(hours=5), reporter="Projektvezető", weather="Napos, 27 °C", workers_total=7, summary="Falazás a nappali és hálózóna tengelyein; áthidalók előkészítve.", blockers="A beszállítói teljesítménynyilatkozat és az aláírt szállítólevél még hiányzik.", safety_status="ok", quality_status="attention", status="submitted", evidence_url="https://drive.google.com/"))
    db.add(SiteIssue(issue_id="ISS-GOD-DEMO", project_id="IMP-GOD-014", report_id="RPT-GOD-DEMO", work_package_id="WP-GOD-WALL", issue_type="documentation", severity="critical", title="Anyagdokumentáció hiányos", description="A falazóanyag teljesítménynyilatkozata és e-napló feltöltési bizonyítéka hiányzik.", responsible="Beszerzés / PM", due_at=now+timedelta(days=1), status="open", financial_impact_huf=Decimal("4850000"), deadline_impact_days=3))
    orders=[
        ProcurementOrderProjection(order_id="ORD-GOD-101", project_id="IMP-GOD-014", work_package_id="WP-GOD-WALL", supplier_name="Minta Építőanyag Kft.", item_summary="Falazóanyag és áthidalók", status="ordered", total_huf=Decimal("4850000"), delivery_due=now-timedelta(days=1), delivery_status="received_with_variance", document_status="missing", variance_status="variance", source_object_id="PROC-ORD-101", source_url="https://drive.google.com/", source_version="1.0"),
        ProcurementOrderProjection(order_id="ORD-GOD-102", project_id="IMP-GOD-014", work_package_id="WP-GOD-ROOF", supplier_name="Tető Partner Kft.", item_summary="Tetőfa és fedési rendszer", status="approved", total_huf=Decimal("8900000"), delivery_due=now+timedelta(days=9), delivery_status="not_started", document_status="pending", variance_status="none", source_object_id="PROC-ORD-102", source_version="1.0"),
    ]
    db.add_all(orders)
    db.add(DeliveryNoteProjection(delivery_note_id="DN-GOD-101", order_id="ORD-GOD-101", project_id="IMP-GOD-014", note_number="SZL-2026-0719-01", source_url="https://drive.google.com/", received_at=now-timedelta(days=1), receiver="Projektvezető", item_summary="Falazóanyag", ordered_quantity=Decimal("36"), received_quantity=Decimal("34"), unit="raklap", actual_specification="Jóváhagyott típus", quality_status="accepted", damage_or_shortage="2 raklap hiány", plan_match="variance", document_status="incomplete", performance_declaration_status="pending", elog_evidence_status="pending"))
    db.add(MaterialLot(lot_id="LOT-GOD-101", project_id="IMP-GOD-014", delivery_note_id="DN-GOD-101", material="Falazóanyag", received_quantity=Decimal("34"), current_quantity=Decimal("21"), unit="raklap", storage_location="Északi depó", planned_use_location="Falszerkezet", actual_use_location="Falszerkezet", custodian="Falazó brigád", weather_protection="adequate", evidence_url="https://drive.google.com/", status="in_stock"))
    partner_access = PartnerFieldAccess(access_id="PFA-GOD-DEMO", company_name="Minta Falazó Kft.", company_tax_number="12345678-2-41", contact_name="Nagy László brigádvezető", contact_phone="+36 30 000 0000", project_id="IMP-GOD-014", work_package_id="WP-GOD-WALL", access_code_hash=hash_password("654321"), active=True, valid_from=now-timedelta(days=2), valid_until=now+timedelta(days=60), attendance_required=True, can_report_changes=True)
    db.add(partner_access)
    db.add_all([
        PartnerWorker(worker_id="PWR-GOD-001", access_id="PFA-GOD-DEMO", name="Nagy László", role="Brigádvezető", active=True),
        PartnerWorker(worker_id="PWR-GOD-002", access_id="PFA-GOD-DEMO", name="Kiss József", role="Kőműves", active=True),
        PartnerWorker(worker_id="PWR-GOD-003", access_id="PFA-GOD-DEMO", name="Szabó Péter", role="Segédmunkás", active=True),
    ])
    db.add(MaterialMovement(movement_id="MOV-GOD-101", lot_id="LOT-GOD-101", project_id="IMP-GOD-014", movement_type="use", quantity=Decimal("13"), from_location="Északi depó", to_location="Falszerkezet", responsible="Falazó brigád", occurred_at=now-timedelta(hours=8), note="Napi felhasználás"))
    db.add(MaterialUsageControl(control_id="USE-GOD-101", project_id="IMP-GOD-014", work_package_id="WP-GOD-WALL", lot_id="LOT-GOD-101", subcontractor="Falazó brigád", planned_quantity=Decimal("30"), waste_pct=Decimal("5"), allowed_quantity=Decimal("31.5"), actual_quantity=Decimal("33"), unit="raklap", unit_cost_huf=Decimal("132000"), damage_huf=Decimal("0"), decision_status="review_required", contractual_basis="Alvállalkozói szerződés anyagfelelősségi pontja"))

def seed_commercial_integration(db: Session) -> None:
    records = [
        {
            "discovery_id": "DISC-COMMERCIAL-CONTRACT-INTEGRATION-V1",
            "requested_capability": "Contract Generator Workspace- és CRM-integráció",
            "requested_module_key": "commercial_integration",
            "searched_terms_json": json.dumps(["Imperial Contract Generator", "contract_generator", "szerződésgenerátor", "v0.4"], ensure_ascii=False),
            "candidate_artifacts_json": json.dumps([{"drive_file_id": "1kL92i1Z8Zk5V_1W4wmTbJB0pRAVVhSHV", "title": "Imperial_Contract_Generator_v0.4.zip", "sha256": "3634378bbc90f885b54e787f6de06e57cabf4d6a594e1351463388814e191a42"}], ensure_ascii=False),
            "canonical_module_key": "contract_generator",
            "canonical_object_owner": "Jogi / operáció",
            "source_version": "0.4.0",
            "source_sha256": "3634378bbc90f885b54e787f6de06e57cabf4d6a594e1351463388814e191a42",
            "decision": "integrate",
            "implementation_gap": "A meglévő motor változtatás nélküli bekötése a Workspace-be, dokumentumtárba, CRM-eseményláncba és aláírási státuszfolyamba.",
        },
        {
            "discovery_id": "DISC-COMMERCIAL-CHANGE-INTEGRATION-V1",
            "requested_capability": "ChangeControl közös Workspace- és eseményintegráció",
            "requested_module_key": "commercial_integration",
            "searched_terms_json": json.dumps(["ChangeControl", "pótmunka", "változtatáskezelő", "v0.1"], ensure_ascii=False),
            "candidate_artifacts_json": json.dumps([{"drive_file_id": "1h-_5X0-zHZmVSKYdg5t13rZQQktZRHlcXYWUZYyvXCo", "title": "ChangeControl v0.1 – pótmunka- és változtatáskezelő"}], ensure_ascii=False),
            "canonical_module_key": "change_control",
            "canonical_object_owner": "Projektvezetés",
            "source_version": "0.1.0",
            "source_sha256": None,
            "decision": "integrate",
            "implementation_gap": "A forrásmodul állapotainak, ügyfél- és partnerintake eseményeinek megjelenítése és továbbítása; új ár-, fedezet- vagy jóváhagyási motor létrehozása nélkül.",
        },
    ]
    for data in records:
        if db.scalar(select(DevelopmentDiscoveryRecord).where(DevelopmentDiscoveryRecord.discovery_id == data["discovery_id"])):
            continue
        db.add(DevelopmentDiscoveryRecord(
            **data, status="approved", requested_by="owner_instruction", reviewed_by="owner_instruction",
            reviewed_at=datetime.now(timezone.utc),
        ))
    if settings.demo_runtime_enabled and not db.scalar(select(ProjectObjectState).where(ProjectObjectState.source_module == "change_control", ProjectObjectState.object_id == "CHG-DEMO-001")):
        db.add(ProjectObjectState(
            project_id="IMP-FONYOD-011", source_module="change_control", object_type="Change", object_id="CHG-DEMO-001",
            status="customer_accepted", summary="Támfal és tereprendezés módosított scope – ügyfél által elfogadva; munkakezdési engedély még szükséges.",
            payload_json=json.dumps({"version": 2, "source_module_is_authoritative": True, "workspace_is_projection_only": True}, ensure_ascii=False),
            last_event_id="EVT-CHG-DEMO-001",
        ))


def seed_content_quality_sources(db: Session) -> None:
    source_url = "https://drive.google.com/drive/folders/0AGVzuRnGAaYZUk9PVA"
    valid_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_until = datetime(2027, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    sources = [
        ("imperial-brand-master", "brand_master", "1.0", {}, 10),
        (
            "imperial-brand-voice",
            "brand_voice_profile",
            "1.0",
            {
                "addressing": "formal",
                "required_concepts": [
                    "fix ár",
                    "fix határidő",
                    "rögzített műszaki tartalom",
                ],
                "forbidden_phrases": [
                    "brutális akció",
                    "őrületes kedvezmény",
                    "olcsó csoda",
                ],
            },
            10,
        ),
        ("imperial-conversion-architecture", "conversion_guide", "1.5", {}, 10),
        ("imperial-full-design-system", "design_system", "1.1", {}, 10),
        ("imperial-channel-rules", "channel_rules", "1.0", {}, 10),
        (
            "OFF-IMP-V1",
            "offer_version",
            "1.0",
            {"record_id": "OFF-IMP-V1", "scope": "approved-pilot"},
            10,
        ),
        (
            "PS-IMP-2026-07",
            "price_snapshot",
            "2026-07",
            {"record_id": "PS-IMP-2026-07", "vat_scope": "validated"},
            10,
        ),
        (
            "TV-IMP-V1",
            "terms_version",
            "1.0",
            {"record_id": "TV-IMP-V1", "status": "approved"},
            10,
        ),
        (
            "HP-IMP-126",
            "house_plan",
            "3",
            {"record_id": "HP-IMP-126", "gross_area_m2": 126},
            10,
        ),
        (
            "CLM-IMP-FIXED-SCOPE",
            "claim",
            "1.0",
            {"record_id": "CLM-IMP-FIXED-SCOPE"},
            10,
        ),
        (
            "PRF-IMP-CONTRACT",
            "proof",
            "1.0",
            {"record_id": "PRF-IMP-CONTRACT"},
            10,
        ),
        (
            "VIS-IMP-126-HERO",
            "visual_rights",
            "1.0",
            {"record_id": "VIS-IMP-126-HERO", "rights_status": "approved"},
            10,
        ),
    ]
    for source_key, source_type, version, payload, priority in sources:
        exists = db.scalar(
            select(CopySourceRecord).where(
                CopySourceRecord.source_key == source_key,
                CopySourceRecord.version == version,
            )
        )
        if exists:
            continue
        payload_json = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        db.add(
            CopySourceRecord(
                source_key=source_key,
                source_type=source_type,
                brand_id="imperial",
                version=version,
                priority=priority,
                status="approved",
                approved=True,
                valid_from=valid_from,
                valid_until=valid_until,
                source_url=source_url,
                content_hash=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                payload_json=payload_json,
            )
        )


def retire_seeded_content_quality_sources(db: Session) -> None:
    """Fail closed in production: the synthetic pilot registry is never authoritative."""
    seeded_versions = {
        ("imperial-brand-master", "1.0"),
        ("imperial-brand-voice", "1.0"),
        ("imperial-conversion-architecture", "1.5"),
        ("imperial-full-design-system", "1.1"),
        ("imperial-channel-rules", "1.0"),
        ("OFF-IMP-V1", "1.0"),
        ("PS-IMP-2026-07", "2026-07"),
        ("TV-IMP-V1", "1.0"),
        ("HP-IMP-126", "3"),
        ("CLM-IMP-FIXED-SCOPE", "1.0"),
        ("PRF-IMP-CONTRACT", "1.0"),
        ("VIS-IMP-126-HERO", "1.0"),
    }
    pilot_url = "https://drive.google.com/drive/folders/0AGVzuRnGAaYZUk9PVA"
    rows = db.scalars(select(CopySourceRecord).where(CopySourceRecord.source_url == pilot_url)).all()
    for row in rows:
        if (row.source_key, row.version) in seeded_versions:
            row.status = "retired"
            row.approved = False


def seed_database(db: Session) -> None:
    demo_emails = {
        role.id: (
            "owner@imperial.local"
            if role.id == "owner"
            else f"{role.id}@imperial.local"
        )
        for role in ROLE_DEFINITIONS
    }
    if not settings.demo_runtime_enabled:
        for user in db.scalars(
            select(User).where(User.email.in_(tuple(demo_emails.values())))
        ).all():
            user.active = False
    else:
        for role in ROLE_DEFINITIONS:
            email = demo_emails[role.id]
            user = db.scalar(select(User).where(User.email == email))
            if not user:
                db.add(
                    User(
                        email=email,
                        password_hash=DEMO_PASSWORD_HASH,
                        name=DEMO_USER_NAMES[role.id],
                        role=role.id,
                    )
                )
            else:
                user.name = DEMO_USER_NAMES[role.id]
                user.role = role.id
                user.active = True
    canonical_module_ids = {module[0] for module in MODULES}
    existing_modules = db.scalars(select(ModuleRegistry)).all()
    existing_by_key = {module.module_key: module for module in existing_modules}
    for module in existing_modules:
        canonical_key = LEGACY_MODULE_ALIASES.get(module.module_key)
        if canonical_key and canonical_key not in existing_by_key:
            module.module_key = canonical_key
            existing_by_key[canonical_key] = module
        elif module.module_key not in canonical_module_ids:
            db.delete(module)
    db.flush()
    verified_at = datetime.now(timezone.utc)
    if settings.demo_runtime_enabled:
        module_runtime = {
            "lifecycle_status": "test_ready",
            "integration_status": "healthy",
            "api_base_url": "/api/demo",
            "last_heartbeat_at": verified_at,
            "last_integration_test_at": verified_at,
            "last_integration_test_status": "passed",
            "notes": "Shared platform-core synthetic adapter; external writes disabled.",
        }
    else:
        module_runtime = {
            "lifecycle_status": "registered",
            "integration_status": "not_connected",
            "api_base_url": None,
            "last_heartbeat_at": None,
            "last_integration_test_at": None,
            "last_integration_test_status": None,
            "notes": "Production adapter and evidence-backed integration test required.",
        }
    for key, name, version, owner, criticality in MODULES:
        health_url = (
            f"/api/demo/modules/{key}" if settings.demo_runtime_enabled else None
        )
        module = db.scalar(select(ModuleRegistry).where(ModuleRegistry.module_key == key))
        if not module:
            db.add(ModuleRegistry(
                module_key=key,
                name=name,
                version=version,
                owner=owner,
                criticality=criticality,
                lifecycle_status=module_runtime["lifecycle_status"],
                integration_status=module_runtime["integration_status"],
                api_base_url=module_runtime["api_base_url"],
                health_url=health_url,
                last_heartbeat_at=module_runtime["last_heartbeat_at"],
                last_integration_test_at=module_runtime["last_integration_test_at"],
                last_integration_test_status=module_runtime["last_integration_test_status"],
                notes=module_runtime["notes"],
            ))
        else:
            module.name = name
            module.version = version
            module.owner = owner
            module.criticality = criticality
            module.lifecycle_status = module_runtime["lifecycle_status"]
            module.integration_status = module_runtime["integration_status"]
            module.api_base_url = module_runtime["api_base_url"]
            module.health_url = health_url
            module.last_heartbeat_at = module_runtime["last_heartbeat_at"]
            module.last_integration_test_at = module_runtime["last_integration_test_at"]
            module.last_integration_test_status = module_runtime["last_integration_test_status"]
            module.notes = module_runtime["notes"]
    current_environment = settings.environment.lower()
    for key, name in (("development", "Fejlesztés"), ("uat", "UAT"), ("production", "Production")):
        environment = db.scalar(
            select(EnvironmentRecord).where(EnvironmentRecord.environment_key == key)
        )
        status = "active" if key == current_environment else "planned"
        if not environment:
            db.add(EnvironmentRecord(environment_key=key, name=name, status=status))
        else:
            environment.name = name
            environment.status = status
    for source_key, name, source_type, domain_scope, connector_reference in IMPORT_SOURCES:
        if not db.scalar(select(ImportDataSource).where(ImportDataSource.source_key == source_key)):
            db.add(ImportDataSource(
                source_key=source_key, name=name, source_type=source_type, domain_scope=domain_scope,
                connector_reference=connector_reference, owner="Adatgazda", enabled=True,
            ))
    for source in CALCULATION_SOURCES:
        if not db.scalar(select(CalculationSourceRegistry).where(CalculationSourceRegistry.source_key == source["source_key"])):
            db.add(CalculationSourceRegistry(**source))
    if not db.scalar(select(MailSendingDomain).where(MailSendingDomain.domain_key == "imperial_tender")):
        db.add(MailSendingDomain(
            domain_key="imperial_tender", domain_name="tender.imperialholding.hu",
            from_email="meghivas@tender.imperialholding.hu", from_name="Imperial Holding Tender",
            provider="provider_not_configured", spf_status="pending", dkim_status="pending",
            dmarc_status="pending", tracking_domain_status="pending", warmup_status="not_started",
            max_hourly_rate=100, active=True,
        ))
    seed_canonical_discoveries(db, MODULES)
    seed_commercial_integration(db)
    if settings.demo_runtime_enabled:
        seed_content_quality_sources(db)
    else:
        retire_seeded_content_quality_sources(db)
    seed_workspace_demo(db)
    seed_operations_demo(db)
    db.commit()
