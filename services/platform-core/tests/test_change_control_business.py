import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (
    CalendarEntry,
    ChangeControlLine,
    CustomerDecisionRequest,
    CustomerPortalAccess,
    OutboxMessage,
    ProjectObjectState,
    ProjectRegistry,
    WorkspaceDocument,
)
from app.services.change_control import (
    CUSTOMER_ACCEPT_OPTION,
    add_change_line,
    authorize_change_work,
    complete_change,
    create_change_case,
    create_change_revision,
    delete_change_line,
    ensure_change_documents,
    review_change,
    submit_change,
    sync_customer_decision,
)
from app.services.my_imperial import respond_to_decision
from scripts.seed_change_control_uat import _ensure_project as ensure_server_uat_project

PROJECT_ID = "CHANGE-UAT-001"
CUSTOMER = "customer@imperial.local"


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _project(db):
    db.add(
        ProjectRegistry(
            project_id=PROJECT_ID,
            name="ChangeControl üzleti UAT projekt",
            customer_name="Change UAT Ügyfél",
            project_type="construction",
            status="active",
            responsible="project-manager@imperial.local",
        )
    )
    db.add(
        CustomerPortalAccess(
            access_id="MYI-ACCESS-CHANGE-UAT",
            project_id=PROJECT_ID,
            customer_email=CUSTOMER,
            contact_name="Change UAT Ügyfél",
            source_type="manual_uat",
            source_id="CHANGE-UAT-ACCESS",
            active=True,
            created_by="project-manager@imperial.local",
        )
    )
    db.commit()


def _case(db, *, advance: str = "4000000"):
    return create_change_case(
        db,
        _user("project-manager"),
        project_id=PROJECT_ID,
        title="Támfal és tereprendezés pótmunkája",
        change_type="scope",
        reason="A feltárt talajviszonyok miatt új vasbeton támfal szükséges.",
        technical_scope="A jóváhagyott kiviteli terv szerinti vasbeton támfal teljes kivitelezése.",
        exclusions="A kertépítés és a későbbi növénytelepítés nem része a módosításnak.",
        assumptions="A munkaterület megközelíthető és a kitermelt föld ideiglenesen tárolható.",
        deadline_impact_days=7,
        vat_rate="27",
        customer_advance_net=advance,
        responsible="project-manager@imperial.local",
    )


def _line(db, change_id: str, *, sale: str = "6500000"):
    return add_change_line(
        db,
        change_id,
        _user("project-manager"),
        category="vasbeton",
        description="Támfal szerkezet teljes anyag- és munkadíja",
        quantity="1",
        unit="átalány",
        unit_cost_net="4000000",
        unit_sale_net=sale,
        early_direct_cost=True,
    )


