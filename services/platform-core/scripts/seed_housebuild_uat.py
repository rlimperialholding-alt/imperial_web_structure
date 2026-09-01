"""Create idempotent, clearly marked HouseBuild UAT scenarios."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from types import SimpleNamespace

from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.database import SessionLocal
from app.models import HouseBuildCase, PlanCheckCase, PlotCheckCase, TechnicalCase
from app.services.house_catalog import public_catalog
from app.services.housebuild import (
    create_case,
    release_case,
    review_gate,
    select_variant,
    submit_case,
)
from app.services.plancheck import (
    create_case as create_plancheck_case,
)
from app.services.plancheck import (
    finalize_case as finalize_plancheck_case,
)
from app.services.plancheck import (
    review_gate as review_plancheck_gate,
)
from app.services.plancheck import (
    submit_review as submit_plancheck_review,
)
from app.services.plancheck import (
    upload_document as upload_plancheck_document,
)

RELEASE_PROJECT = "PRJ-UAT-PLOTCHECK-FIT"
DUPLICATE_PROJECT = "PRJ-UAT-HOUSEBUILD-DUPLICATE"


def user(email: str, role: str) -> SimpleNamespace:
    return SimpleNamespace(email=email, role=role)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def synthetic_pdf(label: str) -> bytes:
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(40, 800, f"SZINTETIKUS UAT - {label}; valodi dontesre nem hasznalhato.")
    pdf.save()
    return stream.getvalue()


def ensure_plancheck(db) -> str:
    existing = db.scalar(
        select(PlanCheckCase).where(
            PlanCheckCase.project_id == RELEASE_PROJECT,
            PlanCheckCase.title == "SZINTETIKUS UAT – HouseBuild PlanCheck előfeltétel",
        )
    )
    if existing:
        if existing.status != "sendable":
            raise RuntimeError("A meglévő HouseBuild UAT PlanCheck nem SENDABLE állapotú.")
        return existing.case_id
    detail, token = create_plancheck_case(
        db,
        project_id=RELEASE_PROJECT,
        title="SZINTETIKUS UAT – HouseBuild PlanCheck előfeltétel",
        contact_name="UAT Teszt",
        contact_email="uat-housebuild@example.invalid",
        intake={"building_type": "synthetic-uat", "gross_area_m2": "126"},
        actor="uat-plancheck-author@imperial.local",
    )
    case_id = detail["case"].case_id
    for category in ("site_plan", "floor_plan", "elevations", "sections", "technical_description"):
        upload_plancheck_document(
            db,
            token=token,
            category=category,
            file_name=f"{category}.pdf",
            mime_type="application/pdf",
            content=synthetic_pdf(category),
            uploader="uat-plancheck-uploader@imperial.local",
        )
    submit_plancheck_review(db, case_id, "uat-plancheck-uploader@imperial.local")
    reviewers = {
        "input": user("uat-pc-input@imperial.local", "project-manager"),
        "engineering": user("uat-pc-engineering@imperial.local", "designer"),
        "commercial": user("uat-pc-commercial@imperial.local", "sales"),
        "finance": user("uat-pc-finance@imperial.local", "finance"),
        "executive": user("uat-pc-executive@imperial.local", "managing-director"),
    }
    for gate_key, reviewer in reviewers.items():
        review_plancheck_gate(
            db,
            case_id,
            gate_key=gate_key,
            decision="approve",
            note=f"SZINTETIKUS UAT {gate_key} PlanCheck kapu jóváhagyva.",
            user=reviewer,
        )
    finalize_plancheck_case(
        db,
        case_id,
        outcome="sendable",
        note="SZINTETIKUS UAT SENDABLE eredmény; valódi döntésre nem használható.",
        user=user("uat-pc-final@imperial.local", "owner"),
    )
    return case_id


def ensure_dependencies(db) -> tuple[str, str, str]:
    plot = db.scalar(
        select(PlotCheckCase).where(
            PlotCheckCase.project_id == RELEASE_PROJECT,
            PlotCheckCase.status.in_(("fit", "fit_with_conditions")),
        )
    )
    if plot is None:
        raise RuntimeError(
            "A HouseBuild UAT előtt futtatni kell a seed_plotcheck_uat.py szkriptet."
        )
    config_id = "CFG-UAT-HOUSEBUILD"
    if db.scalar(select(TechnicalCase).where(TechnicalCase.case_id == config_id)) is None:
        db.add(
            TechnicalCase(
                case_id=config_id,
                module_key="buildconfig",
                project_id=RELEASE_PROJECT,
                title="SZINTETIKUS UAT – HouseBuild BuildConfig előfeltétel",
                status="approved",
                input_json='{"uat":true}',
                result_json='{"offer_eligible":true,"uat":true}',
                source_snapshot_json='{"source":"UAT-SYNTHETIC"}',
                created_by="uat-technical@imperial.local",
                approved_by="uat-finance@imperial.local",
                approved_at=datetime.now(UTC),
            )
        )
    db.commit()
    plan_id = ensure_plancheck(db)
    return plot.case_id, config_id, plan_id


def seed_released(db) -> dict:
    existing = db.scalar(select(HouseBuildCase).where(HouseBuildCase.project_id == RELEASE_PROJECT))
    if existing:
        from app.services.housebuild import case_detail

        return case_detail(db, existing.case_id)
    plot_id, config_id, plan_id = ensure_dependencies(db)
    source = max(public_catalog(db), key=lambda row: row["gross_area_m2"])
    detail = create_case(
        db,
        {
            "project_id": RELEASE_PROJECT,
            "title": "SZINTETIKUS UAT – kiadott kanonikus HousePlan",
            "source_house_id": source["house_id"],
            "rights_evidence_ref": "document://UAT/HOUSEBUILD/RIGHTS-v1",
            "rights_evidence_sha256": digest("SZINTETIKUS UAT HOUSEBUILD RIGHTS v1"),
            "desired_area_m2": "126",
            "technology": "Danish Fabrik",
            "bedrooms": 4,
            "bathrooms": 2,
            "floors": 1,
            "garage_spaces": 1,
            "roof_style": "nyeregtető",
            "facade_style": "kortárs",
            "orientation": "délkelet",
            "accessibility": False,
            "customization_notes": "KIZÁRÓLAG SZINTETIKUS UAT TESZTADAT.",
        },
        user("uat-housebuild-author@imperial.local", "technical-prep"),
    )
    eligible = next(
        variant
        for variant in detail["variants"]
        if all(item["decision"] != "fail" for item in variant["validations"])
    )
    detail = select_variant(
        db,
        detail["case_id"],
        eligible["variant_id"],
        user("uat-housebuild-author@imperial.local", "technical-prep"),
    )
    detail = submit_case(
        db, detail["case_id"], user("uat-housebuild-author@imperial.local", "technical-prep")
    )
    references = {
        "plotcheck": plot_id,
        "buildconfig": config_id,
        "plancheck": plan_id,
        "technical": "DOC-UAT-HOUSEBUILD-TECH-v1",
    }
    for gate_key, reference in references.items():
        detail = review_gate(
            db,
            detail["case_id"],
            gate_key,
            {
                "decision": "approved",
                "note": (
                    f"SZINTETIKUS UAT {gate_key} kapu ellenőrizve; valódi döntésre nem használható."
                ),
                "evidence_refs": [reference],
                "evidence_sha256": digest(f"{detail['case_id']}:{gate_key}:{reference}"),
            },
            user("uat-housebuild-reviewer@imperial.local", "designer"),
        )
    return release_case(
        db,
        detail["case_id"],
        "SZINTETIKUS UAT kiadás; üzleti, építészeti vagy kivitelezési döntésre nem használható.",
        user("uat-housebuild-final@imperial.local", "managing-director"),
    )


def seed_duplicate_stop(db, released: dict) -> dict:
    existing = db.scalar(
        select(HouseBuildCase).where(HouseBuildCase.project_id == DUPLICATE_PROJECT)
    )
    if existing:
        from app.services.housebuild import case_detail

        return case_detail(db, existing.case_id)
    requirements = released["requirements"]
    detail = create_case(
        db,
        {
            "project_id": DUPLICATE_PROJECT,
            "title": "SZINTETIKUS UAT – duplikációs STOP",
            "source_house_id": released["source_house_id"],
            "rights_evidence_ref": "document://UAT/HOUSEBUILD/RIGHTS-v1",
            "rights_evidence_sha256": released["rights_evidence_sha256"],
            "desired_area_m2": requirements["desired_area_m2"],
            "technology": requirements["technology"],
            "bedrooms": requirements["bedrooms"],
            "bathrooms": requirements["bathrooms"],
            "floors": requirements["floors"],
            "garage_spaces": requirements["garage_spaces"],
            "roof_style": requirements["roof_style"],
            "facade_style": requirements["facade_style"],
            "orientation": requirements["orientation"],
            "accessibility": requirements["accessibility"],
            "customization_notes": "KIZÁRÓLAG SZINTETIKUS UAT TESZTADAT.",
        },
        user("uat-housebuild-duplicate@imperial.local", "technical-prep"),
    )
    released_variant = next(
        item
        for item in released["variants"]
        if item["variant_id"] == released["selected_variant_id"]
    )
    matching = next(
        item
        for item in detail["variants"]
        if item["geometry_signature"] == released_variant["geometry_signature"]
    )
    return select_variant(
        db,
        detail["case_id"],
        matching["variant_id"],
        user("uat-housebuild-duplicate@imperial.local", "technical-prep"),
    )


def main() -> None:
    with SessionLocal() as db:
        released = seed_released(db)
        duplicate = seed_duplicate_stop(db, released)
        duplicate_gate = next(
            item for item in duplicate["gates"] if item["gate_key"] == "deduplication"
        )
        print(
            f"{released['project_id']} {released['case_id']} {released['status']} "
            f"{released['selected_variant_id']} {released['final_report_document_id']}"
        )
        print(
            f"{duplicate['project_id']} {duplicate['case_id']} {duplicate['status']} "
            f"deduplication={duplicate_gate['decision']}"
        )


if __name__ == "__main__":
    main()
