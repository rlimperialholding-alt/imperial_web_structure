from __future__ import annotations

from sqlalchemy import select

from app.audit import audit
from app.database import SessionLocal
from app.models import CustomerPortalAccess, ProjectRegistry


def main() -> None:
    project_id = "UAT-2026-A03"
    customer_email = "customer@imperial.local"
    with SessionLocal() as db:
        project = db.scalar(
            select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)
        )
        if project is None:
            raise RuntimeError(f"UAT project is missing: {project_id}")
        row = db.scalar(
            select(CustomerPortalAccess).where(
                CustomerPortalAccess.project_id == project_id,
                CustomerPortalAccess.customer_email == customer_email,
            )
        )
        if row is None:
            row = CustomerPortalAccess(
                access_id="CPA-CARE-UAT-A03",
                project_id=project_id,
                customer_email=customer_email,
                contact_name="Imperial Ügyfél",
                source_type="uat",
                source_id="IMPERIAL-CARE-UAT-20260802",
                active=True,
                created_by="codex-uat",
            )
            db.add(row)
            action = "created"
        else:
            row.active = True
            action = "reactivated"
        audit(
            db,
            actor="codex-uat",
            action=f"imperial_care.uat_access.{action}",
            entity_type="customer_portal_access",
            entity_id=row.access_id,
            after={"project_id": project_id, "customer_email": customer_email, "uat": True},
        )
        db.commit()
        print(row.access_id, project_id, customer_email, action)


if __name__ == "__main__":
    main()
