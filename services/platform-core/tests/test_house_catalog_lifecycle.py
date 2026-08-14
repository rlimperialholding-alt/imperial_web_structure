from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import HouseCatalogPlan, OutboxMessage
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
from app.services.technical_products import create_case


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _version_data(source: dict, *, price_delta: int = 1_000_000):
    return HouseCatalogVersionIn(
        house_id=source["house_id"],
        brand=source["brand"],
        canonical_name=source["name"],
        catalog_price_huf=source["catalog_price_huf"] + price_delta,
        gross_area_m2=source["gross_area_m2"],
        rooms=str(source["rooms"]),
        price_status="2026-Q3 jóváhagyandó listaár",
        data_quality="verified",
        lifestyles=source["lifestyles"],
        source_type="vállalati terv- és árjegyzék",
        source_url=source["source_url"],
        source_verified_at="2026-08-02",
        rights_evidence="A vállalati terv felhasználási joga a jogi nyilvántartásban igazolt.",
        technical_summary=(
            "A terv geometriája és műszaki alaptartalma változatlan, az árverzió frissült."
        ),
        change_summary="2026-Q3 katalógusár-frissítés.",
    )


def test_house_catalog_release_withdrawal_and_downstream_enforcement(db):
    assert ensure_house_catalog_seed(db) == 48
    assert ensure_house_catalog_seed(db) == 0
    baseline = public_catalog(db)
    assert len(baseline) == 45
    source = next(row for row in baseline if len(row["source_url"]) >= 8)
    old_price = source["catalog_price_huf"]

    creator = _user("technical-prep")
    version = create_catalog_version(db, _version_data(source), creator)
    assert version.version == 2
    assert (
        next(row for row in public_catalog(db) if row["house_id"] == source["house_id"])[
            "catalog_price_huf"
        ]
        == old_price
    )
    version = submit_catalog_version(db, version.catalog_version_id, creator)
    assert version.status == "review"
    assert version.content_sha256 and len(version.content_sha256) == 64

    with pytest.raises(ValueError, match="sorrendben"):
        review_catalog_version(
            db,
            version.catalog_version_id,
            HouseCatalogReviewIn(
                gate="technical",
                decision="approve",
                note="A műszaki tartalom megfelelő, de a source kapu még hiányzik.",
            ),
            _user("designer"),
        )
    review_catalog_version(
        db,
        version.catalog_version_id,
        HouseCatalogReviewIn(
            gate="source",
            decision="approve",
            note="A forrás, felhasználási jog és ellenőrzési dátum jogilag igazolt.",
        ),
        _user("legal"),
    )
    with pytest.raises(ValueError, match="készítő"):
        review_catalog_version(
            db,
            version.catalog_version_id,
            HouseCatalogReviewIn(
                gate="technical",
                decision="approve",
                note="A készítő saját műszaki review-ja tiltott kell legyen.",
            ),
            creator,
        )
    review_catalog_version(
        db,
        version.catalog_version_id,
        HouseCatalogReviewIn(
            gate="technical",
            decision="approve",
            note="A tervgeometria, alapterület és műszaki tartalom ellenőrzött.",
        ),
        _user("designer"),
    )
    version = review_catalog_version(
        db,
        version.catalog_version_id,
        HouseCatalogReviewIn(
            gate="commercial",
            decision="approve",
            note="A katalógusár, fajlagos ár és árstátusz kereskedelmileg jóváhagyott.",
        ),
        _user("finance"),
    )
    assert version.status == "approved"
    version = release_catalog_version(db, version.catalog_version_id, _user("managing-director"))
    assert version.status == "released"
    released = next(row for row in public_catalog(db) if row["house_id"] == source["house_id"])
    assert released["catalog_price_huf"] == old_price + 1_000_000
    assert released["catalog_version"] == 2

    withdraw_catalog_plan(
        db,
        source["house_id"],
        reason="A típustervet műszaki felülvizsgálatig azonnal ki kell vonni a kínálatból.",
        user=_user("owner"),
    )
    assert len(public_catalog(db)) == 44
    plan = db.scalar(
        select(HouseCatalogPlan).where(HouseCatalogPlan.house_id == source["house_id"])
    )
    assert plan.lifecycle_status == "withdrawn"
    with pytest.raises(ValueError, match="aktív"):
        create_case(
            db,
            module_key="housebuild-agent",
            project_id="HOUSE-CATALOG-UAT",
            title="Visszavont terv használata tiltott",
            data={
                "source_house_id": source["house_id"],
                "rights_evidence": "https://drive.example/rights",
                "desired_area_m2": "120",
                "bedrooms": "3",
                "bathrooms": "2",
                "floors": "1",
            },
            actor="technical-prep@imperial.local",
        )
    assert db.scalars(
        select(OutboxMessage).where(OutboxMessage.destination_module == "housebuild-agent")
    ).all()


def test_house_catalog_ui_roles_and_public_catalog_remain_scoped(client):
    response = client.post(
        "/login",
        data={"email": "technical-prep@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/house-catalog")
    assert page.status_code == 200
    assert "House Catalog kiadáskezelés" in page.text
    assert client.get("/api/house-catalog").status_code == 200
    assert client.get("/api/housematch/catalog").status_code == 200
    assert len(client.get("/api/housematch/catalog").json()) == 45

    client.post("/logout")
    client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert client.get("/house-catalog").status_code == 403
    assert client.get("/api/housematch/catalog").status_code == 200
