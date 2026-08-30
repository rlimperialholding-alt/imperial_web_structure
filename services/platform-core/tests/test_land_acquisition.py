from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops.canonical_policy import LAND_AGENT_HARD_GATE_GDN
from app.growth_ops.catalog import _fetch
from app.growth_ops.models import GrowthSignal, OutreachMessage
from app.growth_ops.registry import BrandBinding, GrowthRegistryError
from app.growth_ops.schemas import GrowthSignalIn
from app.growth_ops.service import (
    _queue_message,
    _release_matches,
    _render_message,
    dispatch_outreach,
)
from app.land_acquisition.models import (
    LandListingPackage,
    LandOpportunity,
    LandPublicationAttempt,
)
from app.land_acquisition.registry import LandRegistryError, PortalRegistry
from app.land_acquisition.schemas import (
    AuthorityGrantIn,
    DealIn,
    ListingPackageIn,
    PackageApprovalIn,
    PublicationConfirmationIn,
    PublicationRequestIn,
    SourceVerificationIn,
)
from app.land_acquisition.service import (
    approve_package,
    confirm_publication,
    create_listing_package,
    ensure_public_html_land_routes,
    grant_authority,
    record_deal,
    request_publication,
    revoke_authority,
    scan_authority_expiry,
    sync_growth_plot_signals,
    verify_source,
)
from app.land_acquisition.service import (
    readiness as land_readiness,
)
from app.models import (
    BuildConfigCase,
    BuildConfigGate,
    BuildConfigVersion,
    HouseCatalogPlan,
    HouseCatalogVersion,
    ModuleRegistry,
    OutboxMessage,
    PlotCheckCase,
    PlotRuleSet,
)

CANONICAL_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "outbound"
    / "canonical_first_contact_templates_hu_v1.json"
)


def _signal(db, *, signal_id: str = "SIG-LAND-UAT", payload_sha: str = "1" * 64):
    signal = GrowthSignal(
        signal_id=signal_id,
        motor_key="construction",
        source_id="licensed-feed:uat",
        source_bucket="property_development",
        external_key="LISTING-UAT-001",
        signal_type="residential_building_plot",
        detected_at=datetime.now(UTC),
        subject_type="natural_person",
        recipient_email="seller@example.test",
        recipient_email_type="named",
        contact_basis="explicit_request",
        consent_evidence_id="CONSENT-UAT-001",
        location="Budapest XI. kerület",
        summary="Eladó 800 m²-es családi házas építési telek.",
        evidence_url="https://licensed-feed.example.test/listings/UAT-001",
        brand_id="Imperial Holding",
        score=88,
        urgency=50,
        confidence=95,
        dedupe_hash="2" * 64,
        source_payload_hash=payload_sha,
        status="responded",
    )
    db.add(signal)
    db.add(
        OutreachMessage(
            outreach_id="OUT-LAND-UAT",
            signal_id=signal_id,
            motor_key="construction",
            brand_id="Imperial Holding",
            sender_email="info@imperialholding.hu",
            recipient_email="seller@example.test",
            sequence_step=0,
            subject="Együttműködési lehetőség",
            body_text="Evidenced UAT outreach.",
            unsubscribe_token_hash="3" * 64,
            idempotency_key="4" * 64,
            payload_sha256="5" * 64,
            status="responded",
            response_at=datetime.now(UTC),
        )
    )
    db.commit()
    return signal


def _public_land_outreach_input(
    *,
    recipient_role: str,
    recipient_name: str,
    recipient_email: str,
    external_key: str,
    organization_name: str | None = None,
) -> GrowthSignalIn:
    return GrowthSignalIn(
        source_id="licensed-feed:uat",
        external_key=external_key,
        motor_key="construction",
        source_bucket="property_development",
        signal_type="residential_building_plot",
        detected_at=datetime.now(UTC),
        company_name=recipient_name,
        company_registration_id=None,
        recipient_organization_name=organization_name,
        subject_type=(
            "organization" if recipient_role == "listing_agent" else "natural_person"
        ),
        recipient_role=recipient_role,
        recipient_type=(
            "real_estate_agent" if recipient_role == "listing_agent" else "land_owner"
        ),
        recipient_name=recipient_name,
        sender_company_name=None,
        reference_names=[],
        reference_names_verified=False,
        recipient_classification_verified=True,
        exclusion_screening_verified=True,
        recipient_email=recipient_email,
        recipient_email_type="role" if recipient_role == "listing_agent" else "named",
        contact_basis="public_property_listing",
        public_contact_url=f"https://example.test/listing/{external_key}",
        location="Sülysáp",
        plot_size_sqm=605,
        summary="Eladó belterületi építési telek Sülysápon.",
        evidence_url=f"https://example.test/listing/{external_key}",
        brand_id="imperial",
        confidence=90,
        urgency=50,
        source_payload_hash="f" * 64,
    )


