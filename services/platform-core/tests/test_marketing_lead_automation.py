import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (
    ContentAssetRecord,
    ContentPerformanceMetric,
    CopyBriefRecord,
    EnterpriseCanonicalRecord,
    MailSuppression,
    MarketingCampaignDailyMetric,
    MarketingLead,
    MarketingLeadActivity,
    ModuleBusinessRecord,
    ProjectRegistry,
    TaskRecord,
)
from app.services.marketing_automation import (
    activate_campaign,
    approve_campaign,
    campaign_performance,
    capture_lead,
    complete_campaign,
    create_campaign,
    decide_optimization,
    decide_sales_lead,
    execute_optimization,
    handoff_lead_to_crm,
    ingest_campaign_metric,
    propose_optimization,
    qualify_lead,
    set_marketing_consent,
    submit_campaign,
    withdraw_marketing_consent_by_token,
)
from app.seed import DEMO_PASSWORD


def _user(role: str):
    return SimpleNamespace(role=role, email=f"{role}@imperial.local")


def _campaign(db, suffix: str):
    row = create_campaign(
        db,
        _user("marketing"),
        name=f"Imperial leadkampány {suffix}",
        brand_id="imperial",
        objective="Minősített családiház-építési érdeklődők megszerzése és mérése.",
        audience="Építkezést hat hónapon belül kezdő, megfelelő kerettel rendelkező családok.",
        channels=["meta", "google", "email", "meta"],
        budget_net="5000000",
        currency="HUF",
        target_leads=50,
        target_cpl_net="100000",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 10, 31),
        utm_source="meta",
        utm_medium="paid_social",
        utm_campaign=f"imperial-uat-{suffix.lower()}",
        landing_page_url="https://imperialholding.hu/uat",
    )
    submit_campaign(db, row.campaign_id, _user("marketing"))
    return approve_campaign(db, row.campaign_id, _user("owner"))


def _published_campaign_asset(db, campaign_id: str, suffix: str) -> None:
    now = datetime.now(UTC)
    brief_id = f"CB-MKT-{suffix}"
    db.add(
        CopyBriefRecord(
            copy_brief_id=brief_id,
            brand_id="imperial",
            asset_type="landing_page",
            channel="web",
            campaign_id=campaign_id,
            status="STRATEGY_APPROVED",
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=90),
            brief_json="{}",
            source_snapshot_hash="a" * 64,
            created_by="marketing@imperial.local",
        )
    )
    db.add(
        ContentAssetRecord(
            asset_id=f"ASSET-MKT-{suffix}",
            copy_brief_id=brief_id,
            brand_id="imperial",
            asset_type="landing_page",
            channel="web",
            state="PUBLISHED",
            content_hash="b" * 64,
            content_json="{}",
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
            active_bundle_id=f"BUNDLE-MKT-{suffix}",
            publication_proof_id=f"PROOF-MKT-{suffix}",
            published_at=now,
            created_by="marketing@imperial.local",
        )
    )
    db.commit()


def _capture(
    db,
    campaign_id: str,
    *,
    email: str = "lead.uat@example.test",
    utm_campaign: str = "imperial-uat-flow",
):
    return capture_lead(
        db,
        _user("marketing"),
        campaign_id=campaign_id,
        source="landing_form",
        channel="web",
        landing_page_url="https://imperialholding.hu/uat",
        utm_source="meta",
        utm_medium="paid_social",
        utm_campaign=utm_campaign,
        utm_content="hero-a",
        full_name="Kontrollált Lead UAT",
        email=email,
        phone="+36 30 123 4567",
        company="",
        lead_type="b2c",
        project_location="Budapest XI. kerület",
        estimated_budget_huf="120000000",
        timeframe_months=3,
        intent_summary=("Nettó százötven négyzetméteres családi ház teljes körű megvalósítása."),
        privacy_notice_accepted=True,
        privacy_notice_version="privacy-2026-08",
        marketing_consent=True,
    )


