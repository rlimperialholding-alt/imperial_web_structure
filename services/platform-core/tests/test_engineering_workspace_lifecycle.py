from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (
    EngineeringDeliverable,
    EngineeringRevision,
    OutboxMessage,
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


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _revision(document_id: str, version: str, digest: str, summary: str):
    return EngineeringRevisionIn(
        source_document_id=document_id,
        source_version=version,
        source_url=f"https://drive.example/{document_id}/{version}",
        file_name=f"{document_id}-{version}.pdf",
        mime_type="application/pdf",
        file_size=2048,
        content_sha256=digest,
        change_summary=summary,
        metadata={"document_owner": "document-evidence"},
    )


def test_engineering_revision_finding_transmittal_and_readiness_lifecycle(db):
    project_id = "ENG-UAT-001"
    case_data = EngineeringCaseIn(
        project_id=project_id,
        title="Engineering Workspace UAT projekt",
        lead_designer="designer@imperial.local",
        project_manager="project-manager@imperial.local",
        contract_date=date(2026, 8, 2),
    )
    case = create_engineering_case(db, case_data, _user("project-manager"))
    duplicate = create_engineering_case(db, case_data, _user("project-manager"))
    assert duplicate.engineering_case_id == case.engineering_case_id
    assert (case.absolute_deadline - case.consultation_due_at).days == 87
    complete_consultation(db, project_id, _user("designer"))

    deliverable = create_deliverable(
        db,
        project_id,
        EngineeringDeliverableIn(
            discipline="architecture",
            deliverable_code="ARCH-GA",
            title="Építész kiviteli tervcsomag",
            document_type="construction_plan",
            responsible="designer@imperial.local",
            due_at=datetime(2026, 9, 15, tzinfo=UTC),
            required=True,
        ),
        _user("project-manager"),
    )
    assert create_deliverable(
        db,
        project_id,
        EngineeringDeliverableIn(
            discipline="architecture",
            deliverable_code="ARCH-GA",
            title="Építész kiviteli tervcsomag",
            document_type="construction_plan",
            responsible="designer@imperial.local",
            due_at=datetime(2026, 9, 15, tzinfo=UTC),
            required=True,
        ),
        _user("project-manager"),
    ).deliverable_id == deliverable.deliverable_id

    rev1 = create_revision(
        db,
        deliverable.deliverable_id,
        _revision("DOC-ENG-ARCH", "V01", "1" * 64, "Első koordinációs tervkiadás."),
        _user("designer"),
    )
    assert create_revision(
        db,
        deliverable.deliverable_id,
        _revision("DOC-ENG-ARCH", "V01", "1" * 64, "Első koordinációs tervkiadás."),
        _user("designer"),
    ).revision_id == rev1.revision_id
    submit_revision(db, rev1.revision_id, _user("designer"))
    with pytest.raises(ValueError, match="saját"):
        review_revision(
            db,
            rev1.revision_id,
            EngineeringRevisionReviewIn(decision="approve", note="Saját terv tiltott review kísérlete."),
            _user("technical-prep", "designer@imperial.local"),
        )
    review_revision(
        db,
        rev1.revision_id,
        EngineeringRevisionReviewIn(
            decision="approve",
            note="A tervazonosító, tartalom, szakági teljesség és hash ellenőrzött.",
        ),
        _user("technical-prep"),
    )
    release_revision(db, rev1.revision_id, _user("project-manager"))

    finding = create_finding(
        db,
        project_id,
        EngineeringFindingIn(
            revision_id=rev1.revision_id,
            category="coordination",
            severity="critical",
            blocking=True,
            title="Statikai tengely és építész fal eltér",
            description="Az A/3 tengelynél a statikai és építészeti falpozíció nem egyezik.",
            location="A/3 tengely",
            responsible="designer@imperial.local",
            due_at=datetime.now(UTC) + timedelta(days=2),
            source_module="plancheck",
            source_fingerprint="PLAN-CHECK-ENG-UAT-001",
        ),
        _user("designer"),
    )
    assert create_finding(
        db,
        project_id,
        EngineeringFindingIn(
            revision_id=rev1.revision_id,
            category="coordination",
            severity="critical",
            blocking=True,
            title="Statikai tengely és építész fal eltér",
            description="Az A/3 tengelynél a statikai és építészeti falpozíció nem egyezik.",
            location="A/3 tengely",
            responsible="designer@imperial.local",
            due_at=datetime.now(UTC) + timedelta(days=2),
            source_module="plancheck",
            source_fingerprint="PLAN-CHECK-ENG-UAT-001",
        ),
        _user("designer"),
    ).finding_id == finding.finding_id

    rev2 = create_revision(
        db,
        deliverable.deliverable_id,
        _revision(
            "DOC-ENG-ARCH",
            "V02",
            "2" * 64,
            "Az A/3 tengely falpozíciója a statikai tervhez koordinálva.",
        ),
        _user("designer"),
    )
    submit_revision(db, rev2.revision_id, _user("designer"))
    review_revision(
        db,
        rev2.revision_id,
        EngineeringRevisionReviewIn(
            decision="approve", note="A javított falpozíció és a teljes új revízió ellenőrzött."
        ),
        _user("technical-prep"),
    )
    propose_finding_resolution(
        db,
        finding.finding_id,
        EngineeringFindingResolutionIn(
            resolution_revision_id=rev2.revision_id,
            note="A javítás a V02 dokumentumhashhez kötötten benyújtva.",
        ),
        _user("designer"),
    )
    approve_finding_resolution(db, finding.finding_id, _user("technical-prep"))
    release_revision(db, rev2.revision_id, _user("project-manager"))
    db.refresh(rev1)
    assert rev1.status == "superseded"

    transmittal = issue_transmittal(
        db,
        project_id,
        EngineeringTransmittalIn(
            purpose="construction",
            subject="Építész kiviteli tervcsomag R02",
            recipient_name="Kivitelező projektvezető",
            recipient_email="site-manager@imperial.local",
            message="Kizárólag a mellékelt R02 revízió használható kivitelezésre.",
            revision_ids=[rev2.revision_id],
        ),
        _user("project-manager"),
    )
    acknowledge_transmittal(
        db,
        transmittal.transmittal_id,
        EngineeringTransmittalAckIn(
            decision="acknowledge", note="A tervcsomag hashét ellenőriztem és átvettem."
        ),
        _user("finance"),
    )

    with pytest.raises(ValueError, match="PlotCheck"):
        mark_construction_ready(db, project_id, _user("project-manager"))
    db.add(
        TechnicalCase(
            case_id="PLOT-ENG-UAT-001",
            module_key="plotcheck",
            project_id=project_id,
            title="Ellenőrzött telekforrás",
            status="approved",
            input_json="{}",
            result_json="{}",
            source_snapshot_json='{"verified":true}',
            created_by="technical-prep@imperial.local",
            approved_by="technical-prep@imperial.local",
            approved_at=datetime.now(UTC),
        )
    )
    plan = ProjectFinancePlan(
        plan_id="FIN-ENG-UAT-001",
        project_id=project_id,
        version=1,
        status="approved",
        currency="HUF",
        contract_revenue_net=Decimal("100000000"),
        target_margin_percent=Decimal("20"),
        created_by="finance@imperial.local",
    )
    db.add(plan)
    db.flush()
    db.add(
        ProjectFinanceCashflowLine(
            flow_id="FLOW-ENG-UAT-001",
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
    ready = mark_construction_ready(db, project_id, _user("project-manager"))
    assert ready.status == "construction_ready"
    assert ready.readiness_version == 2
    assert db.scalar(
        select(EngineeringDeliverable).where(
            EngineeringDeliverable.deliverable_id == deliverable.deliverable_id
        )
    ).current_released_revision == 2
    assert db.scalar(
        select(EngineeringRevision).where(EngineeringRevision.revision_id == rev2.revision_id)
    ).content_sha256 == "2" * 64
    destinations = set(db.scalars(select(OutboxMessage.destination_module)).all())
    assert {"plancheck", "document-evidence", "project-control", "my-imperial"} <= destinations


def test_engineering_workspace_http_role_scope(client):
    for role in ("technical-prep", "designer", "project-manager", "finance", "owner", "managing-director", "platform-admin"):
        client.post("/logout")
        response = client.post(
            "/login",
            data={"email": f"{role}@imperial.local", "password": "Imperial2026!"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        page = client.get("/engineering-workspace")
        assert page.status_code == 200
        assert "Engineering Workspace" in page.text
        assert client.get("/api/engineering/summary").status_code == 200

    client.post("/logout")
    client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert client.get("/engineering-workspace").status_code == 403
    assert client.get("/api/engineering/summary").status_code == 403