def _commercial_dependencies(db):
    now = datetime.now(UTC)
    db.add(
        PlotRuleSet(
            rule_set_id="RULE-LAND-UAT",
            municipality="Budapest XI.",
            zoning_code="LKE-UAT",
            version="2026-UAT",
            lifecycle_status="verified",
            source_url="https://or.njt.hu/uat",
            source_document_version="2026-UAT",
            source_note="UAT zoning evidence",
            maximum_coverage_percent=Decimal("30"),
            maximum_floor_area_ratio=Decimal("0.6"),
            maximum_height_m=Decimal("7.5"),
            minimum_green_percent=Decimal("50"),
            front_setback_m=Decimal("5"),
            side_setback_m=Decimal("3"),
            rear_setback_m=Decimal("6"),
            allowed_uses_json='["residential"]',
            verified_by="legal@imperial.local",
            verified_at=now,
            created_by="technical-prep@imperial.local",
        )
    )
    db.add(
        HouseCatalogPlan(
            house_id="HOUSE-LAND-UAT",
            brand="Imperial",
            canonical_name="Imperial Family 120",
            lifecycle_status="active",
            current_released_version=1,
            created_by="catalog@imperial.local",
        )
    )
    db.add(
        HouseCatalogVersion(
            catalog_version_id="HCV-LAND-UAT-1",
            house_id="HOUSE-LAND-UAT",
            version=1,
            status="released",
            catalog_price_huf=Decimal("85000000"),
            gross_area_m2=Decimal("120"),
            rooms="4+1",
            price_status="2026-UAT",
            data_quality="verified",
            lifestyles_json='["family"]',
            source_type="company-catalog",
            source_url="https://imperialholding.hu/house/UAT",
            source_verified_at="2026-08-25",
            rights_evidence="RIGHTS-UAT",
            technical_summary="Verified UAT technical snapshot.",
            change_summary="Initial UAT release.",
            content_sha256="6" * 64,
            released_by="managing-director@imperial.local",
            released_at=now,
            created_by="catalog@imperial.local",
        )
    )
    db.add(
        PlotCheckCase(
            case_id="PLOT-LAND-UAT",
            project_id="PRJ-LAND-UAT",
            title="Land acquisition UAT plot",
            address="Budapest XI., UAT utca 1.",
            parcel_number="UAT/1",
            municipality="Budapest XI.",
            zoning_code="LKE-UAT",
            rule_set_id="RULE-LAND-UAT",
            status="fit",
            current_revision=1,
            geometry_json='{"type":"Polygon","coordinates":[]}',
            geometry_crs="LOCAL-METRIC",
            geometry_sha256="7" * 64,
            declared_plot_area_m2=Decimal("800"),
            proposed_footprint_m2=Decimal("120"),
            proposed_gross_floor_area_m2=Decimal("120"),
            proposed_paved_area_m2=Decimal("80"),
            proposed_height_m=Decimal("5.5"),
            proposed_use="residential",
            proposed_width_m=Decimal("10"),
            proposed_depth_m=Decimal("12"),
            house_id="HOUSE-LAND-UAT",
            final_assessment_id="ASSESS-LAND-UAT",
            created_by="technical-prep@imperial.local",
            finalized_by="designer@imperial.local",
            finalized_at=now,
        )
    )
    db.add(
        BuildConfigCase(
            case_id="BC-LAND-UAT",
            project_id="PRJ-LAND-UAT",
            title="Land listing BuildConfig",
            housebuild_case_id="HB-LAND-UAT",
            housebuild_variant_id="HBV-LAND-UAT",
            current_version_id="BCV-LAND-UAT-1",
            status="approved",
            created_by="technical-prep@imperial.local",
            approved_by="finance@imperial.local",
            approved_at=now,
        )
    )
    db.add(
        BuildConfigVersion(
            version_id="BCV-LAND-UAT-1",
            case_id="BC-LAND-UAT",
            version_no=1,
            status="approved",
            brand="Imperial",
            technology="Danish Fabrik",
            completion_level="turnkey",
            package_name="Family",
            gross_area_m2=Decimal("120"),
            currency="HUF",
            vat_rate=Decimal("0.05"),
            option_json="[]",
            bom_json="[]",
            payment_schedule_json="[]",
            capacity_json="{}",
            pricing_snapshot_json='{"cash_buffer_percent":25}',
            source_sha256="8" * 64,
            config_sha256="9" * 64,
            bom_sha256="a" * 64,
            net_cost_huf=Decimal("50000000"),
            net_price_huf=Decimal("70000000"),
            vat_huf=Decimal("3500000"),
            gross_price_huf=Decimal("73500000"),
            margin_percent=Decimal("40"),
            duration_days=240,
            created_by="technical-prep@imperial.local",
            approved_by="finance@imperial.local",
            approved_at=now,
        )
    )
    for key in ("pricing", "margin", "cashflow"):
        db.add(
            BuildConfigGate(
                version_id="BCV-LAND-UAT-1",
                gate_key=key,
                decision="approved",
                evidence_refs_json='["UAT-EVIDENCE"]',
                evidence_sha256="b" * 64,
                note=f"Approved UAT {key} gate.",
                decided_by="finance@imperial.local",
                decided_at=now,
            )
        )
    db.commit()


