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
        "subject_template": "Ajánlatkérés – {{tender_id}}",
        "text_template": (
            "Tisztelt {{contact_name}}!\n\n"
            "Szeretnénk ajánlatot kérni a {{tender_id}} munkára. "
            "Ez új megbízási lehetőség Önöknek.\n\n"
            "Kérjük, nyissák meg a munka leírását: {{tender_link}}\n\n"
            "Üdvözlettel:\nImperial Holding\n\n"
            "Leiratkozás: {{unsubscribe_url}}"
        ),
        "tender_id": "TND-TEST-001",
        "project_id": "IMP-TEST-001",
        "hourly_rate": 50,
    })
    assert response.status_code == 200
    return response.json()["campaign_id"]


def test_tendermail_default_form_copy_passes_the_outbound_gate(logged_in_client):
    page = logged_in_client.get("/tendermail")
    assert page.status_code == 200
    assert "Ajánlatkérés – {{tender_id}}" in page.text
    assert "Ez új megbízási lehetőség Önöknek." in page.text

    response = logged_in_client.post(
        "/tendermail/campaigns",
        data={
            "name": "Alapértelmezett tenderlevél",
            "domain_key": "imperial_tender",
            "subject_template": "Ajánlatkérés – {{tender_id}}",
            "text_template": (
                "Tisztelt {{contact_name}}!\n\n"
                "Szeretnénk ajánlatot kérni a {{tender_id}} munkára. "
                "Ez új megbízási lehetőség Önöknek.\n\n"
                "Kérjük, nyissák meg a munka leírását: {{tender_link}}\n\n"
                "Üdvözlettel:\nImperial Holding\n\n"
                "Leiratkozás: {{unsubscribe_url}}"
            ),
            "tender_id": "TND-DEFAULT-001",
            "project_id": "IMP-DEFAULT-001",
            "hourly_rate": "100",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303


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


def test_tendermail_blocks_jargon_and_foreign_brand_at_campaign_creation(client):
    response = client.post(
        "/api/tendermail/campaigns",
        json={
            "name": "Hibás megkeresés",
            "domain_key": "imperial_tender",
            "subject_template": "Partnerkapcsolat",
            "text_template": (
                "Strukturált szakmai együttműködést keresünk. "
                "Bemutatjuk a projektjel-feldolgozási rendszert. "
                "Kérjük, válaszoljanak. Imperial Holding / BauShield "
                "{{tender_link}} {{unsubscribe_url}}"
            ),
        },
    )

    assert response.status_code == 400
    assert "Kimenő levél blokkolva" in response.json()["detail"]


def test_tendermail_blocks_one_bad_recipient_without_starving_valid_recipient(client, db):
    campaign_id = create_campaign(client)
    recipients = client.post(
        f"/api/tendermail/campaigns/{campaign_id}/recipients",
        json={
            "recipients": [
                {
                    "email": "blocked@example.hu",
                    "company_name": "Első Kft.",
                    "contact_name": "BauShielddel dolgozó partner",
                },
                {
                    "email": "valid@example.hu",
                    "company_name": "Második Kft.",
                    "contact_name": "Kovács Péter",
                },
            ],
            "include_canonical_partner_records": False,
        },
    )
    assert recipients.status_code == 200

    verify_seeded_domain(client)
    assert client.post(f"/api/tendermail/campaigns/{campaign_id}/approve?actor=owner").status_code == 200
    assert client.post(f"/api/tendermail/campaigns/{campaign_id}/queue?simulate=true").status_code == 200
    response = client.post(
        f"/api/tendermail/campaigns/{campaign_id}/dispatch?simulate=true&limit=10"
    )
    assert response.status_code == 200
    assert response.json()["sent"] == 1
    assert response.json()["blocked"] == 1
    assert response.json()["messages"][0]["email"] == "valid@example.hu"

    rows = db.scalars(
        select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign_id)
    ).all()
    statuses = {row.email: row.status for row in rows}
    assert statuses == {"blocked@example.hu": "blocked", "valid@example.hu": "sent"}


def test_tendermail_add_recipient_enforces_owner_and_public_authority_gates(client, db):
    campaign_id = create_campaign(client)
    response = client.post(
        f"/api/tendermail/campaigns/{campaign_id}/recipients",
        json={
            "recipients": [
                {
                    "email": "turczer.jozsef@gmail.com",
                    "company_name": "Minta Kft.",
                    "contact_name": "Turczer József",
                },
                {
                    "email": "iroda@pest.gdn-ingatlan.hu",
                    "company_name": "GDN Ingatlanhálózat",
                },
                {
                    "email": "mompark@oc.hu",
                    "company_name": "Otthon Centrum Budapest XII. kerület",
                },
                {
                    "email": "beszerzes@minta-varos.hu",
                    "company_name": "Minta Város Önkormányzata",
                    "organization_class": "municipality",
                    "contracting_authority_verified": True,
                },
                {
                    "email": "ismeretlen@oc.hu",
                    "company_name": "Otthon Centrum",
                },
            ],
            "include_canonical_partner_records": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"added": 0, "suppressed": 5, "skipped": 0}
    rows = db.scalars(
        select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign_id)
    ).all()
    reasons = {row.email: row.suppression_reason for row in rows}
    assert reasons["ismeretlen@oc.hu"] == "SUPPRESSION_REVIEW"
    assert reasons["beszerzes@minta-varos.hu"].startswith(
        "HARD_SUPPRESSED_PUBLIC_PROCUREMENT_AUTHORITY"
    )
    assert all(row.status == "suppressed" for row in rows)


def test_tendermail_final_dispatch_rechecks_legacy_rows_without_starving_valid(client, db):
    campaign_id = create_campaign(client)
    response = client.post(
        f"/api/tendermail/campaigns/{campaign_id}/recipients",
        json={
            "recipients": [
                {
                    "email": "legacy@example.hu",
                    "company_name": "Régi címzett Kft.",
                },
                {
                    "email": "valid@example.hu",
                    "company_name": "Magán Fővállalkozó Kft.",
                    "organization_class": "private_contractor",
                    "personalization": {
                        "project_type": "public_procurement",
                        "evidence_url": "https://kozbeszerzes.varos.gov.hu/tender/123",
                    },
                },
            ],
            "include_canonical_partner_records": False,
        },
    )
    assert response.status_code == 200
    verify_seeded_domain(client)
    assert client.post(
        f"/api/tendermail/campaigns/{campaign_id}/approve?actor=owner"
    ).status_code == 200
    assert client.post(
        f"/api/tendermail/campaigns/{campaign_id}/queue?simulate=true"
    ).status_code == 200

    legacy = db.scalar(
        select(TenderMailRecipient).where(
            TenderMailRecipient.campaign_id == campaign_id,
            TenderMailRecipient.email == "legacy@example.hu",
        )
    )
    legacy.company_name = "Minta Város Önkormányzata"
    db.commit()

    dispatched = client.post(
        f"/api/tendermail/campaigns/{campaign_id}/dispatch?simulate=true&limit=10"
    )
    assert dispatched.status_code == 200
    assert dispatched.json()["sent"] == 1
    assert dispatched.json()["blocked"] == 1
    assert dispatched.json()["messages"][0]["email"] == "valid@example.hu"
    db.refresh(legacy)
    assert legacy.status == "blocked"
    assert legacy.suppression_reason.startswith(
        "HARD_SUPPRESSED_PUBLIC_PROCUREMENT_AUTHORITY"
    )


def test_tendermail_existing_recipient_reclassification_is_persisted_and_suppressed(
    client, db
):
    campaign_id = create_campaign(client)
    endpoint = f"/api/tendermail/campaigns/{campaign_id}/recipients"
    first = client.post(
        endpoint,
        json={
            "recipients": [
                {
                    "email": "partner@example.hu",
                    "company_name": "Korábbi Magáncég Kft.",
                }
            ],
            "include_canonical_partner_records": False,
        },
    )
    assert first.status_code == 200

    corrected = client.post(
        endpoint,
        json={
            "recipients": [
                {
                    "email": "partner@example.hu",
                    "company_name": "GDN Ingatlanhálózat",
                    "contact_name": "GDN partneriroda",
                }
            ],
            "include_canonical_partner_records": False,
        },
    )

    assert corrected.status_code == 200
    row = db.scalar(
        select(TenderMailRecipient).where(
            TenderMailRecipient.campaign_id == campaign_id,
            TenderMailRecipient.email == "partner@example.hu",
        )
    )
    assert row is not None
    assert row.company_name == "GDN Ingatlanhálózat"
    assert row.status == "suppressed"
    assert row.suppression_reason.startswith("HARD_SUPPRESSED_OWNER_DIRECTIVE")


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
