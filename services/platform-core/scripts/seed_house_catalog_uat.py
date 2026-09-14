from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import HouseCatalogPlan, HouseCatalogVersion
from app.schemas import HouseCatalogReviewIn, HouseCatalogVersionIn
from app.services.house_catalog import (
    create_catalog_version,
    ensure_house_catalog_seed,
    public_catalog,
    release_catalog_version,
    review_catalog_version,
    submit_catalog_version,
    withdraw_catalog_plan,
)

HOUSE_ID = "HOUSE-CATALOG-SERVER-UAT"


def _actor(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def main() -> None:
    with SessionLocal() as db:
        ensure_house_catalog_seed(db)
        plan = db.scalar(select(HouseCatalogPlan).where(HouseCatalogPlan.house_id == HOUSE_ID))
        if not plan:
            version = create_catalog_version(
                db,
                HouseCatalogVersionIn(
                    house_id=HOUSE_ID,
                    brand="imperial-uat",
                    canonical_name="Kontrollált House Catalog szerver-UAT",
                    catalog_price_huf="100000000",
                    gross_area_m2="125",
                    rooms="4+1",
                    price_status="kontrollált UAT",
                    data_quality="verified_uat",
                    lifestyles=["család", "kontrollált teszt"],
                    source_type="controlled_uat",
                    source_url="https://drive.example/house-catalog-server-uat",
                    source_verified_at="2026-08-02",
                    rights_evidence="Kontrollált UAT felhasználási jogi bizonyíték.",
                    technical_summary="Kontrollált UAT típusterv teljes műszaki összefoglalója.",
                    change_summary="Első kontrollált szerver-UAT kiadás.",
                ),
                _actor("technical-prep"),
            )
        else:
            version = db.scalar(
                select(HouseCatalogVersion).where(
                    HouseCatalogVersion.house_id == HOUSE_ID,
                    HouseCatalogVersion.version == 1,
                )
            )
        if version.status == "draft":
            version = submit_catalog_version(
                db, version.catalog_version_id, _actor("technical-prep")
            )
        if version.status == "review" and not version.source_approved_by:
            version = review_catalog_version(
                db,
                version.catalog_version_id,
                HouseCatalogReviewIn(
                    gate="source",
                    decision="approve",
                    note="A kontrollált UAT forrásjogi bizonyítéka megfelelő.",
                ),
                _actor("legal"),
            )
        if version.status == "review" and not version.technical_approved_by:
            version = review_catalog_version(
                db,
                version.catalog_version_id,
                HouseCatalogReviewIn(
                    gate="technical",
                    decision="approve",
                    note="A kontrollált UAT terv műszaki tartalma megfelelő.",
                ),
                _actor("designer"),
            )
        if version.status == "review" and not version.commercial_approved_by:
            version = review_catalog_version(
                db,
                version.catalog_version_id,
                HouseCatalogReviewIn(
                    gate="commercial",
                    decision="approve",
                    note="A kontrollált UAT terv katalógusára megfelelő.",
                ),
                _actor("finance"),
            )
        if version.status == "approved":
            version = release_catalog_version(
                db, version.catalog_version_id, _actor("managing-director")
            )
        was_public = any(row["house_id"] == HOUSE_ID for row in public_catalog(db))
        if version.status == "released":
            version = withdraw_catalog_plan(
                db,
                HOUSE_ID,
                reason="A kontrollált UAT-terv kiadási teszt után kötelezően visszavonandó.",
                user=_actor("owner"),
            )
        is_public = any(row["house_id"] == HOUSE_ID for row in public_catalog(db))
        print(
            {
                "house_id": HOUSE_ID,
                "version": version.version,
                "status": version.status,
                "content_sha256": version.content_sha256,
                "source_approved_by": version.source_approved_by,
                "technical_approved_by": version.technical_approved_by,
                "commercial_approved_by": version.commercial_approved_by,
                "released_then_withdrawn": was_public or version.withdrawn_at is not None,
                "public_after_withdrawal": is_public,
                "public_baseline_count": len(public_catalog(db)),
            }
        )


if __name__ == "__main__":
    main()