def _approved_package(db):
    signal = _signal(db)
    assert sync_growth_plot_signals(db) == {"seen": 1, "created": 1, "updated": 0}
    assert sync_growth_plot_signals(db) == {"seen": 1, "created": 0, "updated": 0}
    opportunity = db.scalar(select(LandOpportunity))
    verify_source(
        db,
        opportunity.opportunity_id,
        SourceVerificationIn(
            expected_source_sha256=signal.source_payload_hash,
            note="The licensed source snapshot and active listing were manually verified.",
            actor="source-reviewer@imperial.local",
        ),
    )
    record_deal(
        db,
        opportunity.opportunity_id,
        DealIn(
            evidence_ref="crm://growth/OUT-LAND-UAT/response",
            evidence_sha256="c" * 64,
            actor="sales@imperial.local",
        ),
    )
    grant = grant_authority(
        db,
        opportunity.opportunity_id,
        AuthorityGrantIn(
            grantor_reference="seller-contract-UAT",
            scopes=["advertising", "media_use", "pricing", "withdrawal", "website", "portals"],
            evidence_ref="drive://legal/LAND-AUTH-UAT",
            evidence_sha256="d" * 64,
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
            valid_until=datetime.now(UTC) + timedelta(days=30),
            created_by="legal-prep@imperial.local",
            approved_by="legal@imperial.local",
        ),
    )
    _commercial_dependencies(db)
    package = create_listing_package(
        db,
        opportunity.opportunity_id,
        ListingPackageIn(
            authority_grant_id=grant.grant_id,
            plotcheck_case_id="PLOT-LAND-UAT",
            house_id="HOUSE-LAND-UAT",
            catalog_version_id="HCV-LAND-UAT-1",
            buildconfig_case_id="BC-LAND-UAT",
            buildconfig_version_id="BCV-LAND-UAT-1",
            plot_price_huf=90_000_000,
            media_asset_ids=["MEDIA-LAND-UAT", "MEDIA-HOUSE-UAT"],
            contact_route="crm://imperial/land/UAT",
            actor="listing-prep@imperial.local",
        ),
    )
    with pytest.raises(ValueError, match="creator cannot approve"):
        approve_package(
            db,
            package.package_id,
            PackageApprovalIn(
                expected_payload_sha256=package.payload_sha256,
                note="Self approval must remain blocked in every environment.",
                actor="listing-prep@imperial.local",
            ),
        )
    package = approve_package(
        db,
        package.package_id,
        PackageApprovalIn(
            expected_payload_sha256=package.payload_sha256,
            note="Legal, technical and commercial evidence reviewed for UAT release.",
            actor="release-reviewer@imperial.local",
        ),
    )
    return opportunity, grant, package


