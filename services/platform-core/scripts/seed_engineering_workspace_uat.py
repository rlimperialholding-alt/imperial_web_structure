from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    EngineeringCase,
    EngineeringDeliverable,
    EngineeringFinding,
    EngineeringRevision,
    EngineeringTransmittal,
    ProjectFinanceCashflowLine,
    ProjectFinancePlan,
    TechnicalCase,
)
from app.schemas import (
    EngineeringCaseIn,
    EngineeringDeliverableIn,
    EngineeringFindingIn,
    EngineeringFindingResolutionIn,
    EngineeringRevisionIn,
    EngineeringRevisionReviewIn,
    EngineeringTransmittalAckIn,
    EngineeringTransmittalIn,
)
from app.services.engineering_workspace import (
    acknowledge_transmittal,
    approve_finding_resolution,
    complete_consultation,
    create_deliverable,
    create_engineering_case,
    create_finding,
    create_revision,
    issue_transmittal,
    mark_construction_ready,
    propose_finding_resolution,
    release_revision,
    review_revision,
    submit_revision,
)

PROJECT_ID = "ENGINEERING-SERVER-UAT"
DOCUMENT_ID = "DOC-ENGINEERING-SERVER-UAT-ARCH"
FINDING_FINGERPRINT = "PLANCHECK-ENGINEERING-SERVER-UAT-CRITICAL-001"


def _actor(role: str):
    return SimpleNamespace(role=role, email=f"{role}@imperial.local")


def _revision(version: str, digest: str, summary: str) -> EngineeringRevisionIn:
    return EngineeringRevisionIn(
        source_document_id=DOCUMENT_ID,
        source_version=version,
        source_url=f"https://drive.example/{DOCUMENT_ID}/{version}",
        file_name=f"{DOCUMENT_ID}-{version}.pdf",
        mime_type="application/pdf",
        file_size=4096,
        content_sha256=digest,
        change_summary=summary,
        metadata={"source": "controlled-server-uat", "immutable": True},
    )


def _print_result(db, case: EngineeringCase) -> None:
    deliverable = db.scalar(
        select(EngineeringDeliverable).where(
            EngineeringDeliverable.engineering_case_id == case.engineering_case_id,
            EngineeringDeliverable.deliverable_code == "ARCH-GA",
        )
    )
    revision = None
    if deliverable and deliverable.current_released_revision:
        revision = db.scalar(
            select(EngineeringRevision).where(
                EngineeringRevision.deliverable_id == deliverable.deliverable_id,
                EngineeringRevision.revision == deliverable.current_released_revision,
            )
        )
    finding = db.scalar(
        select(EngineeringFinding).where(
            EngineeringFinding.source_fingerprint == FINDING_FINGERPRINT
        )
    )
    transmittal = db.scalar(
        select(EngineeringTransmittal).where(
            EngineeringTransmittal.engineering_case_id == case.engineering_case_id,
            EngineeringTransmittal.purpose == "construction",
            EngineeringTransmittal.subject == "Építész kiviteli tervcsomag R02",
        )
    )
    print(
        {
            "project_id": PROJECT_ID,
            "engineering_case_id": case.engineering_case_id,
            "status": case.status,
            "readiness_version": case.readiness_version,
            "consultation_completed": case.consultation_completed_at is not None,
            "current_released_revision": revision.revision_label if revision else None,
            "revision_sha256": revision.content_sha256 if revision else None,
            "finding_status": finding.status if finding else None,
            "transmittal_status": transmittal.status if transmittal else None,
            "transmittal_sha256": transmittal.package_sha256 if transmittal else None,
            "readiness_blockers": case.readiness_blockers_json,
        }
    )