def test_campaign_activation_is_four_eye_and_content_fail_closed(db):
    campaign = _campaign(db, "GATE")
    assert campaign.status == "approved"
    with pytest.raises(ValueError, match="publikált"):
        activate_campaign(db, campaign.campaign_id, _user("marketing"))
    _published_campaign_asset(db, campaign.campaign_id, "GATE")
    active = activate_campaign(db, campaign.campaign_id, _user("marketing"))
    assert active.status == "active"
    assert active.approved_by == "owner@imperial.local"
    assert active.activated_at is not None
    assert complete_campaign(db, campaign.campaign_id, _user("marketing")).status == "completed"


def test_lead_deduplication_scoring_crm_handoff_and_sales_acceptance(db):
    campaign = _campaign(db, "FLOW")
    _published_campaign_asset(db, campaign.campaign_id, "FLOW")
    activate_campaign(db, campaign.campaign_id, _user("marketing"))
    lead = _capture(db, campaign.campaign_id)
    assert lead.status == "scored"
    assert lead.score == 95
    duplicate = _capture(db, campaign.campaign_id, email="LEAD.UAT@example.test")
    assert duplicate.lead_id == lead.lead_id
    assert duplicate.signal_count == 2

    qualify_lead(
        db,
        lead.lead_id,
        _user("marketing"),
        note="A lead pontszáma és projektigénye megfelel az MQL-feltételeknek.",
        override_reason="",
    )
    handed_off = handoff_lead_to_crm(
        db,
        lead.lead_id,
        _user("marketing"),
        assigned_sales_email="sales@imperial.local",
    )
    assert handed_off.status == "crm_handoff"
    accepted = decide_sales_lead(
        db,
        lead.lead_id,
        _user("sales"),
        decision="accept",
        note="A kapcsolatfelvételt és az első konzultációt értékesítés vállalja.",
    )
    assert accepted.status == "sales_accepted"
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.external_key == lead.lead_id,
            EnterpriseCanonicalRecord.entity_type == "lead",
        )
    )
    assert canonical and canonical.target_module == "crm"
    assert json.loads(canonical.data_json)["stage"] == "sales_accepted"
    crm_record = db.scalar(
        select(ModuleBusinessRecord).where(ModuleBusinessRecord.record_id == accepted.crm_record_id)
    )
    assert crm_record and crm_record.status == "active"
    tasks = db.scalars(select(TaskRecord).where(TaskRecord.source_event_id == lead.lead_id)).all()
    assert len(tasks) == 1 and tasks[0].status == "done"
    assert db.scalar(
        select(ProjectRegistry).where(ProjectRegistry.project_id == "COMMERCIAL-PIPELINE")
    )
    activity_types = {
        row.activity_type
        for row in db.scalars(
            select(MarketingLeadActivity).where(MarketingLeadActivity.lead_id == lead.lead_id)
        )
    }
    assert {
        "captured_and_scored",
        "duplicate_signal_merged",
        "marketing_qualified",
        "crm_handoff",
        "sales_accept",
    } <= activity_types