def _portal_registry(tmp_path: Path, *, enabled: bool = True) -> Path:
    registry_path = tmp_path / "portals-public-html.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "portals": [
                    {
                        "key": "ingatlan_com",
                        "domains": ["ingatlan.com"],
                        "discovery_mode": "public_html" if enabled else "manual",
                        "publish_mode": "manual",
                        "discovery_enabled": enabled,
                        "publish_enabled": False,
                        "adapter_module": None,
                        "respect_robots_txt": enabled,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry_path


def test_public_html_registry_requires_robots_enforcement():
    with pytest.raises(LandRegistryError, match="robots.txt enforcement is required"):
        PortalRegistry(
            {
                "version": 1,
                "portals": [
                    {
                        "key": "ingatlan_com",
                        "domains": ["ingatlan.com"],
                        "discovery_mode": "public_html",
                        "publish_mode": "manual",
                        "discovery_enabled": True,
                        "publish_enabled": False,
                        "adapter_module": None,
                        "respect_robots_txt": False,
                    }
                ],
            }
        )


def test_named_portal_requires_explicit_public_html_registry(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LAND_ACQUISITION_PORTAL_REGISTRY_FILE",
        str(_portal_registry(tmp_path, enabled=False)),
    )
    monkeypatch.setattr(
        "app.growth_ops.catalog.httpx.Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call forbidden")),
    )
    result = _fetch(
        SimpleNamespace(
            route_url="https://www.ingatlan.com/123456",
            source_record_json="{}",
        )
    )
    assert result == {
        "status": "rejected",
        "error_type": "portal_public_html_not_enabled",
    }


def test_public_html_portal_respects_robots_and_reads_allowed_page(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LAND_ACQUISITION_PORTAL_REGISTRY_FILE",
        str(_portal_registry(tmp_path)),
    )
    from app.growth_ops import catalog

    monkeypatch.setattr(catalog, "_fresh_pinned_robots_error", lambda *_a, **_k: None)
    monkeypatch.setattr(
        catalog,
        "_pinned_https_get",
        lambda url, **_kwargs: {
            "status_code": 200,
            "headers": {"content-type": "text/html; charset=utf-8"},
            "body": (
                b"<html><head><title>Elado telek</title></head>"
                b"<body>Elado 800 m2-es epitesi telek.</body></html>"
            ),
            "source_ip": "93.184.216.34",
        },
    )
    result = _fetch(
        SimpleNamespace(
            route_url="https://www.ingatlan.com/35500001",
            source_record_json="{}",
        )
    )

    assert result["status"] == "succeeded"
    assert result["evidence"]["discovery_mode"] == "public_html"
    assert result["evidence"]["robots_txt"] == "allowed"
    assert "800 m2-es epitesi telek" in result["analysis_text"]


def test_public_html_portal_does_not_fetch_robots_disallowed_path(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LAND_ACQUISITION_PORTAL_REGISTRY_FILE",
        str(_portal_registry(tmp_path)),
    )
    from app.growth_ops import catalog

    monkeypatch.setattr(
        catalog,
        "_fresh_pinned_robots_error",
        lambda *_args, **_kwargs: "portal_robots_disallowed",
    )
    monkeypatch.setattr(
        catalog,
        "_pinned_https_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("robots-disallowed listing must not be fetched")
        ),
    )
    result = _fetch(
        SimpleNamespace(
            route_url="https://www.ingatlan.com/lista/elado+telek",
            source_record_json="{}",
        )
    )

    assert result == {"status": "rejected", "error_type": "portal_robots_disallowed"}


def test_public_html_portal_retries_after_temporary_robots_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LAND_ACQUISITION_PORTAL_REGISTRY_FILE",
        str(_portal_registry(tmp_path)),
    )
    from app.growth_ops import catalog

    monkeypatch.setattr(
        catalog,
        "_fresh_pinned_robots_error",
        lambda *_args, **_kwargs: "portal_robots_unavailable",
    )
    monkeypatch.setattr(
        catalog,
        "_pinned_https_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("page must not be fetched without a usable robots policy")
        ),
    )
    result = _fetch(
        SimpleNamespace(
            route_url="https://www.ingatlan.com/35500001",
            source_record_json="{}",
        )
    )

    assert result == {"status": "failed", "error_type": "portal_robots_unavailable"}


def test_land_readiness_fails_closed_without_a_public_html_route(db):
    ready, detail = land_readiness(db)

    assert ready is False
    assert detail["live_discovery"] is False
    assert detail["blocking_reasons"][0] == "no_public_html_land_routes_configured"
    assert len(
        [
            reason
            for reason in detail["blocking_reasons"]
            if reason.startswith("public_land_route:")
        ]
    ) == 7