def test_full_change_control_flow_reaches_myimperial_calendar_finance_and_completion(
    db, client
):
    _project(db)
    case = _case(db)
    _line(db, case.change_id)
    submitted = submit_change(db, case.change_id, _user("project-manager"))
    assert submitted.status == "internal_review"
    assert submitted.margin_percent > 35
    assert submitted.leadership_required is True
    assert submitted.content_sha256 and len(submitted.content_sha256) == 64
    internal_document = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.project_id == PROJECT_ID,
            WorkspaceDocument.category == "change_order",
            WorkspaceDocument.confidentiality == "internal",
        )
    )
    assert internal_document
    internal_metadata = json.loads(internal_document.metadata_json)
    internal_path = Path(internal_metadata["local_path"])
    assert internal_path.read_bytes().startswith(b"%PDF-")
    assert hashlib.sha256(internal_path.read_bytes()).hexdigest() == internal_metadata[
        "artifact_sha256"
    ]
    client.post(
        "/login",
        data={"email": "project-manager@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    internal_download = client.get(internal_document.source_url)
    assert internal_download.status_code == 200
    assert internal_download.content.startswith(b"%PDF-")

    with pytest.raises(ValueError, match="saját"):
        review_change(
            db,
            case.change_id,
            _user("project-manager"),
            gate="technical",
            decision="approve",
            note="A saját verzió jóváhagyása tiltott lenne.",
        )
    review_change(
        db,
        case.change_id,
        _user("technical-prep"),
        gate="technical",
        decision="approve",
        note="A műszaki tartalom és a hét nap határidőhatás elfogadható.",
    )
    review_change(
        db,
        case.change_id,
        _user("finance"),
        gate="finance",
        decision="approve",
        note="Az ár, fedezet, előleg és korai cashflow-kapu megfelelő.",
    )
    customer_review = review_change(
        db,
        case.change_id,
        _user("managing-director"),
        gate="leadership",
        decision="approve",
        note="A nagy értékű változtatás üzleti és határidőhatása jóváhagyott.",
    )
    assert customer_review.status == "customer_review"
    decision = db.scalar(
        select(CustomerDecisionRequest).where(
            CustomerDecisionRequest.decision_id == customer_review.customer_decision_id
        )
    )
    assert decision.source_module == "change-control"
    assert decision.source_object_id == case.change_id
    assert decision.source_version == 1
    internal_documents = db.scalars(
        select(WorkspaceDocument).where(
            WorkspaceDocument.project_id == PROJECT_ID,
            WorkspaceDocument.category == "change_order",
            WorkspaceDocument.confidentiality == "internal",
        )
    ).all()
    assert {json.loads(row.metadata_json)["variant"] for row in internal_documents} == {
        "internal-review",
        "internal-approved",
    }
    assert len(
        {json.loads(row.metadata_json)["local_path"] for row in internal_documents}
    ) == 2
    customer_document = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.project_id == PROJECT_ID,
            WorkspaceDocument.category == "change_order",
            WorkspaceDocument.confidentiality == "customer",
        )
    )
    assert customer_document and customer_document.approval_status == "approved"
    customer_metadata = json.loads(customer_document.metadata_json)
    customer_path = Path(customer_metadata["local_path"])
    assert customer_metadata["audience"] == "customer"
    assert customer_path.read_bytes().startswith(b"%PDF-")
    assert hashlib.sha256(customer_path.read_bytes()).hexdigest() == customer_metadata[
        "artifact_sha256"
    ]
    client.post("/logout")
    client.post(
        "/login",
        data={"email": CUSTOMER, "password": "Imperial2026!"},
        follow_redirects=False,
    )
    portal = client.get(f"/my-imperial/{PROJECT_ID}")
    assert portal.status_code == 200
    assert customer_document.document_id in portal.text
    customer_download = client.get(customer_document.source_url)
    assert customer_download.status_code == 200
    assert customer_download.content.startswith(b"%PDF-")
    assert (
        client.get(
            f"/my-imperial/UNAUTHORIZED-PROJECT/documents/{customer_document.document_id}"
        ).status_code
        == 403
    )
    original_customer_pdf = customer_path.read_bytes()
    customer_path.write_bytes(original_customer_pdf + b"tamper")
    assert client.get(customer_document.source_url).status_code == 409
    customer_path.write_bytes(original_customer_pdf)

    respond_to_decision(
        db,
        PROJECT_ID,
        decision.decision_id,
        _user("customer", CUSTOMER),
        selected_option=CUSTOMER_ACCEPT_OPTION,
        note="A részletes műszaki és pénzügyi csomagot elfogadom.",
    )
    accepted = sync_customer_decision(db, case.change_id, _user("project-manager"))
    assert accepted.status == "customer_accepted"

    starts_at = datetime.now(UTC) + timedelta(days=1)
    authorized = authorize_change_work(
        db,
        case.change_id,
        _user("project-manager"),
        starts_at=starts_at,
        ends_at=starts_at + timedelta(days=7),
    )
    assert authorized.status == "work_authorized"
    assert db.scalar(
        select(CalendarEntry).where(
            CalendarEntry.entry_id == authorized.calendar_entry_id,
            CalendarEntry.source_module == "change-control",
        )
    )
    state = db.scalar(
        select(ProjectObjectState).where(
            ProjectObjectState.project_id == PROJECT_ID,
            ProjectObjectState.source_module == "change_control",
            ProjectObjectState.object_id == case.change_id,
        )
    )
    assert state and state.status == "work_authorized"
    destinations = {
        row.destination_module
        for row in db.scalars(
            select(OutboxMessage).where(OutboxMessage.source_event_id == state.last_event_id)
        )
    }
    assert {"project_control", "finance", "calendar", "procurement"} <= destinations

    completed = complete_change(
        db,
        case.change_id,
        _user("project-manager"),
        evidence_url="https://drive.google.com/change-uat-evidence",
        note="A támfal elkészült, a műszaki átadás és a bizonyíték ellenőrzött.",
    )
    assert completed.status == "completed"
    db.refresh(state)
    assert state.status == "completed"
    before_artifacts = {
        row.document_id: json.loads(row.metadata_json)["artifact_sha256"]
        for row in db.scalars(
            select(WorkspaceDocument).where(
                WorkspaceDocument.project_id == PROJECT_ID,
                WorkspaceDocument.source_system == "change-control",
            )
        ).all()
    }
    ensure_change_documents(db, case.change_id, _user("platform-admin"))
    ensure_change_documents(db, case.change_id, _user("platform-admin"))
    after_artifacts = {
        row.document_id: json.loads(row.metadata_json)["artifact_sha256"]
        for row in db.scalars(
            select(WorkspaceDocument).where(
                WorkspaceDocument.project_id == PROJECT_ID,
                WorkspaceDocument.source_system == "change-control",
            )
        ).all()
    }
    assert after_artifacts == before_artifacts


