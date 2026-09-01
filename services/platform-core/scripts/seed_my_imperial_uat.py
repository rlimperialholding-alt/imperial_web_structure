from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    CustomerDecisionRequest,
    CustomerPortalAccess,
    CustomerPortalUpdate,
    ProjectRegistry,
)
from app.services.my_imperial import create_decision_request, publish_project_update

PROJECT_ID = "MYI-UAT-SERVER-001"
CUSTOMER_EMAIL = "customer@imperial.local"


def main() -> None:
    actor = SimpleNamespace(role="project-manager", email="project-manager@imperial.local")
    with SessionLocal() as db:
        if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == PROJECT_ID)):
            db.add(
                ProjectRegistry(
                    project_id=PROJECT_ID,
                    name="MyImperial szerver UAT projekt",
                    customer_name="Kontrollált UAT Ügyfél",
                    project_type="uat_new_build",
                    status="active",
                    responsible=actor.email,
                    next_action="MyImperial szerepkörös UAT",
                )
            )
        if not db.scalar(
            select(CustomerPortalAccess).where(
                CustomerPortalAccess.project_id == PROJECT_ID,
                CustomerPortalAccess.customer_email == CUSTOMER_EMAIL,
            )
        ):
            db.add(
                CustomerPortalAccess(
                    access_id="MYI-UAT-SERVER-ACCESS-001",
                    project_id=PROJECT_ID,
                    customer_email=CUSTOMER_EMAIL,
                    contact_name="Kontrollált UAT Ügyfél",
                    source_type="uat",
                    source_id="MYI-UAT-SERVER-SEED",
                    active=True,
                    created_by=actor.email,
                )
            )
        db.commit()
        if not db.scalar(
            select(CustomerPortalUpdate).where(
                CustomerPortalUpdate.project_id == PROJECT_ID,
                CustomerPortalUpdate.title == "UAT projektindítás",
            )
        ):
            publish_project_update(
                db,
                PROJECT_ID,
                actor,
                title="UAT projektindítás",
                body="Kontrollált tesztfrissítés a MyImperial projektportál ellenőrzéséhez.",
                progress_percent=15,
                requires_acknowledgement=True,
            )
        if not db.scalar(
            select(CustomerDecisionRequest).where(
                CustomerDecisionRequest.project_id == PROJECT_ID,
                CustomerDecisionRequest.title == "UAT burkolati döntés",
            )
        ):
            create_decision_request(
                db,
                PROJECT_ID,
                actor,
                title="UAT burkolati döntés",
                description="Válasszon egy kontrollált tesztopciót a döntési folyamat UAT-jához.",
                options=["UAT világos", "UAT natúr", "UAT sötét"],
                due_at=datetime.now(UTC) + timedelta(days=7),
            )
        print(
            {
                "project_id": PROJECT_ID,
                "customer_email": CUSTOMER_EMAIL,
                "updates": db.scalar(
                    select(func.count())
                    .select_from(CustomerPortalUpdate)
                    .where(CustomerPortalUpdate.project_id == PROJECT_ID)
                ),
                "decisions": db.scalar(
                    select(func.count())
                    .select_from(CustomerDecisionRequest)
                    .where(CustomerDecisionRequest.project_id == PROJECT_ID)
                ),
            }
        )


if __name__ == "__main__":
    main()
