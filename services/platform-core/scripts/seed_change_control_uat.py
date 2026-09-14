from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    ChangeControlCase,
    ChangeControlLine,
    ChangeControlVersion,
    CustomerDecisionRequest,
    CustomerDecisionResponse,
    CustomerPortalAccess,
    ProjectRegistry,
)
from app.services.change_control import (
    CUSTOMER_ACCEPT_OPTION,
    add_change_line,
    authorize_change_work,
    complete_change,
    create_change_case,
    ensure_change_documents,
    review_change,
    submit_change,
    sync_customer_decision,
)
from app.services.my_imperial import respond_to_decision

PROJECT_ID = "CHANGE-SERVER-UAT"
CASE_TITLE = "ChangeControl kontrollált szerver-UAT"
CUSTOMER_EMAIL = "customer@imperial.local"


def _actor(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _ensure_project(db) -> None:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == PROJECT_ID)):
        db.add(
            ProjectRegistry(
                project_id=PROJECT_ID,
                name="ChangeControl szerver-UAT projekt",
                customer_name="ChangeControl UAT ügyfél",
                project_type="controlled_uat",
                status="active",
                responsible="project-manager@imperial.local",
            )
        )
    access = db.scalar(
        select(CustomerPortalAccess).where(
            CustomerPortalAccess.access_id == "MYI-ACCESS-CHANGE-SERVER-UAT"
        )
    )
    if access:
        access.project_id = PROJECT_ID
        access.customer_email = CUSTOMER_EMAIL
        access.contact_name = "ChangeControl UAT ügyfél"
        access.source_type = "controlled_uat"
        access.source_id = "CHANGE-SERVER-UAT"
        access.active = True
    else:
        db.add(
            CustomerPortalAccess(
                access_id="MYI-ACCESS-CHANGE-SERVER-UAT",
                project_id=PROJECT_ID,
                customer_email=CUSTOMER_EMAIL,
                contact_name="ChangeControl UAT ügyfél",
                source_type="controlled_uat",
                source_id="CHANGE-SERVER-UAT",
                active=True,
                created_by="project-manager@imperial.local",
            )
        )
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        _ensure_project(db)
        case = db.scalar(
            select(ChangeControlCase).where(
                ChangeControlCase.project_id == PROJECT_ID,
                ChangeControlCase.title == CASE_TITLE,
            )
        )
        if not case:
            case = create_change_case(
                db,
                _actor("project-manager"),
                project_id=PROJECT_ID,
                title=CASE_TITLE,
                change_type="scope",
                reason="Kontrollált szerver-UAT a natív változtatáskezelési életútra.",
                technical_scope=(
                    "Vasbeton szerkezet kontrollált tesztváltoztatása teljes műszaki tartalommal."
                ),
                exclusions=(
                    "Az UAT nem hoz létre valós ügyfélkötelezettséget vagy valós munkamegrendelést."
                ),
                assumptions=(
                    "A teszt minden pénzügyi és műszaki értéke szintetikus és elkülönített."
                ),
                deadline_impact_days=7,
                vat_rate="27",
                customer_advance_net="4000000",
                responsible="project-manager@imperial.local",
            )
        version = db.scalar(
            select(ChangeControlVersion).where(
                ChangeControlVersion.change_id_fk == case.id,
                ChangeControlVersion.version == case.current_version,
            )
        )
        if version.status == "draft" and not db.scalar(
            select(ChangeControlLine).where(ChangeControlLine.version_id_fk == version.id)
        ):
            add_change_line(
                db,
                case.change_id,
                _actor("project-manager"),
                category="controlled_uat",
                description="Kontrollált UAT tétel",
                quantity="1",
                unit="átalány",
                unit_cost_net="4000000",
                unit_sale_net="6500000",
                early_direct_cost=True,
            )
        if version.status == "draft":
            version = submit_change(db, case.change_id, _actor("project-manager"))
        if version.status == "internal_review" and not version.technical_approved_by:
            version = review_change(
                db,
                case.change_id,
                _actor("technical-prep"),
                gate="technical",
                decision="approve",
                note="A kontrollált UAT műszaki scope és határidőhatás megfelelő.",
            )
        if version.status == "internal_review" and not version.finance_approved_by:
            version = review_change(
                db,
                case.change_id,
                _actor("finance"),
                gate="finance",
                decision="approve",
                note="A kontrollált UAT ár-, fedezet-, előleg- és cashflow-kapu megfelelő.",
            )
        if version.status == "internal_review" and not version.leadership_approved_by:
            version = review_change(
                db,
                case.change_id,
                _actor("managing-director"),
                gate="leadership",
                decision="approve",
                note="A kontrollált UAT nagyértékű változtatása vezetőileg jóváhagyott.",
            )
        if version.status == "customer_review":
            decision = db.scalar(
                select(CustomerDecisionRequest).where(
                    CustomerDecisionRequest.decision_id == version.customer_decision_id
                )
            )
            response = db.scalar(
                select(CustomerDecisionResponse).where(
                    CustomerDecisionResponse.decision_id_fk == decision.id
                )
            )
            if not response:
                respond_to_decision(
                    db,
                    PROJECT_ID,
                    decision.decision_id,
                    _actor("customer", CUSTOMER_EMAIL),
                    selected_option=CUSTOMER_ACCEPT_OPTION,
                    note="A kontrollált UAT ügyfélcsomagot elfogadom.",
                )
            version = sync_customer_decision(db, case.change_id, _actor("project-manager"))
        if version.status == "customer_accepted":
            starts_at = datetime(2026, 8, 10, 8, tzinfo=UTC)
            version = authorize_change_work(
                db,
                case.change_id,
                _actor("project-manager"),
                starts_at=starts_at,
                ends_at=starts_at + timedelta(days=7),
            )
        if version.status == "work_authorized":
            version = complete_change(
                db,
                case.change_id,
                _actor("project-manager"),
                evidence_url="https://drive.google.com/change-control-server-uat-evidence",
                note="A kontrollált UAT-változtatás teljesítése és integrációja ellenőrzött.",
            )
        documents = ensure_change_documents(
            db,
            case.change_id,
            _actor("platform-admin"),
        )
        print(
            {
                "change_id": case.change_id,
                "version": version.version,
                "status": version.status,
                "cost_net": str(version.cost_net),
                "sale_net": str(version.sale_net),
                "margin_percent": str(version.margin_percent),
                "content_sha256": version.content_sha256,
                "customer_decision_id": version.customer_decision_id,
                "calendar_entry_id": version.calendar_entry_id,
                "document_ids": [row.document_id for row in documents],
            }
        )


if __name__ == "__main__":
    main()