def main() -> None:
    with SessionLocal() as db:
        case = db.scalar(select(EngineeringCase).where(EngineeringCase.project_id == PROJECT_ID))
        if case and case.status == "construction_ready":
            _print_result(db, case)
            return

        case = create_engineering_case(
            db,
            EngineeringCaseIn(
                project_id=PROJECT_ID,
                title="Kontrollált Engineering Workspace szerver-UAT",
                lead_designer="designer@imperial.local",
                project_manager="project-manager@imperial.local",
                contract_date=date(2026, 8, 2),
            ),
            _actor("project-manager"),
        )
        if not case.consultation_completed_at:
            case = complete_consultation(db, PROJECT_ID, _actor("designer"))

        deliverable = create_deliverable(
            db,
            PROJECT_ID,
            EngineeringDeliverableIn(
                discipline="architecture",
                deliverable_code="ARCH-GA",
                title="Építész kiviteli tervcsomag",
                document_type="construction_plan",
                responsible="designer@imperial.local",
                due_at=datetime(2026, 9, 15, tzinfo=UTC),
                required=True,
            ),
            _actor("project-manager"),
        )

        rev1 = create_revision(
            db,
            deliverable.deliverable_id,
            _revision("V01", "1" * 64, "Első koordinációs tervkiadás."),
            _actor("designer"),
        )
        if rev1.status == "draft":
            rev1 = submit_revision(db, rev1.revision_id, _actor("designer"))
        if rev1.status == "review":
            rev1 = review_revision(
                db,
                rev1.revision_id,
                EngineeringRevisionReviewIn(
                    decision="approve",
                    note="A tervazonosító, tartalom és dokumentumhash ellenőrzött.",
                ),
                _actor("technical-prep"),
            )
        if rev1.status == "approved":
            rev1 = release_revision(db, rev1.revision_id, _actor("project-manager"))

        finding = create_finding(
            db,
            PROJECT_ID,
            EngineeringFindingIn(
                revision_id=rev1.revision_id,
                category="coordination",
                severity="critical",
                blocking=True,
                title="Statikai tengely és építész fal eltér",
                description="Az A/3 tengelynél a statikai és építészeti falpozíció nem egyezik.",
                location="A/3 tengely",
                responsible="designer@imperial.local",
                due_at=datetime(2026, 8, 4, tzinfo=UTC),
                source_module="plancheck",
                source_fingerprint=FINDING_FINGERPRINT,
            ),
            _actor("designer"),
        )

        rev2 = create_revision(
            db,
            deliverable.deliverable_id,
            _revision(
                "V02",
                "2" * 64,
                "Az A/3 tengely falpozíciója a statikai tervhez koordinálva.",
            ),
            _actor("designer"),
        )
        if rev2.status == "draft":
            rev2 = submit_revision(db, rev2.revision_id, _actor("designer"))
        if rev2.status == "review":
            rev2 = review_revision(
                db,
                rev2.revision_id,
                EngineeringRevisionReviewIn(
                    decision="approve",
                    note="A javított falpozíció és a teljes új revízió ellenőrzött.",
                ),
                _actor("technical-prep"),
            )
        if finding.status == "open":
            finding = propose_finding_resolution(
                db,
                finding.finding_id,
                EngineeringFindingResolutionIn(
                    resolution_revision_id=rev2.revision_id,
                    note="A javítás a V02 dokumentumhashhez kötötten benyújtva.",
                ),
                _actor("designer"),
            )
        if finding.status == "resolution_proposed":
            finding = approve_finding_resolution(
                db, finding.finding_id, _actor("technical-prep")
            )
        if rev2.status == "approved":
            rev2 = release_revision(db, rev2.revision_id, _actor("project-manager"))

        if not db.scalar(
            select(TechnicalCase).where(
                TechnicalCase.project_id == PROJECT_ID,
                TechnicalCase.module_key == "plotcheck",
                TechnicalCase.status == "approved",
            )
        ):
            db.add(
                TechnicalCase(
                    case_id="PLOTCHECK-ENGINEERING-SERVER-UAT",
                    module_key="plotcheck",
                    project_id=PROJECT_ID,
                    title="Kontrollált telekforrás",
                    status="approved",
                    input_json="{}",
                    result_json="{}",
                    source_snapshot_json='{"verified":true}',
                    created_by="technical-prep@imperial.local",
                    approved_by="technical-prep@imperial.local",
                    approved_at=datetime.now(UTC),
                )
            )

        plan = db.scalar(
            select(ProjectFinancePlan).where(
                ProjectFinancePlan.project_id == PROJECT_ID,
                ProjectFinancePlan.status == "approved",
            )
        )
        if not plan:
            plan = ProjectFinancePlan(
                plan_id="FIN-ENGINEERING-SERVER-UAT",
                project_id=PROJECT_ID,
                version=1,
                status="approved",
                currency="HUF",
                contract_revenue_net=Decimal("100000000"),
                target_margin_percent=Decimal("20"),
                created_by="finance@imperial.local",
            )
            db.add(plan)
            db.flush()
        if not db.scalar(
            select(ProjectFinanceCashflowLine).where(
                ProjectFinanceCashflowLine.plan_id_fk == plan.id
            )
        ):
            db.add(
                ProjectFinanceCashflowLine(
                    flow_id="FLOW-ENGINEERING-SERVER-UAT",
                    plan_id_fk=plan.id,
                    period_date=date(2026, 9, 30),
                    direction="outflow",
                    category="design",
                    description="Tervezési mérföldkő",
                    amount_net=Decimal("5000000"),
                    status="committed",
                    source_type="engineering",
                    source_id=case.engineering_case_id,
                )
            )
        db.commit()

        transmittal = db.scalar(
            select(EngineeringTransmittal).where(
                EngineeringTransmittal.engineering_case_id == case.engineering_case_id,
                EngineeringTransmittal.purpose == "construction",
                EngineeringTransmittal.subject == "Építész kiviteli tervcsomag R02",
            )
        )
        if not transmittal:
            transmittal = issue_transmittal(
                db,
                PROJECT_ID,
                EngineeringTransmittalIn(
                    purpose="construction",
                    subject="Építész kiviteli tervcsomag R02",
                    recipient_name="Kivitelező projektvezető",
                    recipient_email="site-manager@imperial.local",
                    message="Kizárólag a mellékelt R02 revízió használható kivitelezésre.",
                    revision_ids=[rev2.revision_id],
                ),
                _actor("project-manager"),
            )
        if transmittal.status == "issued":
            transmittal = acknowledge_transmittal(
                db,
                transmittal.transmittal_id,
                EngineeringTransmittalAckIn(
                    decision="acknowledge",
                    note="A tervcsomag dokumentumhashét ellenőriztem és átvettem.",
                ),
                _actor("finance"),
            )

        case = mark_construction_ready(db, PROJECT_ID, _actor("project-manager"))
        _print_result(db, case)


if __name__ == "__main__":
    main()