def test_margin_advance_and_version_reset_are_fail_closed(db):
    _project(db)
    case = _case(db, advance="1000000")
    line = _line(db, case.change_id, sale="5000000")
    with pytest.raises(ValueError, match="35%"):
        submit_change(db, case.change_id, _user("project-manager"))
    delete_change_line(db, case.change_id, line.line_id, _user("project-manager"))
    replacement = _line(db, case.change_id, sale="6500000")
    with pytest.raises(ValueError, match="előleg"):
        submit_change(db, case.change_id, _user("project-manager"))
    delete_change_line(db, case.change_id, replacement.line_id, _user("project-manager"))
    add_change_line(
        db,
        case.change_id,
        _user("project-manager"),
        category="tervezés",
        description="Módosított statikai terv és mérnöki ellenőrzés",
        quantity="1",
        unit="átalány",
        unit_cost_net="500000",
        unit_sale_net="1000000",
        early_direct_cost=True,
    )
    submitted = submit_change(db, case.change_id, _user("project-manager"))
    review_change(
        db,
        case.change_id,
        _user("technical-prep"),
        gate="technical",
        decision="reject",
        note="A tervcsomagból még hiányzik a statikai részletrajz.",
    )
    revision = create_change_revision(
        db,
        case.change_id,
        _user("project-manager"),
        reason="A statikai részletrajzzal és pontosított tétellel új verzió készül.",
    )
    assert revision.version == 2
    assert revision.status == "draft"
    assert revision.technical_approved_by is None
    assert revision.finance_approved_by is None
    assert revision.leadership_approved_by is None
    assert revision.customer_decision_id is None
    assert submitted.status == "superseded"
    assert (
        len(
            db.scalars(
                select(ChangeControlLine).where(ChangeControlLine.version_id_fk == revision.id)
            ).all()
        )
        == 1
    )


def test_change_control_http_is_internal_only(client):
    client.post(
        "/login",
        data={"email": "project-manager@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert client.get("/change-control").status_code == 200
    client.post("/logout")
    client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert client.get("/change-control").status_code == 403


def test_server_uat_access_upgrade_is_idempotent(db):
    db.add(
        ProjectRegistry(
            project_id="CHANGE-SERVER-UAT",
            name="Korábbi UAT projekt",
            project_type="controlled_uat",
            status="active",
        )
    )
    db.add(
        CustomerPortalAccess(
            access_id="MYI-ACCESS-CHANGE-SERVER-UAT",
            project_id="CHANGE-SERVER-UAT",
            customer_email="change-control-uat@imperial.local",
            contact_name="Korábbi technikai ügyfél",
            source_type="controlled_uat",
            source_id="CHANGE-SERVER-UAT",
            active=True,
            created_by="project-manager@imperial.local",
        )
    )
    db.commit()
    ensure_server_uat_project(db)
    ensure_server_uat_project(db)
    accesses = db.scalars(
        select(CustomerPortalAccess).where(
            CustomerPortalAccess.access_id == "MYI-ACCESS-CHANGE-SERVER-UAT"
        )
    ).all()
    assert len(accesses) == 1
    assert accesses[0].customer_email == "customer@imperial.local"