def test_land_readiness_accepts_enabled_public_html_route(db):
    result = ensure_public_html_land_routes(db, dry_run=False)
    assert result["readback_pass"] is True

    ready, detail = land_readiness(db)

    assert ready is True
    assert detail["live_discovery"] is True
    assert detail["registry"]["public_html_route_counts"]["ingatlan_com"] == 1


def test_land_outreach_copy_is_specific_simple_and_actionable(monkeypatch):
    monkeypatch.setenv(
        "CANONICAL_FIRST_CONTACT_REGISTRY_FILE", str(CANONICAL_REGISTRY_PATH)
    )
    monkeypatch.setattr(
        "app.growth_ops.service.settings",
        lambda: SimpleNamespace(base_url="https://growth.imperialholding.test"),
    )
    signal = GrowthSignal(
        signal_id="SIG-LAND-COPY",
        motor_key="construction",
        source_id="licensed-feed:uat",
        source_bucket="property_development",
        external_key="LISTING-COPY-001",
        signal_type="residential_building_plot",
        detected_at=datetime.now(UTC),
        company_name="Nagy Gergő",
        recipient_organization_name="Duna House",
        subject_type="natural_person",
        recipient_role="listing_agent",
        recipient_email="nagy.gergo1@dh.hu",
        recipient_email_type="named",
        contact_basis="public_property_listing",
        location="sülysápi, 605 m²-es",
        summary="Eladó belterületi építési telek Sülysápon.",
        evidence_url="https://example.test/listing/COPY-001",
        brand_id="imperial",
        score=90,
        urgency=50,
        confidence=90,
        dedupe_hash="0" * 64,
        source_payload_hash="1" * 64,
        status="blocked",
    )
    binding = BrandBinding(
        brand_id="imperial",
        sender_email="info@imperialholding.hu",
        domain_key="imperialholding.hu",
        secret={},
        config={
            "brand_name": "Imperial Holding",
            "templates": {
                "default": {
                    "initial": {
                        "subject": "unused land-specific subject",
                        "body": "unused land-specific body",
                    }
                }
            },
        },
    )
    agent_data = _public_land_outreach_input(
        recipient_role="listing_agent",
        recipient_name="Nagy Gergő",
        recipient_email="nagy.gergo1@dh.hu",
        external_key="COPY-001",
        organization_name="Duna House",
    )
    subject, body, metadata = _render_message(
        signal,
        binding,
        step=0,
        unsubscribe_token="UAT-XY-CC-ZZ-TOKEN",
        data=agent_data,
    )
    assert metadata["template_id"] == "REAL_ESTATE_AGENT_FIRST_CONTACT_HU"
    assert subject == "ház eladásában kérnék segítséget"
    assert (
        "Cégünk, az Imperial Holding, előregyártott készházak és típusházak "
        "építésével foglalkozik"
    ) in body
    assert (
        "2,5% jutalékot fizetünk azoknak az ingatlanos partnereinknek, akik a "
        "hirdetett telkeik mellé valamelyik típusházunkat is eladják."
    ) in body
    assert "Jelenleg is számos ingatlan-irodával dolgozunk együtt" in body
    assert "látványtervvel, alaprajzzal és műszaki leírással" in body
    assert "2,5% jutalékot fizetünk Önnek a típusterv árából" in body
    assert "Érdekli ez a lehetőség?" in body
    assert (
        "Leiratkozás: "
        "https://growth.imperialholding.test/growth/unsubscribe/UAT-XY-CC-ZZ-TOKEN"
    ) in body

    signal.recipient_role = "property_owner"
    signal.company_name = "Kovács Péter"
    owner_data = _public_land_outreach_input(
        recipient_role="property_owner",
        recipient_name="Kovács Péter",
        recipient_email="owner@example.test",
        external_key="COPY-002",
    )
    subject, body, metadata = _render_message(
        signal,
        binding,
        step=0,
        unsubscribe_token="UAT-OWNER-TOKEN",
        data=owner_data,
    )
    assert metadata["template_id"] == "LAND_OWNER_FIRST_CONTACT_HU"
    assert subject == (
        "Ingyen elkészítjük a Sülysáp, 605 m²-es telek + típusház hirdetését"
    )
    assert "Az Ön által hirdetett Sülysáp, 605 m²-es építési telek miatt keresem." in body
    assert "Az Imperial Holding típustervek kulcsrakész építésével foglalkozik." in body
    assert "Ingyen, jutalék nélkül meghirdetjük az ingatlanát" in body
    assert "semmilyen kötelezettséget nem vállal" in body
    assert "Csak az írásos engedélyét kérjük" in body
    assert "„Engedélyezem a telek hirdetését.”" in body
    assert "Hirdetés: https://example.test/listing/COPY-002" in body
    assert "2,5%" not in body
    assert (
        "Leiratkozás: https://growth.imperialholding.test/growth/unsubscribe/UAT-OWNER-TOKEN"
    ) in body