def test_marketing_consent_withdrawal_is_fail_closed_and_synced(db):
    campaign = _campaign(db, "CONSENT")
    _published_campaign_asset(db, campaign.campaign_id, "CONSENT")
    activate_campaign(db, campaign.campaign_id, _user("marketing"))
    lead = _capture(
        db,
        campaign.campaign_id,
        email="consent.uat@example.test",
        utm_campaign=campaign.utm_campaign,
    )
    qualify_lead(
        db,
        lead.lead_id,
        _user("marketing"),
        note="A hozzájárulási UAT lead megfelel az MQL-feltételeknek.",
        override_reason="",
    )
    handoff_lead_to_crm(
        db,
        lead.lead_id,
        _user("marketing"),
        assigned_sales_email="sales@imperial.local",
    )

    withdrawn = set_marketing_consent(
        db,
        lead.lead_id,
        _user("marketing"),
        consent=False,
        source="customer_email",
        evidence="Az ügyfél visszavonási kérése archiválva van.",
    )
    assert withdrawn.marketing_consent is False
    assert withdrawn.marketing_consent_withdrawn_at is not None
    suppression = db.scalar(
        select(MailSuppression).where(
            MailSuppression.email == "consent.uat@example.test"
        )
    )
    assert suppression and suppression.active
    assert suppression.reason == "marketing_consent_withdrawn"
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.external_key == lead.lead_id,
            EnterpriseCanonicalRecord.entity_type == "lead",
        )
    )
    crm_record = db.scalar(
        select(ModuleBusinessRecord).where(
            ModuleBusinessRecord.record_id == withdrawn.crm_record_id
        )
    )
    assert canonical and json.loads(canonical.data_json)["marketingConsent"] is False
    assert crm_record and json.loads(crm_record.data_json)["marketingConsent"] is False

    duplicate = _capture(
        db,
        campaign.campaign_id,
        email="CONSENT.UAT@example.test",
        utm_campaign=campaign.utm_campaign,
    )
    assert duplicate.marketing_consent is False
    assert duplicate.marketing_consent_withdrawn_at is not None

    granted = set_marketing_consent(
        db,
        lead.lead_id,
        _user("marketing"),
        consent=True,
        source="signed_form",
        evidence="Új, aláírt hozzájárulási nyilatkozat archiválva.",
    )
    assert granted.marketing_consent is True
    assert granted.marketing_consent_withdrawn_at is None
    db.refresh(suppression)
    assert suppression.active is False

    self_service = withdraw_marketing_consent_by_token(
        db, granted.consent_management_token
    )
    assert self_service.marketing_consent is False
    with pytest.raises(PermissionError):
        set_marketing_consent(
            db,
            lead.lead_id,
            _user("project-manager"),
            consent=True,
            source="manual",
            evidence="Jogosulatlan hozzájárulási kísérlet.",
        )

    db.add(
        MailSuppression(
            email="complaint.uat@example.test",
            reason="complaint",
            source="mail_provider",
            active=True,
        )
    )
    db.commit()
    suppressed_lead = _capture(
        db,
        campaign.campaign_id,
        email="complaint.uat@example.test",
        utm_campaign=campaign.utm_campaign,
    )
    assert suppressed_lead.marketing_consent is False
    with pytest.raises(ValueError, match="más okból aktív tiltólistán"):
        set_marketing_consent(
            db,
            suppressed_lead.lead_id,
            _user("marketing"),
            consent=True,
            source="signed_form",
            evidence="Új hozzájárulási jel érkezett, de a panasz aktív.",
        )
    complaint = db.scalar(
        select(MailSuppression).where(
            MailSuppression.email == "complaint.uat@example.test"
        )
    )
    assert complaint and complaint.reason == "complaint" and complaint.active


def test_marketing_consent_public_self_service(client, db):
    campaign = _campaign(db, "CONSENT-PUBLIC")
    _published_campaign_asset(db, campaign.campaign_id, "CONSENT-PUBLIC")
    activate_campaign(db, campaign.campaign_id, _user("marketing"))
    lead = _capture(
        db,
        campaign.campaign_id,
        email="public.consent@example.test",
        utm_campaign=campaign.utm_campaign,
    )

    page = client.get(f"/marketing/consent/{lead.consent_management_token}")
    assert page.status_code == 200
    assert "Hozzájárulás visszavonása" in page.text
    result = client.post(f"/marketing/consent/{lead.consent_management_token}")
    assert result.status_code == 200
    db.expire_all()
    stored = db.scalar(select(MarketingLead).where(MarketingLead.lead_id == lead.lead_id))
    assert stored and stored.marketing_consent is False
    assert "további marketingküldés nem engedélyezett" in result.text
    assert client.get("/marketing/consent/not-a-valid-token").status_code == 404


