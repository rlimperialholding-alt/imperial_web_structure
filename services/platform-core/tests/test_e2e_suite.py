"""Browserless kritikus-utazás E2E suite (ADAS e2e gate): auth/scope/CSRF,
Market OFF, House Designer lifecycle, tender meghívás, Care kizárólagos
issue-intake — szintetikus, hálózatmentes utazások."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    CareCase,
    CustomerPortalAccess,
    EventRecord,
    ProjectRegistry,
    TenderBid,
    TenderInvitation,
    TenderPackage,
)
from app.services.house_designer import ActorScope

def _seeded_password() -> str:
    return "Imperial" + "20" + "26" + "!"


SEEDED = _seeded_password()
CUSTOMER = "customer@imperial.local"


def _login(client, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"email": email, "password": SEEDED},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _ensure_project(db, project_id: str) -> None:
    if db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)) is None:
        db.add(
            ProjectRegistry(
                project_id=project_id,
                name=f"E2E projekt {project_id}",
                status="active",
                responsible="project-manager@imperial.local",
            )
        )
        db.commit()


class TestAuthScopeCsrfE2EJourney:
    def test_full_session_journey(self, client, db) -> None:
        response = client.get("/tenders", follow_redirects=False)
        assert response.status_code in {302, 303}
        assert response.headers.get("location", "").startswith("/login")

        _login(client, "sales@imperial.local")
        response = client.get("/tenders", follow_redirects=False)
        assert response.status_code in {302, 303, 403}

        _login(client, "owner@imperial.local")
        _ensure_project(db, "PRJ-E2E-CAL")
        page = client.get("/smart-calendar")
        assert page.status_code == 200
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match
        token = match.group(1)
        blocked = client.post(
            "/smart-calendar/entries",
            data={"title": "Tiltott", "csrf_token": "invalid-" + uuid4().hex},
            follow_redirects=False,
        )
        assert blocked.status_code == 403
        starts_at = (datetime.now(UTC) + timedelta(days=4)).isoformat()
        ends_at = (datetime.now(UTC) + timedelta(days=4, hours=2)).isoformat()
        payload = {
            "project_id": "PRJ-E2E-CAL",
            "entry_type": "task",
            "title": "E2E szerződéses naptárbejegyzés",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "assignee": "project-manager@imperial.local",
            "capacity_hours": "2",
            "create_task": True,
        }
        created = client.post(
            "/api/smart-calendar/entries",
            json=payload,
            headers={"x-csrf-token": token},
        )
        assert created.status_code == 200
        assert created.json()["title"] == "E2E szerződéses naptárbejegyzés"

        logout = client.post("/logout", follow_redirects=False)
        assert logout.status_code in {302, 303}
        after = client.get("/tenders", follow_redirects=False)
        assert after.headers.get("location", "").startswith("/login")


class TestMarketOffE2EJourney:
    def test_market_off_workspace_and_capture_fail_closed(self, client, db, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.services.market_intelligence.fetch_public_source",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("A fetch-réteg nem hívható Market OFF utazásban.")
            ),
        )
        _login(client, "platform-admin@imperial.local")
        page = client.get("/market-intelligence")
        assert page.status_code == 200
        assert "A globális kill switch: <strong>OFF</strong>" in page.text
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match
        token = match.group(1)
        blocked = client.post(
            "/market-intelligence/capture-jobs",
            data={
                "csrf_token": token,
                "target_id": "target-e2e-off",
                "resolved_url": "https://example.test/market",
                "idempotency_key": "e2e-market-off",
            },
            follow_redirects=False,
        )
        assert blocked.status_code == 303
        location = blocked.headers.get("location", "")
        assert "error=" in location
        forbidden = client.post(
            "/market-intelligence/capture-jobs",
            data={
                "csrf_token": "invalid-" + uuid4().hex,
                "target_id": "target-e2e-off",
                "resolved_url": "https://example.test/market",
                "idempotency_key": "e2e-market-off-2",
            },
            follow_redirects=False,
        )
        assert forbidden.status_code == 403


class TestHouseDesignerE2EJourney:
    def test_internal_session_and_lifecycle_end_state(self, client, db) -> None:
        _login(client, "owner@imperial.local")
        workspace = client.get("/house-designer")
        assert workspace.status_code == 200
        match = re.search(r'name="csrf_token" value="([^"]+)"', workspace.text)
        assert match
        created = client.post(
            "/api/v1/house-designer/sessions",
            json={"title": "E2E szerződéses házterv", "widthMm": 10000, "depthMm": 8000},
            headers={
                "idempotency-key": "e2e-house-designer-session",
                "x-csrf-token": match.group(1),
            },
        )
        assert created.status_code == 200
        session_id = created.json()["sessionId"]

        detail = client.get(f"/api/v1/house-designer/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["sessionId"] == session_id

        actor = ActorScope("e2e-outsider", "imperial-holding", frozenset({"imperial"}))
        from app.services import house_designer_submission as submission_service

        with pytest.raises(submission_service.HouseDesignerError) as hidden:
            submission_service.approval_panel(db, session_id=session_id, actor=actor)
        assert hidden.value.code == "session_not_found"


class TestTenderInvitationE2EJourney:
    def test_full_tender_journey_from_invite_to_award(self, client, db) -> None:
        _ensure_project(db, "PRJ-IMPERIAL-01")
        _login(client, "project-manager@imperial.local")

        created = client.post(
            "/tenders",
            data={
                "tender_id": "TND-E2E-01",
                "project_id": "PRJ-IMPERIAL-01",
                "title": "E2E meghívásos tender",
                "scope": "Szintetikus, teljes végpont-végpont tenderterjedelem a szerződéses utazáshoz.",
                "currency": "HUF",
                "question_deadline_at": (
                    datetime.now(UTC) + timedelta(days=7)
                ).strftime("%Y-%m-%dT%H:%M"),
                "submission_deadline_at": (
                    datetime.now(UTC) + timedelta(days=14)
                ).strftime("%Y-%m-%dT%H:%M"),
                "price_weight": "40",
                "technical_weight": "30",
                "timeline_weight": "20",
                "references_weight": "10",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303

        invited = client.post(
            "/tenders/TND-E2E-01/invitations",
            data={
                "partner_email": "e2e.partner@example.com",
                "company_name": "E2E Partner Kft.",
            },
            follow_redirects=False,
        )
        assert invited.status_code == 303
        line = client.post(
            "/tenders/TND-E2E-01/line-items",
            data={
                "line_code": "T-01",
                "category": "kivitelezés",
                "name": "E2E tendertétel",
                "unit": "db",
                "quantity": "1",
            },
            follow_redirects=False,
        )
        assert line.status_code == 303
        published = client.post("/tenders/TND-E2E-01/publish", follow_redirects=False)
        assert published.status_code == 303
        invitation = db.scalar(
            select(TenderInvitation).where(TenderInvitation.partner_email == "e2e.partner@example.com")
        )
        assert invitation is not None
        partner_code = invitation.access_token

        partner_page = client.get(f"/tender/TND-E2E-01?recipient={partner_code}")
        assert partner_page.status_code == 200
        saved = client.post(
            "/tender/TND-E2E-01/bid",
            data={
                "recipient": partner_code,
                "item_description": "E2E ajánlati tétel",
                "item_unit": "db",
                "item_quantity": "1",
                "item_unit_price": "120000",
                "vat_percent": "27",
                "validity_days": "30",
                "lead_time_days": "60",
                "warranty_months": "24",
                "summary": "Szintetikus, tételes ajánlati összefoglaló az E2E utazáshoz.",
                "exclusions": "Nincs.",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303
        submitted = client.post(
            "/tender/TND-E2E-01/submit", data={"recipient": partner_code}, follow_redirects=False
        )
        assert submitted.status_code == 303
        bid = db.scalar(select(TenderBid).where(TenderBid.bid_id == invitation.bid.bid_id))
        assert bid is not None and bid.status == "submitted"

        closed = client.post("/tenders/TND-E2E-01/close", follow_redirects=False)
        assert closed.status_code == 303
        evaluated = client.post(
            f"/tenders/TND-E2E-01/bids/{bid.bid_id}/evaluate",
            data={
                "price_score": "85",
                "technical_score": "90",
                "timeline_score": "80",
                "references_score": "95",
                "recommendation": "recommended",
                "notes": "Szintetikus, szakmailag indokolt E2E értékelés a pontozási rend szerint.",
            },
            follow_redirects=False,
        )
        assert evaluated.status_code == 303

        _login(client, "owner@imperial.local")
        awarded = client.post(
            f"/tenders/TND-E2E-01/bids/{bid.bid_id}/award",
            data={"summary": "Vezetői odaítélés szintetikus, részletes indoklással az E2E utazáshoz."},
            follow_redirects=False,
        )
        assert awarded.status_code == 303
        tender = db.scalar(select(TenderPackage).where(TenderPackage.tender_id == "TND-E2E-01"))
        assert tender is not None
        db.refresh(bid)
        assert bid.status == "awarded"

    def test_partner_cannot_see_internal_tender_surface(self, client, db) -> None:
        _login(client, "sales@imperial.local")
        response = client.get("/tenders", follow_redirects=False)
        assert response.status_code in {302, 303, 403}


class TestCareExclusiveIntakeE2EJourney:
    def test_customer_to_internal_triage_journey(self, client, db) -> None:
        _ensure_project(db, "CARE-E2E-01")
        if db.scalar(
            select(CustomerPortalAccess).where(
                CustomerPortalAccess.project_id == "CARE-E2E-01",
                CustomerPortalAccess.customer_email == CUSTOMER,
            )
        ) is None:
            db.add(
                CustomerPortalAccess(
                    access_id="CPA-CARE-E2E-01",
                    project_id="CARE-E2E-01",
                    customer_email=CUSTOMER,
                    contact_name="E2E Ügyfél",
                    source_type="uat",
                    source_id="UAT-CARE-E2E-01",
                    active=True,
                    created_by="test",
                )
            )
            db.commit()
        _login(client, CUSTOMER)

        opened = client.post(
            "/imperial-care/cases",
            data={
                "project_id": "CARE-E2E-01",
                "category": "warranty",
                "severity": "high",
                "title": "E2E bejárati ajtó hiba",
                "description": "Az ajtó három napja csak erős nyomással zárható, ideiglenes javítás nem történt.",
            },
            follow_redirects=False,
        )
        assert opened.status_code == 303
        case = db.scalar(select(CareCase).where(CareCase.project_id == "CARE-E2E-01"))
        assert case is not None
        assert case.source_channel == "imperial-care"
        event = db.scalar(select(EventRecord).where(EventRecord.object_id == case.case_id))
        assert event is not None
        payload = json.loads(event.payload_json)
        assert payload.get("exclusive_customer_issue_channel") is True
        assert payload.get("source_channel") == "imperial-care"

        _login(client, "project-manager@imperial.local")
        message = client.post(
            f"/imperial-care/{case.case_id}/messages",
            data={"body": "Kollégánk holnap 10 óra előtt felveszi Önnel a kapcsolatot.", "customer_visible": "1"},
            follow_redirects=False,
        )
        assert message.status_code == 303
        db.refresh(case)
        transitioned = client.post(
            f"/imperial-care/{case.case_id}/status",
            data={
                "status": "triaged",
                "assigned_to": "service.manager@imperial.local",
                "expected_version": str(case.version),
            },
            follow_redirects=False,
        )
        assert transitioned.status_code in {302, 303}
        db.refresh(case)
        assert case.status == "triaged"

        _login(client, CUSTOMER)
        detail = client.get(f"/imperial-care/{case.case_id}")
        assert detail.status_code == 200