@pytest.mark.parametrize("recipient_role", ["listing_agent", "property_owner"])
def test_owner_approved_land_initial_email_is_policy_released(
    db, monkeypatch, recipient_role
):
    monkeypatch.setenv(
        "CANONICAL_FIRST_CONTACT_REGISTRY_FILE", str(CANONICAL_REGISTRY_PATH)
    )
    monkeypatch.setattr(
        "app.growth_ops.service.settings",
        lambda: SimpleNamespace(base_url="https://growth.imperialholding.test"),
    )
    signal = GrowthSignal(
        signal_id=f"SIG-LAND-RELEASE-{recipient_role}",
        motor_key="construction",
        source_id="licensed-feed:uat",
        source_bucket="property_development",
        external_key=f"LISTING-RELEASE-{recipient_role}",
        signal_type="residential_building_plot",
        detected_at=datetime.now(UTC),
        company_name="Nyilvános hirdető",
        recipient_organization_name=(
            "Független Ingatlaniroda" if recipient_role == "listing_agent" else None
        ),
        subject_type=(
            "organization" if recipient_role == "listing_agent" else "natural_person"
        ),
        recipient_role=recipient_role,
        recipient_email=f"{recipient_role}@example.test",
        recipient_email_type="role" if recipient_role == "listing_agent" else "named",
        contact_basis=(
            "documented_consent"
            if recipient_role == "property_owner"
            else "public_property_listing"
        ),
        consent_evidence_id=(
            "CONSENT-LAND-OWNER-RELEASE"
            if recipient_role == "property_owner"
            else None
        ),
        public_contact_url="https://example.test/listing/RELEASE-001",
        location="Sülysáp",
        plot_size_sqm=605,
        summary="Eladó belterületi építési telek Sülysápon.",
        evidence_url="https://example.test/listing/RELEASE-001",
        brand_id="imperial",
        score=90,
        urgency=50,
        confidence=90,
        dedupe_hash=("a" if recipient_role == "listing_agent" else "b") * 64,
        source_payload_hash=("c" if recipient_role == "listing_agent" else "d") * 64,
        status="accepted",
    )
    binding = BrandBinding(
        brand_id="imperial",
        sender_email="info@imperialholding.hu",
        domain_key="imperialholding.hu",
        secret={},
        config={
            "brand_name": "Imperial Holding",
            "templates": {
                "default": {
                    "initial": {"subject": "unused", "body": "unused"},
                    "followup_1": {"subject": "unused", "body": "unused"},
                }
            },
        },
    )
    db.add(signal)
    db.flush()
    data = _public_land_outreach_input(
        recipient_role=recipient_role,
        recipient_name="Nyilvános hirdető",
        recipient_email=f"{recipient_role}@example.test",
        external_key=f"RELEASE-{recipient_role}",
        organization_name=(
            "Független Ingatlaniroda" if recipient_role == "listing_agent" else None
        ),
    )
    if recipient_role == "property_owner":
        data.contact_basis = "documented_consent"
        data.consent_evidence_id = "CONSENT-LAND-OWNER-RELEASE"

    initial = _queue_message(
        db,
        signal,
        binding,
        step=0,
        available_at=datetime.now(UTC),
        enforce_recipient_cooldown=False,
        data=data,
        source_evidence_manifest_sha256=(
            "e" * 64 if recipient_role == "listing_agent" else None
        ),
    )
    with pytest.raises(
        GrowthRegistryError, match="owner_approved_followup_template_missing_no_send"
    ):
        _queue_message(
            db,
            signal,
            binding,
            step=1,
            available_at=datetime.now(UTC),
            enforce_recipient_cooldown=False,
            data=data,
            source_evidence_manifest_sha256=(
                "e" * 64 if recipient_role == "listing_agent" else None
            ),
        )

    assert initial.release_approved_by == "owner-policy:land-public-listing-v3:2026-08-28"
    assert initial.release_approved_at is not None
    assert initial.release_token_hash and _release_matches(initial)
    canonical_metadata = json.loads(initial.receipt_json)["canonical_template"]
    assert canonical_metadata["template_id"] == (
        "REAL_ESTATE_AGENT_FIRST_CONTACT_HU"
        if recipient_role == "listing_agent"
        else "LAND_OWNER_FIRST_CONTACT_HU"
    )
    assert "template_policy" not in canonical_metadata
    if recipient_role == "listing_agent":
        assert initial.body_html
        assert (
            "<strong>2,5% jutalékot fizetünk azoknak az ingatlanos partnereinknek"
            in initial.body_html
        )
    else:
        assert initial.body_html is not None


