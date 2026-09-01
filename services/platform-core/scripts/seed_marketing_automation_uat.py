from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    ContentAssetRecord,
    CopyBriefRecord,
    MarketingCampaign,
    MarketingLead,
    MarketingOptimizationDecision,
)
from app.services.marketing_automation import (
    activate_campaign,
    approve_campaign,
    campaign_performance,
    capture_lead,
    create_campaign,
    decide_optimization,
    decide_sales_lead,
    execute_optimization,
    handoff_lead_to_crm,
    ingest_campaign_metric,
    propose_optimization,
    qualify_lead,
    submit_campaign,
)

UTM_CAMPAIGN = "imperial-server-uat-2026-08"
LEAD_EMAIL = "marketing-uat@imperial.local"
PERFORMANCE_LEAD_EMAIL = "marketing-performance-uat@imperial.local"
ASSET_ID = "ASSET-MKT-SERVER-UAT"
BRIEF_ID = "CB-MKT-SERVER-UAT"
METRIC_EXTERNAL_KEY = "imperial-server-uat-2026-08-01"


def _actor(role: str):
    return SimpleNamespace(role=role, email=f"{role}@imperial.local")


def _ensure_published_asset(db, campaign_id: str) -> None:
    if db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == ASSET_ID)):
        return
    now = datetime.now(UTC)
    db.add(
        CopyBriefRecord(
            copy_brief_id=BRIEF_ID,
            brand_id="imperial",
            asset_type="landing_page",
            channel="web",
            campaign_id=campaign_id,
            status="STRATEGY_APPROVED",
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=365),
            brief_json='{"purpose":"controlled server UAT"}',
            source_snapshot_hash="a" * 64,
            created_by="marketing@imperial.local",
        )
    )
    # PostgreSQL enforces the brief foreign key immediately. Flush the parent
    # before the synthetic UAT asset so this seed proves the production path,
    # not SQLite's more permissive default behavior.
    db.flush()
    db.add(
        ContentAssetRecord(
            asset_id=ASSET_ID,
            copy_brief_id=BRIEF_ID,
            brand_id="imperial",
            asset_type="landing_page",
            channel="web",
            state="PUBLISHED",
            content_hash="b" * 64,
            content_json='{"purpose":"controlled server UAT"}',
            gate_1_approved=True,
            expert_language_approved=True,
            expert_marketing_approved=True,
            copywriter_approved=True,
            four_gate_approved=True,
            editorial_approved=True,
            owner_approved=True,
            source_prevalidated=True,
            creative_director_approved=True,
            assembly_approved=True,
            campaign_package_approved=True,
            campaign_package_hash="c" * 64,
            campaign_artifact_set_hash="d" * 64,
            release_approved=True,
            live_review_approved=True,
            active_bundle_id="BUNDLE-MKT-SERVER-UAT",
            publication_proof_id="PROOF-MKT-SERVER-UAT",
            published_at=now,
            created_by="marketing@imperial.local",
        )
    )
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        campaign = db.scalar(
            select(MarketingCampaign).where(MarketingCampaign.utm_campaign == UTM_CAMPAIGN)
        )
        if not campaign:
            campaign = create_campaign(
                db,
                _actor("marketing"),
                name="Imperial marketing automatizmus szerver-UAT",
                brand_id="imperial",
                objective="A kampányjóváhagyás és a tartalomkapu szerveroldali ellenőrzése.",
                audience="Kontrollált, szintetikus UAT célközönség éles ügyféladatok nélkül.",
                channels=["meta", "google"],
                budget_net="1000000",
                currency="HUF",
                target_leads=10,
                target_cpl_net="100000",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 12, 31),
                utm_source="uat",
                utm_medium="controlled_test",
                utm_campaign=UTM_CAMPAIGN,
                landing_page_url="https://imperialholding.hu/uat-marketing",
            )
        if campaign.status == "draft":
            campaign = submit_campaign(db, campaign.campaign_id, _actor("marketing"))
        if campaign.status == "review":
            campaign = approve_campaign(db, campaign.campaign_id, _actor("owner"))
        _ensure_published_asset(db, campaign.campaign_id)
        if campaign.status == "approved":
            campaign = activate_campaign(db, campaign.campaign_id, _actor("marketing"))

        lead = db.scalar(select(MarketingLead).where(MarketingLead.email == LEAD_EMAIL))
        if not lead:
            lead = capture_lead(
                db,
                _actor("marketing"),
                campaign_id="",
                source="controlled_server_uat",
                channel="web",
                landing_page_url="https://imperialholding.hu/uat-marketing",
                utm_source="uat",
                utm_medium="controlled_test",
                utm_campaign=UTM_CAMPAIGN,
                utm_content="server-seed",
                full_name="Marketing Automatizmus UAT Lead",
                email=LEAD_EMAIL,
                phone="+36 30 000 0001",
                company="Imperial UAT",
                lead_type="b2b",
                project_location="Budapest",
                estimated_budget_huf="150000000",
                timeframe_months=3,
                intent_summary=(
                    "Kontrollált tesztprojekt a Lead Intelligence és CRM-átadás ellenőrzésére."
                ),
                privacy_notice_accepted=True,
                privacy_notice_version="privacy-2026-08-uat",
                marketing_consent=False,
            )
        if lead.status in {"scored", "sales_rejected"}:
            lead = qualify_lead(
                db,
                lead.lead_id,
                _actor("marketing"),
                note="Kontrollált szerver-UAT lead minősítési ellenőrzése sikeres.",
                override_reason="",
            )
        if lead.status == "marketing_qualified":
            lead = handoff_lead_to_crm(
                db,
                lead.lead_id,
                _actor("marketing"),
                assigned_sales_email="sales@imperial.local",
            )
        if lead.status == "crm_handoff":
            lead = decide_sales_lead(
                db,
                lead.lead_id,
                _actor("sales"),
                decision="accept",
                note="Kontrollált szerver-UAT értékesítői átvétel sikeres.",
            )

        performance_lead = db.scalar(
            select(MarketingLead).where(MarketingLead.email == PERFORMANCE_LEAD_EMAIL)
        )
        if not performance_lead:
            performance_lead = capture_lead(
                db,
                _actor("marketing"),
                campaign_id=campaign.campaign_id,
                source="controlled_performance_uat",
                channel="web",
                landing_page_url=campaign.landing_page_url,
                utm_source=campaign.utm_source,
                utm_medium=campaign.utm_medium,
                utm_campaign=campaign.utm_campaign,
                utm_content="performance-seed",
                full_name="Marketing Teljesítmény UAT Lead",
                email=PERFORMANCE_LEAD_EMAIL,
                phone="+36 30 000 0002",
                company="Imperial UAT",
                lead_type="b2b",
                project_location="Budapest",
                estimated_budget_huf="150000000",
                timeframe_months=3,
                intent_summary="Kontrollált kampányteljesítmény- és optimalizálási UAT lead.",
                privacy_notice_accepted=True,
                privacy_notice_version="privacy-2026-08-uat",
                marketing_consent=False,
            )
        if performance_lead.status == "scored":
            performance_lead = qualify_lead(
                db,
                performance_lead.lead_id,
                _actor("marketing"),
                note="A kontrollált teljesítmény-UAT lead minősítési feltételei teljesültek.",
                override_reason="",
            )

        metric = ingest_campaign_metric(
            db,
            _actor("marketing"),
            campaign_id=campaign.campaign_id,
            asset_id=ASSET_ID,
            metric_date=date(2026, 8, 1),
            channel="meta",
            source_system="meta_ads_uat",
            external_key=METRIC_EXTERNAL_KEY,
            impressions=10000,
            clicks=200,
            landing_sessions=180,
            form_starts=20,
            form_completes=10,
            platform_conversions=8,
            spend_net="80000",
            currency="HUF",
            raw_payload={"adapter": "controlled_server_uat", "version": 1},
        )
        optimization = db.scalar(
            select(MarketingOptimizationDecision).where(
                MarketingOptimizationDecision.campaign_id == campaign.campaign_id
            )
        )
        if not optimization:
            optimization = propose_optimization(
                db,
                campaign.campaign_id,
                _actor("owner"),
                rationale="Kontrollált szerver-UAT a jóváhagyott keretemelési folyamatra.",
            )
        if optimization.status == "proposed":
            optimization = decide_optimization(
                db,
                optimization.decision_id,
                _actor("managing-director"),
                decision="approve",
                note="A kontrollált teljesítménymérés alapján a javaslat jóváhagyható.",
            )
        if optimization.status == "approved":
            optimization = execute_optimization(db, optimization.decision_id, _actor("marketing"))
        performance = campaign_performance(db, campaign.campaign_id)
        print(
            {
                "campaign_id": campaign.campaign_id,
                "campaign_status": campaign.status,
                "content_gate_evidence": ASSET_ID,
                "lead_id": lead.lead_id,
                "lead_status": lead.status,
                "lead_score": lead.score,
                "crm_record_id": lead.crm_record_id,
                "signal_count": lead.signal_count,
                "performance_lead_id": performance_lead.lead_id,
                "metric_id": metric.metric_id,
                "spend_net": str(performance["spend_net"]),
                "actual_cpl_net": str(performance["actual_cpl_net"]),
                "optimization_id": optimization.decision_id,
                "optimization_type": optimization.decision_type,
                "optimization_status": optimization.status,
            }
        )


if __name__ == "__main__":
    main()
