"""Create idempotent, clearly marked BuildConfig UAT scenarios."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import BuildConfigCase, HouseBuildCase, HouseBuildVariant
from app.services.buildconfig import (
    case_detail,
    create_case,
    create_revision,
    release_case,
    review_gate,
    submit_case,
)

RELEASE_PROJECT = "PRJ-UAT-PLOTCHECK-FIT"
STOP_PROJECT = "PRJ-UAT-HOUSEBUILD-DUPLICATE"


def user(email: str, role: str):
    return SimpleNamespace(email=email, role=role)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def binding(db, project_id: str) -> tuple[HouseBuildCase, HouseBuildVariant]:
    case = db.scalar(
        select(HouseBuildCase).where(
            HouseBuildCase.project_id == project_id,
            HouseBuildCase.selected_variant_id.is_not(None),
        )
    )
    if case is None or not case.selected_variant_id:
        raise RuntimeError(
            "A BuildConfig UAT előtt futtatni kell a PlotCheck és HouseBuild UAT seedeket."
        )
    variant = db.scalar(
        select(HouseBuildVariant).where(HouseBuildVariant.variant_id == case.selected_variant_id)
    )
    if variant is None:
        raise RuntimeError("A BuildConfig UAT HousePlan-változata hiányzik.")
    return case, variant


def payload(
    case: HouseBuildCase,
    variant: HouseBuildVariant,
    *,
    title: str,
    options: list[str],
) -> dict:
    requirements = json.loads(case.requirement_json)
    return {
        "project_id": case.project_id,
        "title": title,
        "housebuild_case_id": case.case_id,
        "housebuild_variant_id": variant.variant_id,
        "brand": "imperial",
        "technology": requirements.get("technology") or "Danish Fabrik",
        "completion_level": "Kulcsrakész",
        "package": "Közép",
        "gross_area_m2": str(variant.gross_area_m2),
        "vat_rate": "0.05",
        "options": options,
        "planned_start": "2026-09-01",
        "promised_delivery": "2027-09-01",
        "crew_count": 2,
        "weekly_capacity_m2": "30",
    }


def ensure_release_case(db) -> dict:
    existing = db.scalar(
        select(BuildConfigCase).where(BuildConfigCase.project_id == RELEASE_PROJECT)
    )
    if existing is None:
        housebuild, variant = binding(db, RELEASE_PROJECT)
        detail = create_case(
            db,
            payload(
                housebuild,
                variant,
                title="SZINTETIKUS UAT – kiadott BuildConfig",
                options=["solar_ready", "heat_pump_upgrade"],
            ),
            user("uat-buildconfig-author@imperial.local", "technical-prep"),
        )
    else:
        detail = case_detail(db, existing.case_id)
    if detail["status"] == "approved":
        return detail
    if detail["status"] == "calculated":
        if any(gate["decision"] == "rejected" for gate in detail["versions"][0]["gates"]):
            housebuild, variant = binding(db, RELEASE_PROJECT)
            detail = create_revision(
                db,
                detail["case_id"],
                payload(
                    housebuild,
                    variant,
                    title="SZINTETIKUS UAT – kiadott BuildConfig",
                    options=["solar_ready", "heat_pump_upgrade"],
                ),
                user("uat-buildconfig-author@imperial.local", "technical-prep"),
            )
        detail = submit_case(
            db,
            detail["case_id"],
            user("uat-buildconfig-author@imperial.local", "technical-prep"),
        )
    for gate_key, reviewer_role in (("technical", "designer"), ("finance", "finance")):
        reviewer_email = f"uat-buildconfig-{gate_key}@imperial.local"
        reference = f"document://UAT/BUILDCONFIG/{gate_key.upper()}"
        detail = review_gate(
            db,
            detail["case_id"],
            gate_key,
            {
                "decision": "approved",
                "note": (
                    f"SZINTETIKUS UAT {gate_key} ellenőrzés; valódi döntésre nem használható."
                ),
                "evidence_ref": reference,
                "evidence_sha256": digest(f"{detail['case_id']}:{gate_key}:{reference}"),
            },
            user(reviewer_email, reviewer_role),
        )
    return release_case(
        db,
        detail["case_id"],
        "SZINTETIKUS UAT kiadás; ajánlati vagy szerződéses döntésre nem használható.",
        user("uat-buildconfig-final@imperial.local", "managing-director"),
    )


def ensure_stop_case(db) -> dict:
    existing = db.scalar(select(BuildConfigCase).where(BuildConfigCase.project_id == STOP_PROJECT))
    if existing is not None:
        return case_detail(db, existing.case_id)
    housebuild, variant = binding(db, STOP_PROJECT)
    return create_case(
        db,
        payload(
            housebuild,
            variant,
            title="SZINTETIKUS UAT – kompatibilitási STOP",
            options=["green_roof"],
        ),
        user("uat-buildconfig-stop@imperial.local", "technical-prep"),
    )


def main() -> None:
    with SessionLocal() as db:
        released = ensure_release_case(db)
        stopped = ensure_stop_case(db)
        stop_gate = next(
            gate for gate in stopped["versions"][0]["gates"] if gate["gate_key"] == "compatibility"
        )
        print(
            f"{released['project_id']} {released['case_id']} {released['status']} "
            f"{released['current_version_id']} {released['final_report_document_id']}"
        )
        print(
            f"{stopped['project_id']} {stopped['case_id']} {stopped['status']} "
            f"compatibility={stop_gate['decision']}"
        )


if __name__ == "__main__":
    main()
