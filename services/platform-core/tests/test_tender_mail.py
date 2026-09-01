from __future__ import annotations

from sqlalchemy import select

from app.models import MailSuppression, TenderMailCampaign, TenderMailRecipient


def verify_seeded_domain(client, provider="provider_not_configured"):
    # Update provider separately while preserving the default sender identity.
    domain = client.post("/api/tendermail/domains", json={
        "domain_key": "imperial_tender",
        "domain_name": "tender.imperialholding.hu",
        "from_email": "meghivas@tender.imperialholding.hu",
        "from_name": "Imperial Holding Tender",
        "provider": provider,
        "max_hourly_rate": 100,
    })
    assert domain.status_code == 200
    verification = client.post("/api/tendermail/domains/imperial_tender/verification", json={
        "spf_status": "pass", "dkim_status": "pass", "dmarc_status": "pass",
        "tracking_domain_status": "pass", "warmup_status": "active",
        "evidence": {"verified_by": "test"},
    })
    assert verification.status_code == 200


def create_campaign(client):
    response = client.post("/api/tendermail/campaigns", json={
        "name": "Teszt szerkezetépítési tender",
        "domain_key": "imperial_tender",
        "subject_template": "Tendermeghívás – {{company_name}} – {{tender_id}}",
        "text_template": "Tisztelt {{contact_name}}!\nTender: {{tender_link}}\nÉrtesítések: {{unsubscribe_url}}",
        "tender_id": "TND-TEST-001",
        "project_id": "IMP-TEST-001",
        "hourly_rate": 50,
    })
    assert response.status_code == 200
    return response.json()["campaign_id"]


def test_tendermail_requires_domain_auth_and_supports_safe_simulation(client, db):
    campaign_id = create_campaign(client)
    recipients = client.post(f"/api/tendermail/campaigns/{campaign_id}/recipients", json={
        "recipients": [{"email": "partner@example.hu", "company_name": "Partner Kft.", "contact_name": "Kovács Péter"}],
        "include_canonical_partner_records": False,
    })
    assert recipients.status_code == 200

    before = client.get(f"/api/tendermail/campaigns/{campaign_id}/readiness").json()
    assert before["ready_for_approval"] is False
    assert before["checks"]["spf"] is False

    verify_seeded_domain(client)
    readiness = client.get(f"/api/tendermail/campaigns/{campaign_id}/readiness").json()
    assert readiness["ready_for_approval"] is True
    assert readiness["ready_for_live_send"] is False  # no live provider adapter

    approved = client.post(f"/api/tendermail/campaigns/{campaign_id}/approve?actor=owner")
    assert approved.status_code == 200
    queued = client.post(f"/api/tendermail/campaigns/{campaign_id}/queue?simulate=true")
    assert queued.status_code == 200
    sent = client.post(f"/api/tendermail/campaigns/{campaign_id}/dispatch?simulate=true&limit=10")
    assert sent.status_code == 200
    assert sent.json()["sent"] == 1
    assert "partner@example.hu" == sent.json()["messages"][0]["email"]
    assert "TND-TEST-001" in sent.json()["messages"][0]["subject"]
    assert "/mail/preferences/" in sent.json()["messages"][0]["text"]

    db.expire_all()
    campaign = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id))
    recipient = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign_id))
    assert campaign.status == "completed"
    assert recipient.status == "sent"


def test_complaint_suppresses_email_for_future_campaigns(client, db):
    verify_seeded_domain(client)
    campaign_id = create_campaign(client)
    client.post(f"/api/tendermail/campaigns/{campaign_id}/recipients", json={
        "recipients": [{"email": "complaint@example.hu", "company_name": "Panasz Kft."}],
        "include_canonical_partner_records": False,
    })
    recipient = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign_id))
    event = client.post("/api/tendermail/events", json={
        "recipient_id": recipient.recipient_id, "event_type": "complaint", "provider_event_id": "evt-complaint-1",
    })
    assert event.status_code == 200
    db.expire_all()
    assert db.scalar(select(MailSuppression).where(MailSuppression.email == "complaint@example.hu")) is not None

    campaign2 = create_campaign(client)
    added = client.post(f"/api/tendermail/campaigns/{campaign2}/recipients", json={
        "recipients": [{"email": "complaint@example.hu", "company_name": "Panasz Kft."}],
        "include_canonical_partner_records": False,
    })
    assert added.status_code == 200
    assert added.json()["suppressed"] == 1
    row = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign2))
    assert row.status == "suppressed"


def test_one_click_preference_endpoint(client, db):
    campaign_id = create_campaign(client)
    client.post(f"/api/tendermail/campaigns/{campaign_id}/recipients", json={
        "recipients": [{"email": "optout@example.hu", "company_name": "Optout Kft."}],
        "include_canonical_partner_records": False,
    })
    row = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign_id))
    page = client.get(f"/mail/preferences/{row.tracking_token}")
    assert page.status_code == 200
    response = client.post(f"/mail/preferences/{row.tracking_token}")
    assert response.status_code == 200
    db.expire_all()
    row = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.recipient_id == row.recipient_id))
    assert row.status == "unsubscribed"