def test_privacy_gate_low_score_override_and_role_ui(client, db):
    with pytest.raises(ValueError, match="adatkezelési"):
        capture_lead(
            db,
            _user("marketing"),
            campaign_id="",
            source="manual",
            channel="phone",
            landing_page_url="",
            utm_source="",
            utm_medium="",
            utm_campaign="",
            utm_content="",
            full_name="Adatvédelmi Teszt",
            email="privacy@example.test",
            phone="",
            company="",
            lead_type="b2c",
            project_location="",
            estimated_budget_huf="0",
            timeframe_months=None,
            intent_summary="",
            privacy_notice_accepted=False,
            privacy_notice_version="",
            marketing_consent=False,
        )

    api_response = client.post(
        "/api/marketing/leads",
        json={
            "source": "landing_adapter_uat",
            "channel": "web",
            "fullName": "API Lead UAT",
            "email": "api-lead@example.test",
            "phone": "+36 30 999 9999",
            "projectLocation": "Érd",
            "estimatedBudgetHuf": "80000000",
            "timeframeMonths": 6,
            "intentSummary": ("Kontrollált API lead egy családi ház kivitelezési érdeklődésével."),
            "privacyNoticeAccepted": True,
            "privacyNoticeVersion": "privacy-2026-08",
            "marketingConsent": False,
        },
    )
    assert api_response.status_code == 200
    assert api_response.json()["score"] == 85
    assert api_response.json()["marketing_consent"] is False

    login = client.post(
        "/login",
        data={"email": "marketing@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/marketing/automation").status_code == 200
    client.post("/logout")
    client.post(
        "/login",
        data={"email": "sales@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    page = client.get("/marketing/automation")
    assert page.status_code == 200
    assert "Lead pipeline" in page.text
    client.post("/logout")
    client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert client.get("/marketing/automation").status_code == 403


def test_campaign_metrics_are_idempotent_and_scale_requires_human_approval(db):
    campaign = _campaign(db, "PERF")
    _published_campaign_asset(db, campaign.campaign_id, "PERF")
    activate_campaign(db, campaign.campaign_id, _user("marketing"))
    lead = _capture(
        db,
        campaign.campaign_id,
        email="performance@example.test",
        utm_campaign="imperial-uat-perf",
    )
    qualify_lead(
        db,
        lead.lead_id,
        _user("marketing"),
        note="A teljesítményteszt lead megfelel a minősítési követelményeknek.",
        override_reason="",
    )
    raw_payload = {"adapter": "meta_uat", "account": "act-uat"}
    metric = ingest_campaign_metric(
        db,
        _user("marketing"),
        campaign_id=campaign.campaign_id,
        asset_id="ASSET-MKT-PERF",
        metric_date=date(2026, 9, 10),
        channel="meta",
        source_system="meta_ads",
        external_key="meta-perf-2026-09-10",
        impressions=10000,
        clicks=200,
        landing_sessions=180,
        form_starts=20,
        form_completes=10,
        platform_conversions=8,
        spend_net="80000",
        currency="HUF",
        raw_payload=raw_payload,
    )
    same = ingest_campaign_metric(
        db,
        _user("marketing"),
        campaign_id=campaign.campaign_id,
        asset_id="ASSET-MKT-PERF",
        metric_date=date(2026, 9, 10),
        channel="meta",
        source_system="meta_ads",
        external_key="meta-perf-2026-09-10",
        impressions=10000,
        clicks=200,
        landing_sessions=180,
        form_starts=20,
        form_completes=10,
        platform_conversions=8,
        spend_net="80000",
        currency="HUF",
        raw_payload=raw_payload,
    )
    assert same.metric_id == metric.metric_id
    assert len(db.scalars(select(MarketingCampaignDailyMetric)).all()) == 1
    content_metrics = db.scalars(
        select(ContentPerformanceMetric).where(
            ContentPerformanceMetric.asset_id == "ASSET-MKT-PERF"
        )
    ).all()
    assert {row.metric_type for row in content_metrics} == {"ctr", "form_complete"}
    summary = campaign_performance(db, campaign.campaign_id)
    assert summary["ctr_percent"] == 2
    assert summary["actual_cpl_net"] == 80000
    decision = propose_optimization(
        db,
        campaign.campaign_id,
        _user("owner"),
        rationale="A minősített lead üzleti minősége megfelelő.",
    )
    assert decision.decision_type == "scale"
    assert decision.proposed_budget_net == 6000000
    with pytest.raises(ValueError, match="független"):
        decide_optimization(
            db,
            decision.decision_id,
            _user("owner"),
            decision="approve",
            note="A saját javaslat önjóváhagyítása tiltott lenne.",
        )
    decide_optimization(
        db,
        decision.decision_id,
        _user("managing-director"),
        decision="approve",
        note="A teljesítményadatok alapján a húsz százalékos skálázás jóváhagyható.",
    )
    executed = execute_optimization(db, decision.decision_id, _user("marketing"))
    assert executed.status == "executed"
    db.refresh(campaign)
    assert campaign.budget_net == 6000000


def test_optimization_pauses_campaign_after_two_target_cpl_without_lead(db):
    campaign = _campaign(db, "PAUSE")
    _published_campaign_asset(db, campaign.campaign_id, "PAUSE")
    activate_campaign(db, campaign.campaign_id, _user("marketing"))
    ingest_campaign_metric(
        db,
        _user("marketing"),
        campaign_id=campaign.campaign_id,
        asset_id="",
        metric_date=date(2026, 9, 11),
        channel="google",
        source_system="google_ads",
        external_key="google-pause-2026-09-11",
        impressions=5000,
        clicks=100,
        landing_sessions=90,
        form_starts=5,
        form_completes=0,
        platform_conversions=0,
        spend_net="250000",
        currency="HUF",
        raw_payload={"adapter": "google_uat"},
    )
    proposal = propose_optimization(
        db,
        campaign.campaign_id,
        _user("marketing"),
        rationale="A költést a cél-CPL kétszerese felett meg kell állítani.",
    )
    assert proposal.decision_type == "pause"
    decide_optimization(
        db,
        proposal.decision_id,
        _user("owner"),
        decision="approve",
        note="A nulla lead miatt a kampány szüneteltetése indokolt és jóváhagyott.",
    )
    execute_optimization(db, proposal.decision_id, _user("marketing"))
    db.refresh(campaign)
    assert campaign.status == "paused"


def test_campaign_metric_api_is_idempotent_and_rejects_currency_mismatch(client, db):
    campaign = _campaign(db, "API-PERF")
    _published_campaign_asset(db, campaign.campaign_id, "API-PERF")
    activate_campaign(db, campaign.campaign_id, _user("marketing"))
    payload = {
        "campaignId": campaign.campaign_id,
        "metricDate": "2026-09-12",
        "channel": "meta",
        "sourceSystem": "meta_ads_api_uat",
        "externalKey": "meta-api-perf-2026-09-12",
        "impressions": 1000,
        "clicks": 20,
        "landingSessions": 18,
        "formStarts": 4,
        "formCompletes": 2,
        "platformConversions": 1,
        "spendNet": "25000",
        "currency": "HUF",
    }
    first = client.post("/api/marketing/campaign-metrics", json=payload)
    second = client.post("/api/marketing/campaign-metrics", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["metric_id"] == first.json()["metric_id"]
    invalid = client.post("/api/marketing/campaign-metrics", json={**payload, "currency": "EUR"})
    assert invalid.status_code == 400
    assert "pénznemének egyeznie" in invalid.json()["detail"]
