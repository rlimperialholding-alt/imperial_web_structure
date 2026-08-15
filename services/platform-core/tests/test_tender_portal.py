from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import (
    AuditLog,
    EventRecord,
    ProjectRegistry,
    TaskRecord,
    TenderBid,
    TenderBidVersion,
    TenderBidEvidence,
    TenderInvitation,
    TenderClarificationRequest,
    TenderPackage,
    TenderPurchaseOrderPreparation,
)
from app.services.tender_portal import _package_query, bid_comparison

PASSWORD = "Imperial2026!"
TENDER_ID = "TND-UAT-2026-001"
PROJECT_ID = "TENDER-UAT-001"


def _login(client, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login", data={"email": email, "password": PASSWORD}, follow_redirects=False
    )
    assert response.status_code == 303


def _create_project(db) -> None:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == PROJECT_ID)):
        db.add(
            ProjectRegistry(
                project_id=PROJECT_ID,
                name="Tender UAT építési projekt",
                status="active",
                responsible="project-manager@imperial.local",
            )
        )
        db.commit()


def _create_tender(client, db) -> TenderPackage:
    _create_project(db)
    _login(client, "project-manager@imperial.local")
    now = datetime.now(UTC)
    response = client.post(
        "/tenders",
        data={
            "tender_id": TENDER_ID,
            "project_id": PROJECT_ID,
            "title": "UAT szerkezetépítési ajánlatkérés",
            "scope": (
                "Teljes szerkezetépítési munkatartalom anyaggal, "
                "dokumentált átadással és ütemezéssel."
            ),
            "currency": "HUF",
            "question_deadline_at": (now + timedelta(days=2)).isoformat(),
            "submission_deadline_at": (now + timedelta(days=5)).isoformat(),
            "price_weight": "40",
            "technical_weight": "30",
            "timeline_weight": "20",
            "references_weight": "10",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    row = db.scalar(select(TenderPackage).where(TenderPackage.tender_id == TENDER_ID))
    assert row is not None
    for payload in (
        {"line_code": "STR-001", "category": "Szerkezet", "name": "Vasbeton szerkezet", "unit": "m3", "quantity": "10", "required": "on"},
        {"line_code": "STR-002", "category": "Szerkezet", "name": "Falazási munkák", "unit": "m2", "quantity": "100", "required": "on"},
    ):
        response = client.post(f"/tenders/{TENDER_ID}/line-items", data=payload, follow_redirects=False)
        assert response.status_code == 303
    return row


def _invite_and_publish(client, db, email: str = "partner.one@example.com") -> TenderInvitation:
    _create_tender(client, db)
    response = client.post(
        f"/tenders/{TENDER_ID}/invitations",
        data={
            "company_name": "UAT Szerkezet Kft.",
            "contact_name": "Partner Péter",
            "partner_email": email,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    invitation = db.scalar(select(TenderInvitation).where(TenderInvitation.partner_email == email))
    assert invitation is not None and len(invitation.access_token) >= 48
    _login(client, "platform-admin@imperial.local")
    assert client.post(
        f"/partners/{invitation.partner_id}/external-score",
        data={"score": "84", "evidence_ref": "drive://partnercheck/uat"},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        f"/partners/{invitation.partner_id}/approve",
        data={"note": "UAT partner dokumentált előminősítése rendben."},
        follow_redirects=False,
    ).status_code == 303
    _login(client, "project-manager@imperial.local")
    assert client.post(f"/tenders/{TENDER_ID}/publish", follow_redirects=False).status_code == 303
    return invitation


def _save_bid(
    client,
    invitation: TenderInvitation,
    *,
    summary: str = "Teljes körű kivitelezési ajánlat ütemtervvel.",
):
    return client.post(
        f"/tender/{TENDER_ID}/bid",
        data={
            "recipient": invitation.access_token,
            "item_description": ["Vasbeton szerkezet", "Falazási munkák"],
            "item_unit": ["m3", "m2"],
            "item_quantity": ["10", "100"],
            "item_unit_price": ["50000", "12000"],
            "vat_percent": "27",
            "validity_days": "30",
            "lead_time_days": "45",
            "warranty_months": "36",
            "summary": summary,
            "exclusions": "Daruzás külön megrendelés szerint.",
        },
        follow_redirects=False,
    )


def test_project_manager_creates_publishes_and_gets_event_task(client, db):
    tender = _create_tender(client, db)
    blocked = client.post(f"/tenders/{TENDER_ID}/publish")
    assert blocked.status_code == 400
    invitation = client.post(
        f"/tenders/{TENDER_ID}/invitations",
        data={
            "company_name": "UAT Partner Kft.",
            "contact_name": "Teszt Elek",
            "partner_email": "uat@example.com",
        },
        follow_redirects=False,
    )
    assert invitation.status_code == 303
    assert client.post(f"/tenders/{TENDER_ID}/publish", follow_redirects=False).status_code == 303
    db.refresh(tender)
    assert tender.status == "published" and tender.published_at is not None
    event = db.scalar(select(EventRecord).where(EventRecord.object_id == TENDER_ID))
    assert event is not None and event.event_type == "TENDER_PUBLISHED"
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
    assert task is not None


def test_partner_saves_itemized_bid_submits_and_cannot_edit_until_withdrawn(client, db):
    invitation = _invite_and_publish(client, db)
    page = client.get(f"/tender/{TENDER_ID}?recipient={invitation.access_token}")
    assert page.status_code == 200
    assert "UAT Szerkezet Kft." in page.text
    assert _save_bid(client, invitation).status_code == 303
    bid = db.scalar(select(TenderBid))
    assert bid is not None
    assert len(bid.items) == 2
    assert bid.net_total == Decimal("1700000.00")
    assert bid.vat_total == Decimal("459000.00")
    assert bid.gross_total == Decimal("2159000.00")
    version = db.scalar(select(TenderBidVersion).where(TenderBidVersion.bid_id_fk == bid.id))
    assert version is not None and version.normalization_status == "clean"
    assert len(version.content_sha256) == 64
    submit = client.post(
        f"/tender/{TENDER_ID}/submit",
        data={"recipient": invitation.access_token},
        follow_redirects=False,
    )
    assert submit.status_code == 303
    db.refresh(bid)
    assert bid.status == "submitted" and bid.submitted_at is not None
    assert _save_bid(client, invitation).status_code == 400
    assert (
        client.post(
            f"/tender/{TENDER_ID}/withdraw",
            data={"recipient": invitation.access_token},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        _save_bid(client, invitation, summary="Módosított, teljes körű UAT ajánlat.").status_code
        == 303
    )
    db.refresh(bid)
    assert bid.version == 2 and bid.status == "draft"


def test_tender_state_transition_query_uses_postgresql_row_lock():
    unlocked = str(_package_query().compile(dialect=postgresql.dialect()))
    locked = str(_package_query(for_update=True).compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" not in unlocked
    assert "FOR UPDATE" in locked


def test_partner_clarification_private_internal_note_and_token_isolation(client, db):
    first = _invite_and_publish(client, db)
    _login(client, "project-manager@imperial.local")
    assert (
        client.post(
            f"/tenders/{TENDER_ID}/invitations",
            data={
                "company_name": "Másik Partner Kft.",
                "contact_name": "Másik Márk",
                "partner_email": "second@example.com",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    second = db.scalar(
        select(TenderInvitation).where(TenderInvitation.partner_email == "second@example.com")
    )

    client.cookies.clear()
    question = client.post(
        f"/tender/{TENDER_ID}/clarifications",
        data={
            "recipient": first.access_token,
            "body": "A daruzás munkaterületi koordinációját ki biztosítja?",
        },
        follow_redirects=False,
    )
    assert question.status_code == 303
    _login(client, "project-manager@imperial.local")
    private = client.post(
        f"/tenders/{TENDER_ID}/clarifications",
        data={
            "invitation_id": first.invitation_id,
            "body": "Belső értékelés: a partner kapacitását ellenőrizni kell.",
        },
        follow_redirects=False,
    )
    assert private.status_code == 303
    visible = client.post(
        f"/tenders/{TENDER_ID}/clarifications",
        data={
            "invitation_id": first.invitation_id,
            "body": "A daruzást az ajánlattevő koordinálja.",
            "partner_visible": "on",
        },
        follow_redirects=False,
    )
    assert visible.status_code == 303
    client.cookies.clear()
    first_page = client.get(f"/tender/{TENDER_ID}?recipient={first.access_token}")
    assert "A daruzást az ajánlattevő" in first_page.text
    assert "Belső értékelés" not in first_page.text
    second_page = client.get(f"/tender/{TENDER_ID}?recipient={second.access_token}")
    assert "A daruzást az ajánlattevő" not in second_page.text
    assert client.get(f"/tender/{TENDER_ID}?recipient=wrong-token").status_code == 403


def test_evidence_is_hashed_type_checked_and_partner_isolated(client, db):
    invitation = _invite_and_publish(client, db)
    assert _save_bid(client, invitation).status_code == 303
    pdf = b"%PDF-1.7\ncontrolled tender UAT\n%%EOF"
    upload = client.post(
        f"/tender/{TENDER_ID}/evidence",
        data={
            "recipient": invitation.access_token,
            "caption": "UAT műszaki ajánlat",
        },
        files={"file": ("ajanlat.pdf", BytesIO(pdf), "application/pdf")},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    evidence = db.scalar(select(TenderBidEvidence))
    assert evidence is not None and len(evidence.sha256) == 64
    assert evidence.scan_status == "clean"
    assert evidence.scan_engine == "deterministic-test-scanner"
    assert evidence.scan_engine_version == "1"
    assert evidence.scanned_at is not None
    download = client.get(
        f"/tender/{TENDER_ID}/evidence/{evidence.evidence_id}?recipient={invitation.access_token}"
    )
    assert download.status_code == 200 and download.content == pdf
    assert db.scalar(
        select(AuditLog).where(
            AuditLog.action == "tender.bid.evidence.downloaded",
            AuditLog.entity_id == evidence.evidence_id,
        )
    ) is not None

    _login(client, "sales@imperial.local")
    assert client.get(f"/tenders/evidence/{evidence.evidence_id}").status_code == 403
    _login(client, "project-manager@imperial.local")
    evidence.scan_status = "legacy_unverified"
    db.commit()
    assert client.get(f"/tenders/evidence/{evidence.evidence_id}").status_code == 409
    evidence.scan_status = "clean"
    db.commit()
    client.cookies.clear()
    invalid = client.post(
        f"/tender/{TENDER_ID}/evidence",
        data={
            "recipient": invitation.access_token,
        },
        files={"file": ("fake.pdf", BytesIO(b"not-pdf"), "application/pdf")},
    )
    assert invalid.status_code == 400

    infected = client.post(
        f"/tender/{TENDER_ID}/evidence",
        data={"recipient": invitation.access_token},
        files={
            "file": (
                "eicar.pdf",
                BytesIO(b"%PDF-1.7\nEICAR-STANDARD-ANTIVIRUS-TEST-FILE\n%%EOF"),
                "application/pdf",
            )
        },
    )
    assert infected.status_code == 400
    assert "teszt-scanner" in infected.text
    assert len(db.scalars(select(TenderBidEvidence)).all()) == 1
    assert db.scalar(
        select(AuditLog).where(
            AuditLog.action == "tender.bid.evidence.rejected",
            AuditLog.entity_id == evidence.bid.bid_id,
        )
    ) is not None

    evidence_path = Path(evidence.storage_path)
    with evidence_path.open("ab") as handle:
        handle.write(b"tamper")
    blocked = client.get(
        f"/tender/{TENDER_ID}/evidence/{evidence.evidence_id}?recipient={invitation.access_token}"
    )
    assert blocked.status_code == 409
    assert db.scalar(
        select(AuditLog).where(
            AuditLog.action == "tender.bid.evidence.download_blocked",
            AuditLog.entity_id == evidence.evidence_id,
        )
    ) is not None


def test_evidence_upload_fails_closed_when_scanner_is_disabled(client, db, monkeypatch):
    invitation = _invite_and_publish(client, db)
    assert _save_bid(client, invitation).status_code == 303
    monkeypatch.setenv("TENDER_AV_MODE", "disabled")
    response = client.post(
        f"/tender/{TENDER_ID}/evidence",
        data={"recipient": invitation.access_token},
        files={"file": ("offer.pdf", BytesIO(b"%PDF-1.7\nUAT\n%%EOF"), "application/pdf")},
    )
    assert response.status_code == 503
    assert db.scalar(select(TenderBidEvidence)) is None
    rejected = db.scalar(
        select(AuditLog).where(AuditLog.action == "tender.bid.evidence.rejected")
    )
    assert rejected is not None and '"scan_status": "unavailable"' in rejected.after_json


def test_partner_can_decline_no_bid_and_cannot_reenter_bid_flow(client, db):
    invitation = _invite_and_publish(client, db)
    response = client.post(
        f"/tender/{TENDER_ID}/decline",
        data={
            "recipient": invitation.access_token,
            "reason": "A szintetikus UAT kapacitásablak nem megfelelő.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.refresh(invitation)
    assert invitation.status == "declined" and invitation.declined_at is not None
    assert _save_bid(client, invitation).status_code == 400
    assert db.scalar(
        select(AuditLog).where(
            AuditLog.action == "tender.invitation.declined",
            AuditLog.entity_id == TENDER_ID,
        )
    ) is not None


def test_evaluation_and_leadership_award_close_related_task(client, db):
    invitation = _invite_and_publish(client, db)
    assert _save_bid(client, invitation).status_code == 303
    assert (
        client.post(
            f"/tender/{TENDER_ID}/submit",
            data={"recipient": invitation.access_token},
            follow_redirects=False,
        ).status_code
        == 303
    )
    _login(client, "project-manager@imperial.local")
    assert client.post(f"/tenders/{TENDER_ID}/close", follow_redirects=False).status_code == 303
    bid = db.scalar(select(TenderBid))
    evaluation = client.post(
        f"/tenders/{TENDER_ID}/bids/{bid.bid_id}/evaluate",
        data={
            "price_score": "85",
            "technical_score": "92",
            "timeline_score": "80",
            "references_score": "90",
            "recommendation": "recommended",
            "notes": "A műszaki tartalom teljes, az ár piaci és a kapacitás igazolt.",
        },
        follow_redirects=False,
    )
    assert evaluation.status_code == 303
    clarification = client.post(
        f"/tenders/{TENDER_ID}/bids/{bid.bid_id}/clarification-requests",
        data={
            "question": "Kérjük a vállalt létszám és mobilizáció dokumentált megerősítését.",
            "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
        follow_redirects=False,
    )
    assert clarification.status_code == 303
    request = db.scalar(select(TenderClarificationRequest).where(TenderClarificationRequest.bid_id_fk == bid.id))
    assert request is not None and request.status == "open"
    partner_page = client.get(f"/tender/{TENDER_ID}?recipient={invitation.access_token}")
    assert partner_page.status_code == 200
    assert "FORMÁLIS HIÁNYPÓTLÁS" in partner_page.text and "mobilizáció" in partner_page.text
    forbidden_award = client.post(
        f"/tenders/{TENDER_ID}/bids/{bid.bid_id}/award",
        data={"summary": "A legjobb összesített ajánlat kiválasztása."},
    )
    assert forbidden_award.status_code == 403
    _login(client, "platform-admin@imperial.local")
    blocked_award = client.post(
        f"/tenders/{TENDER_ID}/bids/{bid.bid_id}/award",
        data={"summary": "A dokumentált értékelés alapján feltételesen kiválasztott ajánlat."},
    )
    assert blocked_award.status_code == 400
    client.cookies.clear()
    response = client.post(
        f"/tender/{TENDER_ID}/clarification-requests/{request.request_id}/respond",
        data={"recipient": invitation.access_token, "response": "Tizenkét fős brigáddal öt munkanapon belül mobilizálunk."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    _login(client, "project-manager@imperial.local")
    assert client.post(
        f"/tenders/{TENDER_ID}/clarification-requests/{request.request_id}/accept",
        data={"note": "A létszám és mobilizáció elfogadva."},
        follow_redirects=False,
    ).status_code == 303
    _login(client, "platform-admin@imperial.local")
    award = client.post(
        f"/tenders/{TENDER_ID}/bids/{bid.bid_id}/award",
        data={
            "summary": "A dokumentált súlyozott értékelés alapján a legjobb összesített ajánlat."
        },
        follow_redirects=False,
    )
    assert award.status_code == 303
    tender = db.scalar(select(TenderPackage).where(TenderPackage.tender_id == TENDER_ID))
    db.refresh(bid)
    assert tender.status == "awarded" and tender.awarded_bid_id == bid.bid_id
    assert bid.status == "awarded"
    preparation = db.scalar(select(TenderPurchaseOrderPreparation).where(TenderPurchaseOrderPreparation.tender_id == TENDER_ID))
    assert preparation is not None and preparation.partner_id == invitation.partner_id
    assert preparation.status == "draft" and len(preparation.content_sha256) == 64
    governance = client.get(f"/tenders/{TENDER_ID}/governance")
    assert governance.status_code == 200
    assert preparation.preparation_id in governance.text and "SHA-256" in governance.text
    event = db.scalar(select(EventRecord).where(EventRecord.object_id == TENDER_ID))
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
    assert event.status == "resolved" and task.status == "done"


def test_sales_cannot_open_internal_tender_workspace(client, db):
    _create_project(db)
    _login(client, "sales@imperial.local")
    assert client.get("/tenders").status_code == 403
    _login(client, "subcontractor@imperial.local")
    assert client.get("/tenders").status_code == 403


def test_internal_bid_comparison_screen_is_operational(client, db):
    invitation = _invite_and_publish(client, db)
    assert _save_bid(client, invitation).status_code == 303
    submitted = client.post(
        f"/tender/{TENDER_ID}/submit",
        data={"recipient": invitation.access_token},
        follow_redirects=False,
    )
    assert submitted.status_code == 303

    comparison = bid_comparison(db, TENDER_ID)
    assert comparison["metrics"]["candidate_count"] == 1
    assert comparison["metrics"]["complete_count"] == 1
    assert comparison["metrics"]["lowest_net_total"] == Decimal("1700000.00")
    assert len(comparison["line_matrix"]) == 2
    assert comparison["candidates"][0]["rank"] == 1

    _login(client, "project-manager@imperial.local")
    page = client.get(f"/tenders/{TENDER_ID}/compare")
    assert page.status_code == 200
    for marker in (
        "Összesített döntés-előkészítés",
        "Tételes ajánlati mátrix",
        "UAT Szerkezet Kft.",
        "1 700 000",
    ):
        assert marker in page.text
    assert client.get("/tenders/TND-NOT-FOUND/compare").status_code == 404


def test_invitation_link_rotation_revocation_and_expiry_fail_closed(client, db):
    invitation = _invite_and_publish(client, db)
    original_token = invitation.access_token

    _login(client, "project-manager@imperial.local")
    rotated = client.post(
        f"/tenders/{TENDER_ID}/invitations/{invitation.invitation_id}/rotate",
        follow_redirects=False,
    )
    assert rotated.status_code == 303
    db.refresh(invitation)
    assert invitation.token_revision == 2
    assert invitation.access_token != original_token
    assert client.get(f"/tender/{TENDER_ID}?recipient={original_token}").status_code == 403
    assert client.get(f"/tender/{TENDER_ID}?recipient={invitation.access_token}").status_code == 200

    missing_reason = client.post(
        f"/tenders/{TENDER_ID}/invitations/{invitation.invitation_id}/revoke",
        data={"reason": ""},
    )
    assert missing_reason.status_code == 400
    revoked = client.post(
        f"/tenders/{TENDER_ID}/invitations/{invitation.invitation_id}/revoke",
        data={"reason": "A partner hozzáférési linkje illetéktelenhez kerülhetett."},
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    db.refresh(invitation)
    assert invitation.status == "revoked"
    assert invitation.revoked_by == "project-manager@imperial.local"
    assert client.get(f"/tender/{TENDER_ID}?recipient={invitation.access_token}").status_code == 403

    invitation.status = "invited"
    invitation.revoked_at = None
    invitation.revoked_by = None
    invitation.revoke_reason = None
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.get(f"/tender/{TENDER_ID}?recipient={invitation.access_token}").status_code == 403
    db.refresh(invitation)
    assert invitation.status == "expired"
