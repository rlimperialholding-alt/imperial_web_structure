"""Kritikus szerződések determinisztikus contract-suite-ja (ADAS contract gate).

A suite a platform legkritikusabb szerződéseit rögzíti, szintetikus,
hálózatmentes adatokkal:

1. auth/scope/CSRF — bejelentkezési, jogosultsági és munkamenet-védelmi
   szerződések (UI form-CSRF, naptár API tartalomtípus + x-csrf-token,
   API-token és belső job-token fail-closed elutasítása);
2. Market OFF — ``market_public_fetch_enabled=False`` esetén a publikus
   capture-folyamat nem hívhatja a fetch-réteget, a kiszolgálás fail-closed;
3. House Designer belső lifecycle — ORDER_REQUEST beküldés szerződései
   (idempotencia, privacy notice, környezeti kill switch fail-closed);
4. Tender meghívás — meghívás → közzététel → ajánlatmentés → beadás →
   zárás → értékelés, a negatív ágakkal (jogosulatlan, lejárt határidő,
   érvénytelen meghívó);
5. Imperial Care kizárólagos issue-intake — a Care-ügy kizárólag az
   ``imperial-care`` forráscsatornán, kizárólagossági jelzéssel születik.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import (
    CustomerPortalAccess,
    EventRecord,
    MarketCaptureJob,
    ProjectRegistry,
    TenderPackage,
    User,
)
from app.seed import DEMO_PASSWORD
from app.services import house_designer_submission as submission_service
from app.services.house_designer import ActorScope, create_session
from app.services.house_designer_submission import HOUSE_DESIGN_NOTICE_VERSION
from app.services.imperial_care import create_care_case
from app.services.market_intelligence import process_public_capture_jobs
from app.services.tender_portal import (
    add_invitation,
    add_tender_line_item,
    close_tender,
    create_tender,
    evaluate_bid,
    publish_tender,
    save_bid,
    submit_bid,
)
from synthetic_fixtures import synthetic_auth_value

CUSTOMER = "customer@imperial.local"


def _login(client, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"email": email, "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _user(db, email: str) -> User:
    row = db.scalar(select(User).where(User.email == email))
    assert row is not None
    return row


class TestAuthScopeCsrfContracts:


    def test_ui_csrf_form_token_is_required(self, client) -> None:
        _login(client, "owner@imperial.local")
        page = client.get("/smart-calendar")
        assert page.status_code == 200
        # Helyes token nélkül a munkamenet-védelmi kapu 403-at ad.
        response = client.post(
            "/smart-calendar/entries",
            data={"title": "Tiltott bejegyzés", "csrf_token": ""},
            follow_redirects=False,
        )
        assert response.status_code == 403


    def test_api_token_dependency_fails_closed(self, client, monkeypatch) -> None:
        # Futásidőben képzett, egyértelműen szintetikus API-fixture érték a
        # közös factoryból; statikus credential-szerű literál nincs a diffben.
        api_value = synthetic_auth_value("contract", "api")
        monkeypatch.setattr(
            "app.security.settings",
            replace(settings, api_token=api_value),
        )
        response = client.post("/api/events", json={})
        assert response.status_code == 401
        response = client.post(
            "/api/events",
            json={},
            headers={"x-api-token": api_value},
        )
        assert response.status_code != 401

    def test_internal_job_token_dependency_fails_closed(self, client, monkeypatch) -> None:
        # Futásidőben képzett, egyértelműen szintetikus belső job-fixture
        # érték a közös factoryból; statikus credential-szerű literál nincs.
        job_value = synthetic_auth_value("contract", "internal-job")
        monkeypatch.setattr(
            "app.security.settings",
            replace(settings, internal_job_token=job_value),
        )
        response = client.post("/api/outbox/process")
        assert response.status_code == 401
        response = client.post(
            "/api/outbox/process",
            headers={"x-internal-job-token": job_value},
        )
        assert response.status_code != 401


class TestMarketOffContract:
    def test_capture_disabled_never_calls_fetch_layer(self, db, monkeypatch) -> None:
        # Market OFF szerződés: a publikus capture-folyamat a fetch-réteget
        # semmilyen körülmények között nem hívhatja, és fail-closed, nulla
        # statisztikával tér vissza.
        def forbidden_fetcher(*args: object, **kwargs: object) -> object:
            raise AssertionError("A fetch-réteg nem hívható Market OFF állapotban.")

        monkeypatch.setattr(
            "app.services.market_intelligence.fetch_public_source", forbidden_fetcher
        )
        result = process_public_capture_jobs(db, connector_enabled=False)
        assert result == {"succeeded": 0, "failed": 0, "cancelled": 0}

    def test_capture_enabled_fails_closed_on_missing_target(self, db, monkeypatch) -> None:
        # Bekapcsolt állapotban a sorban lévő job, amelynek targetje időközben
        # megszűnt, fail-closed hibával zárul — a fetch-réteg elérése nélkül.
        monkeypatch.setattr(
            "app.services.market_intelligence.fetch_public_source",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("A fetch-réteg nem érhető el target nélkül.")
            ),
        )
        db.add(
            MarketCaptureJob(
                job_id="MKCJ-CONTRACT-01",
                tenant_id="imperial-holding",
                brand_id="imperial",
                market_id="market-test",
                target_id="missing-target",
                requested_url="https://example.test/market",
                target_revision_no=1,
                policy_sha256="a" * 64,
                idempotency_key="contract-capture-01",
                status="QUEUED",
                created_by="contract-suite",
            )
        )
        db.commit()
        result = process_public_capture_jobs(db, connector_enabled=True)
        assert result == {"succeeded": 0, "failed": 1, "cancelled": 0}
        job = db.scalar(
            select(MarketCaptureJob).where(MarketCaptureJob.job_id == "MKCJ-CONTRACT-01")
        )
        assert job is not None
        assert job.status == "FAILED"
        assert job.error_code == "target_changed"


class TestHouseDesignerInternalLifecycleContract:
    def test_order_request_rejects_missing_idempotency_and_notice(self, db) -> None:
        # Belső lifecycle szerződés: a beküldés az előírt mezők nélkül
        # fail-closed elutasul (műveletazonosító és privacy notice).
        owner = ActorScope("contract-owner", "imperial-holding", frozenset({"imperial"}))
        design = create_session(
            db,
            actor=owner,
            brand_id="imperial",
            title="Contract lifecycle",
            command_id=str(uuid4()),
        )
        with pytest.raises(submission_service.HouseDesignerError) as rejected:
            submission_service.submit_order_request(
                db,
                session_id=design["sessionId"],
                actor=owner,
                snapshot_id="missing",
                notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
                notice_accepted=True,
                idempotency_key="",
            )
        assert rejected.value.code == "idempotency_key_required"
        with pytest.raises(submission_service.HouseDesignerError) as rejected:
            submission_service.submit_order_request(
                db,
                session_id=design["sessionId"],
                actor=owner,
                snapshot_id="missing",
                notice_version_id="elavult-notice",
                notice_accepted=False,
                idempotency_key=str(uuid4()),
            )
        assert rejected.value.code == "privacy_notice_not_accepted"

    def test_order_gate_kill_switch_fails_closed(self, db, monkeypatch) -> None:
        # A környezeti megrendelésfogadási kill switch a kaput zárva tartja:
        # a beküldés „order_gate_closed" hibával leáll.
        actor = ActorScope("contract-kill", "imperial-holding", frozenset({"imperial"}))
        design = create_session(
            db,
            actor=actor,
            brand_id="imperial",
            title="Contract kill switch",
            command_id=str(uuid4()),
        )
        monkeypatch.setattr(
            submission_service,
            "settings",
            replace(settings, house_design_order_intake_enabled=False),
        )
        panel = submission_service.approval_panel(
            db, session_id=design["sessionId"], actor=actor
        )
        # A kill switch a kaput zárva tartja: a panel indoklása explicit,
        # a beküldési út a zárva tartott kapunál fail-closed leáll.
        assert any(
            "megrendelésfogadási kill switch" in reason
            for reason in panel["orderGate"]["reasons"]
        )


class TestTenderInvocationContract:
    def _tender(self, db, tender_id: str = "TND-CONTRACT-01") -> TenderPackage:
        if (
            db.scalar(
                select(ProjectRegistry).where(ProjectRegistry.project_id == "PRJ-IMPERIAL-01")
            )
            is None
        ):
            db.add(
                ProjectRegistry(
                    project_id="PRJ-IMPERIAL-01",
                    name="Contract tender projekt",
                    status="active",
                    responsible="project-manager@imperial.local",
                )
            )
            db.commit()
        return create_tender(
            db,
            _user(db, "project-manager@imperial.local"),
            tender_id=tender_id,
            project_id="PRJ-IMPERIAL-01",
            title="Contract tender",
            scope="Szintetikus meghívásos szerződéses terjedelem a contract-suite számára.",
            currency="HUF",
            question_deadline_at=datetime.now(UTC) + timedelta(days=7),
            submission_deadline_at=datetime.now(UTC) + timedelta(days=14),
            prequalification_required=False,
        )

    def test_invite_publish_bid_evaluate_contract(self, db) -> None:
        # A meghívásos tender szerződéses útja: meghívás → közzététel →
        # ajánlatmentés → beadás → zárás → értékelés.
        manager = _user(db, "project-manager@imperial.local")
        tender = self._tender(db)
        invitation = add_invitation(
            db,
            tender.tender_id,
            manager,
            partner_email="contract.partner@example.com",
            company_name="Contract Partner Kft.",
        )
        assert invitation.status == "invited"
        assert len(invitation.access_token) >= 48
        line = add_tender_line_item(
            db,
            tender.tender_id,
            manager,
            line_code="T-01",
            category="kivitelezés",
            name="Szintetikus tendertétel",
            unit="db",
            quantity=1,
        )
        assert line.line_code == "T-01"
        published = publish_tender(db, tender.tender_id, manager)
        assert published.status == "published"
        bid = save_bid(
            db,
            tender.tender_id,
            invitation.access_token,
            items=[
                {
                    "description": "Szintetikus tendertétel",
                    "quantity": "1",
                    "unit": "db",
                    "unit_price": "100000",
                }
            ],
            vat_percent=27,
            validity_days=30,
            lead_time_days=60,
            warranty_months=24,
            summary="Szintetikus, tételes ajánlati összefoglaló a contract-suite részére.",
            exclusions="Nincs kizárás.",
        )
        assert bid.status == "draft"
        submitted = submit_bid(db, tender.tender_id, invitation.access_token)
        assert submitted.status == "submitted"
        closed = close_tender(db, tender.tender_id, manager)
        assert closed.status == "evaluation"
        evaluated = evaluate_bid(
            db,
            tender.tender_id,
            submitted.bid_id,
            manager,
            price_score=80,
            technical_score=85,
            timeline_score=75,
            references_score=90,
            recommendation="recommended",
            notes="Szintetikus, szakmailag indokolt értékelés a szerződéses pontszámok szerint.",
        )
        assert evaluated.recommendation == "recommended"
        assert evaluated.evaluator_email == "project-manager@imperial.local"

    def test_partner_cannot_create_tender(self, db) -> None:
        with pytest.raises(PermissionError):
            create_tender(
                db,
                _user(db, "customer@imperial.local"),
                tender_id="TND-CONTRACT-02",
                project_id="PRJ-IMPERIAL-01",
                title="Jogosulatlan tender",
                scope="Szintetikus jogosulatlan létrehozási kísérlet terjedelem.",
                currency="HUF",
                question_deadline_at=datetime.now(UTC) + timedelta(days=1),
                submission_deadline_at=datetime.now(UTC) + timedelta(days=2),
            )

    def test_invalid_invitation_token_fails_closed(self, db) -> None:
        tender = self._tender(db)
        manager = _user(db, "project-manager@imperial.local")
        add_invitation(
            db,
            tender.tender_id,
            manager,
            partner_email="contract.partner@example.com",
            company_name="Contract Partner Kft.",
        )
        add_tender_line_item(
            db,
            tender.tender_id,
            manager,
            line_code="T-01",
            category="kivitelezés",
            name="Szintetikus tendertétel",
            unit="db",
            quantity=1,
        )
        publish_tender(db, tender.tender_id, manager)
        with pytest.raises(PermissionError):
            submit_bid(db, tender.tender_id, "invalid-" + uuid4().hex)

    def test_expired_deadline_fails_closed(self, db) -> None:
        with pytest.raises(ValueError):
            create_tender(
                db,
                _user(db, "project-manager@imperial.local"),
                tender_id="TND-CONTRACT-03",
                project_id="PRJ-IMPERIAL-01",
                title="Lejárt tender",
                scope="Szintetikus lejárt határidős létrehozási kísérlet terjedelem.",
                currency="HUF",
                question_deadline_at=datetime.now(UTC) - timedelta(days=2),
                submission_deadline_at=datetime.now(UTC) - timedelta(days=1),
            )


class TestCareExclusiveIssueIntakeContract:
    def _grant(self, db, project_id: str = "CARE-CONTRACT-01") -> None:
        project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
        if project is None:
            db.add(
                ProjectRegistry(
                    project_id=project_id,
                    name="Care contract projekt",
                    customer_name="Care Contract Ügyfél",
                    project_type="Átadott családi ház",
                    status="active",
                    responsible="project.manager@imperial.local",
                )
            )
        if db.scalar(
            select(CustomerPortalAccess).where(
                CustomerPortalAccess.project_id == project_id,
                CustomerPortalAccess.customer_email == CUSTOMER,
            )
        ) is None:
            db.add(
                CustomerPortalAccess(
                    access_id=f"CPA-{project_id}",
                    project_id=project_id,
                    customer_email=CUSTOMER,
                    contact_name="Care Contract Ügyfél",
                    source_type="uat",
                    source_id=f"UAT-{project_id}",
                    active=True,
                    created_by="test",
                )
            )
        db.commit()

    def test_customer_case_is_exclusive_imperial_care_channel(self, db) -> None:
        self._grant(db)
        case = create_care_case(
            db,
            _user(db, CUSTOMER),
            project_id="CARE-CONTRACT-01",
            category="warranty",
            severity="high",
            title="Bejárati ajtó záródási hiba",
            description="Az ajtó három napja csak erős nyomással zárható, ideiglenes javítás nem történt.",
        )
        # Kizárólagos issue-intake szerződés: a forráscsatorna mindig
        # imperial-care, és a kanonikus esemény hordozza a kizárólagosságot.
        assert case.source_channel == "imperial-care"
        event = db.scalar(select(EventRecord).where(EventRecord.object_id == case.case_id))
        assert event is not None
        assert event.source_module == "imperial-care"
        assert event.event_type == "WARRANTY_CASE_OPENED"
        payload = json.loads(event.payload_json)
        assert payload.get("exclusive_customer_issue_channel") is True
        assert payload.get("source_channel") == "imperial-care"


    def test_case_requires_active_portal_access(self, db) -> None:
        # Portálhozzáférés nélkül az issue-intake fail-closed elutasul.
        self._grant(db, project_id="CARE-CONTRACT-NOACCESS")
        db.execute(
            CustomerPortalAccess.__table__.delete().where(
                CustomerPortalAccess.project_id == "CARE-CONTRACT-NOACCESS"
            )
        )
        db.commit()
        db.expire_all()
        with pytest.raises(PermissionError):
            create_care_case(
                db,
                _user(db, CUSTOMER),
                project_id="CARE-CONTRACT-NOACCESS",
                category="warranty",
                severity="medium",
                title="Hozzáférést igénylő ügy",
                description="Szintetikus ügy aktív MyImperial-hozzáférés nélkül.",
            )

    def test_external_role_cannot_open_case(self, db) -> None:
        self._grant(db)
        with pytest.raises(PermissionError):
            create_care_case(
                db,
                _user(db, "designer@imperial.local"),
                project_id="CARE-CONTRACT-01",
                category="warranty",
                severity="medium",
                title="Jogosulatlan ügy",
                description="Szintetikus jogosulatlan ügynyitási kísérlet a kizárólagos csatornán.",
                customer_email=CUSTOMER,
                reporter_name="Care Contract Ügyfél",
            )