def test_dispatch_blocks_legacy_queued_gdn_agent_before_registry_or_smtp(db):
    signal = GrowthSignal(
        signal_id="SIG-LAND-GDN-LEGACY",
        motor_key="construction",
        source_id="licensed-feed:legacy",
        source_bucket="property_development",
        external_key="LISTING-GDN-LEGACY",
        signal_type="residential_building_plot",
        detected_at=datetime.now(UTC),
        company_name="Minta Értékesítő",
        recipient_organization_name="GDN Ingatlanhálózat",
        recipient_office_name="GDN Belvárosi Iroda",
        subject_type="natural_person",
        recipient_role="listing_agent",
        recipient_email="ertekesito@gdn-ingatlan.hu",
        recipient_email_type="named",
        contact_basis="public_property_listing",
        public_contact_url="https://gdn-ingatlan.hu/ingatlan/LEGACY",
        location="Budapest",
        summary="Korábban sorba állított építési telek hirdetése.",
        evidence_url="https://gdn-ingatlan.hu/ingatlan/LEGACY",
        brand_id="Imperial",
        score=90,
        urgency=50,
        confidence=90,
        dedupe_hash="e" * 64,
        source_payload_hash="f" * 64,
        status="queued",
    )
    message = OutreachMessage(
        outreach_id="OUT-LAND-GDN-LEGACY",
        signal_id=signal.signal_id,
        motor_key="construction",
        brand_id="Imperial",
        sender_email="info@imperialholding.hu",
        recipient_email=signal.recipient_email,
        sequence_step=0,
        subject="legacy queued message",
        body_text="Legacy queued outreach that must never be dispatched.",
        unsubscribe_token_hash="1" * 64,
        idempotency_key="2" * 64,
        payload_sha256="3" * 64,
        status="claimed",
        claimed_by="legacy-worker",
        claimed_at=datetime.now(UTC),
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    db.add_all([signal, message])
    db.commit()

    result = dispatch_outreach(db, message)

    assert result.status == "blocked"
    assert result.last_error == LAND_AGENT_HARD_GATE_GDN
    assert signal.status == "blocked"
    assert signal.rejection_reasons_json == f'["{LAND_AGENT_HARD_GATE_GDN}"]'


def test_generic_scanner_rejects_private_and_cgnat_targets(monkeypatch):
    for address in ("127.0.0.1", "10.10.0.8", "100.64.0.1"):
        monkeypatch.setattr(
            "app.growth_ops.catalog.socket.getaddrinfo",
            lambda *args, address=address, **kwargs: [(2, 1, 6, "", (address, 443))],
        )
        result = _fetch(
            SimpleNamespace(
                route_url="https://scanner-target.example.test/source",
                source_record_json="{}",
            )
        )
        assert result == {"status": "rejected", "error_type": "non_public_target"}


def test_deal_package_and_disabled_portals_fail_closed(db):
    opportunity, _grant, package = _approved_package(db)
    attempts = request_publication(
        db,
        package.package_id,
        PublicationRequestIn(
            channels=["ingatlan_com", "zenga", "imperial_plot_finder"],
            actor="publishing@imperial.local",
        ),
    )
    assert {row.status for row in attempts} == {"BLOCKED"}
    assert all(row.outbox_message_id is None for row in attempts)
    assert not db.scalars(
        select(OutboxMessage).where(OutboxMessage.message_id.like("MSG-LAND-%"))
    ).all()
    assert opportunity.state == "PUBLISH_APPROVED"
    stored = db.scalar(
        select(LandListingPackage).where(LandListingPackage.package_id == package.package_id)
    )
    assert stored.payload_sha256 == package.payload_sha256
    assert "total_indicative_price_huf" in stored.payload_json


def test_licensed_adapter_requires_healthy_module_and_readback_proof(db, tmp_path, monkeypatch):
    opportunity, _grant, package = _approved_package(db)
    registry_path = tmp_path / "portals.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "portals": [
                    {
                        "key": "imperial_plot_finder",
                        "domains": ["imperialholding.hu"],
                        "discovery_mode": "manual",
                        "publish_mode": "licensed_api",
                        "discovery_enabled": False,
                        "publish_enabled": True,
                        "adapter_module": "imperial-plot-finder-adapter",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LAND_ACQUISITION_PORTAL_REGISTRY_FILE", str(registry_path))

    blocked = request_publication(
        db,
        package.package_id,
        PublicationRequestIn(
            channels=["imperial_plot_finder"],
            actor="publishing@imperial.local",
        ),
    )[0]
    assert blocked.status == "BLOCKED"

    # The same blocked idempotency key becomes queueable only after the module
    # registry has a successful integration-test receipt.
    db.add(
        ModuleRegistry(
            module_key="imperial-plot-finder-adapter",
            name="Imperial Plot Finder Adapter",
            lifecycle_status="pilot",
            integration_status="healthy",
            last_integration_test_at=datetime.now(UTC),
            last_integration_test_status="passed",
        )
    )
    db.commit()
    queued = request_publication(
        db,
        package.package_id,
        PublicationRequestIn(
            channels=["imperial_plot_finder"],
            actor="publishing@imperial.local",
        ),
    )[0]
    assert queued.status == "QUEUED"
    assert queued.outbox_message_id
    with pytest.raises(ValueError, match="does not belong"):
        confirm_publication(
            db,
            queued.attempt_id,
            PublicationConfirmationIn(
                external_id="PLOT-UAT-001",
                public_url="https://example.test/forged",
                proof={"readback_payload_sha256": package.payload_sha256},
                actor="reconciliation@imperial.local",
            ),
        )
    confirmed = confirm_publication(
        db,
        queued.attempt_id,
        PublicationConfirmationIn(
            external_id="PLOT-UAT-001",
            public_url="https://plots.imperialholding.hu/PLOT-UAT-001",
            proof={"readback_payload_sha256": package.payload_sha256},
            actor="reconciliation@imperial.local",
        ),
    )
    assert confirmed.status == "SUCCEEDED"
    db.refresh(opportunity)
    assert opportunity.state == "PUBLISHED"


def test_revoked_authority_creates_idempotent_takedown_requirement(db):
    opportunity, grant, package = _approved_package(db)
    publication = LandPublicationAttempt(
        attempt_id="LPUB-LIVE-UAT",
        opportunity_id=opportunity.opportunity_id,
        package_id=package.package_id,
        channel="ingatlan_com",
        action="PUBLISH",
        idempotency_key="e" * 64,
        payload_sha256=package.payload_sha256,
        status="SUCCEEDED",
        external_id="ING-UAT-1",
        public_url="https://ingatlan.com/ING-UAT-1",
        proof_json='{"readback":"verified"}',
        proof_sha256="f" * 64,
        created_by="publishing@imperial.local",
        completed_at=datetime.now(UTC),
    )
    db.add(publication)
    db.commit()
    revoke_authority(
        db,
        grant.grant_id,
        actor="legal@imperial.local",
        reason="The owner withdrew advertising and publication authority immediately.",
    )
    db.refresh(opportunity)
    assert opportunity.state == "TAKEDOWN_REQUIRED"
    withdrawals = db.scalars(
        select(LandPublicationAttempt).where(LandPublicationAttempt.action == "WITHDRAW")
    ).all()
    assert len(withdrawals) == 1
    assert withdrawals[0].status == "WITHDRAWAL_REQUIRED"
    assert scan_authority_expiry(db)["withdrawals"] == 0
    assert (
        db.scalar(
            select(LandPublicationAttempt).where(LandPublicationAttempt.action == "WITHDRAW")
        ).attempt_id
        == withdrawals[0].attempt_id
    )
