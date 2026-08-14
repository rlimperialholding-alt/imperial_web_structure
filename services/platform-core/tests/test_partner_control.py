from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import PartnerFieldAccess, PartnerProfile, ProjectRegistry, TenderPackage
from app.services.partner_control import (
    add_certificate,
    approve_decision,
    approve_partner,
    certificate_state,
    close_incident,
    create_incident,
    create_partner,
    create_project_evaluation,
    declare_capacity,
    eligibility_report,
    propose_decision,
    record_incident_response,
    review_capacity,
    review_decision,
    set_external_score,
    verify_certificate,
)


def _user(role: str, email: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, email=email)


PM = _user("project-manager", "pm@imperial.local")
TECH = _user("technical-prep", "technical@imperial.local")
FINANCE = _user("finance", "finance@imperial.local")
LEADERSHIP = _user("managing-director", "md@imperial.local")


def _approved_partner(db):
    partner = create_partner(
        db,
        PM,
        company_name="Kontroll Partner Kft.",
        primary_email="partner@example.com",
        tax_number="12345678-2-42",
        trade_categories=["szerkezet"],
        territories=["Budapest"],
    )
    set_external_score(
        db,
        partner.partner_id,
        TECH,
        score="88",
        evidence_ref="drive://partnercheck/company-registry",
    )
    approve_partner(
        db, partner.partner_id, FINANCE, note="Cégjegyzék, pénzügy és referenciák ellenőrizve."
    )
    return partner


def test_prequalification_certificates_capacity_and_fail_closed_eligibility(db):
    partner = _approved_partner(db)
    tender = TenderPackage(
        tender_id="TENDER-PARTNER-GATE",
        project_id="P-1",
        title="Partner gate",
        scope="Részletes partner gate teszt műszaki tartalommal.",
        currency="HUF",
        question_deadline_at=datetime.now(UTC) + timedelta(days=1),
        submission_deadline_at=datetime.now(UTC) + timedelta(days=2),
        status="draft",
        evaluation_criteria_json="{}",
        created_by=PM.email,
        prequalification_required=True,
        certificate_gate_enabled=True,
        required_certificate_types_json='["liability_insurance","tax_clearance"]',
    )
    db.add(tender)
    db.commit()
    blocked = eligibility_report(db, partner.partner_id, tender=tender)
    assert blocked["eligible"] is False
    assert set(blocked["blockers"]) == {
        "certificate:liability_insurance",
        "certificate:tax_clearance",
    }

    for cert_type in ("liability_insurance", "tax_clearance"):
        cert = add_certificate(
            db,
            partner.partner_id,
            PM,
            certificate_type=cert_type,
            issuer="Hatóság Zrt.",
            document_ref=f"drive://certificates/{cert_type}",
            document_sha256=("a" if cert_type == "liability_insurance" else "b") * 64,
            valid_from=date.today() - timedelta(days=10),
            valid_until=date.today() + timedelta(days=300),
        )
        assert certificate_state(cert) == "incomplete"
        verify_certificate(db, cert.certificate_id, FINANCE, accepted=True)
        assert certificate_state(cert) == "valid"

    capacity = declare_capacity(
        db,
        partner.partner_id,
        PM,
        trade_category="szerkezet",
        territory="Budapest",
        available_from=date.today(),
        available_until=date.today() + timedelta(days=90),
        crew_count=12,
        monthly_capacity="100",
        committed_capacity="25",
        evidence_ref="drive://capacity/q3",
    )
    assert (
        eligibility_report(
            db,
            partner.partner_id,
            tender=tender,
            trade_category="szerkezet",
            territory="Budapest",
            required_capacity="50",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=30),
        )["eligible"]
        is False
    )
    review_capacity(
        db, capacity.declaration_id, TECH, accepted=True, note="Létszám és vállalások ellenőrizve."
    )
    passed = eligibility_report(
        db,
        partner.partner_id,
        tender=tender,
        trade_category="szerkezet",
        territory="Budapest",
        required_capacity="50",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
    )
    assert passed["eligible"] is True and passed["blockers"] == []


def test_partnercheck_uses_70_30_external_internal_score(db):
    partner = _approved_partner(db)
    db.add(
        ProjectRegistry(
            project_id="PARTNER-PROJECT",
            name="Partner értékelés",
            status="active",
            responsible=PM.email,
        )
    )
    db.commit()
    evaluation = create_project_evaluation(
        db,
        partner.partner_id,
        "PARTNER-PROJECT",
        PM,
        quality=5,
        deadline=4,
        documentation=4,
        hse=5,
        commercial=4,
        cooperation=5,
        warranty=4,
        notes="Dokumentált projektzáró értékelés jó minőségű teljesítéssel.",
    )
    db.refresh(partner)
    assert evaluation.weighting_version == "partner-score-v1"
    assert str(evaluation.score_100) == "90.00"
    assert str(partner.internal_score) == "90.00"
    assert str(partner.combined_score) == "88.60"


def test_critical_incident_suspends_and_reinstatement_requires_segregated_approval(db):
    partner = _approved_partner(db)
    access = PartnerFieldAccess(
        access_id="PFA-PARTNER-CONTROL-UAT",
        company_name=partner.company_name,
        company_tax_number=partner.tax_number,
        project_id="FIELD-UAT",
        access_code_hash="not-used-in-this-test",
        active=True,
    )
    db.add(access)
    db.commit()
    incident = create_incident(
        db,
        partner.partner_id,
        PM,
        incident_type="hse",
        severity="critical",
        facts="Dokumentált, súlyos munkavédelmi szabályszegés történt a helyszínen.",
        requirement_breached="A kötelező leesésvédelem alkalmazása dokumentáltan elmaradt.",
        immediate_risk="Az esemény közvetlen élet- és balesetveszélyt okozott a munkaterületen.",
        evidence_refs=["drive://incidents/photo-1"],
    )
    db.refresh(partner)
    assert incident.immediate_suspension is True and partner.status == "suspended"
    db.refresh(access)
    assert access.active is False
    assert eligibility_report(db, partner.partner_id)["eligible"] is False

    with pytest.raises(ValueError, match="partnernyilatkozat"):
        close_incident(
            db,
            incident.incident_id,
            PM,
            outcome="A helyszíni lezárás bizonyítéka rendelkezésre áll.",
        )

    premature = propose_decision(
        db,
        partner.partner_id,
        PM,
        decision_type="approved",
        basis={"incident_id": incident.incident_id, "corrective_audit": "drive://audit/closed"},
        review_at=datetime.now(UTC) + timedelta(days=180),
    )
    review_decision(
        db,
        premature.decision_id,
        PM,
        review_type="pm",
        note="Korrekció és helyszíni visszaellenőrzés előkészítve.",
    )
    with pytest.raises(ValueError, match="reinstatement review"):
        approve_decision(
            db,
            premature.decision_id,
            LEADERSHIP,
            notification_evidence_ref="drive://decision/premature",
        )

    review = propose_decision(
        db,
        partner.partner_id,
        PM,
        decision_type="reinstatement_review",
        basis={"incident_id": incident.incident_id, "review_scope": "helyszíni HSE és korrekció"},
        review_at=datetime.now(UTC) + timedelta(days=30),
    )
    review_decision(
        db,
        review.decision_id,
        PM,
        review_type="pm",
        note="A visszaengedélyezési vizsgálat szakmai köre megfelelő.",
    )
    review_decision(
        db,
        review.decision_id,
        FINANCE,
        review_type="finance_legal",
        note="A jogi és biztosítási kontroll felülvizsgálva.",
    )
    approve_decision(
        db,
        review.decision_id,
        LEADERSHIP,
        notification_evidence_ref="drive://decision/review-notice",
    )
    db.refresh(partner)
    assert partner.status == "suspended" and partner.current_decision_id == review.decision_id

    record_incident_response(
        db,
        incident.incident_id,
        PM,
        partner_statement="A partner a HSE-hiányt elismerte és a tényállást elfogadta.",
        corrective_action=(
            "Kollektív védelem kiépítése, oktatás és dokumentált helyszíni visszaellenőrzés."
        ),
        corrective_owner="partner-hse@example.com",
        corrective_due_at=datetime.now(UTC) + timedelta(days=7),
    )
    close_incident(
        db,
        incident.incident_id,
        PM,
        outcome="A korrekció fotóval, oktatási ívvel és helyszíni auditjegyzőkönyvvel igazolt.",
    )

    decision = propose_decision(
        db,
        partner.partner_id,
        PM,
        decision_type="approved",
        basis={"incident_id": incident.incident_id, "corrective_audit": "drive://audit/closed"},
        review_at=datetime.now(UTC) + timedelta(days=180),
    )
    review_decision(
        db,
        decision.decision_id,
        PM,
        review_type="pm",
        note="Korrekció és helyszíni visszaellenőrzés rendben.",
    )
    approve_decision(
        db, decision.decision_id, LEADERSHIP, notification_evidence_ref="drive://decision/notice"
    )
    db.refresh(partner)
    assert partner.status == "approved" and partner.current_decision_id == decision.decision_id


def test_overdue_requalification_and_recurring_major_incident_fail_closed(db):
    partner = _approved_partner(db)
    partner.next_review_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    report = eligibility_report(db, partner.partner_id)
    assert report["eligible"] is False
    assert "qualification_review_overdue" in report["blockers"]

    partner.next_review_at = datetime.now(UTC) + timedelta(days=365)
    db.commit()
    incident = create_incident(
        db,
        partner.partner_id,
        PM,
        incident_type="delay",
        severity="major",
        recurring=True,
        facts=(
            "Az igazolt ütemtervi mérföldkő ismételten és súlyosan, előzetes jelzés nélkül késett."
        ),
        requirement_breached=(
            "A szerződéses határidő és a kötelező előrejelzési rend ismételten megsérült."
        ),
        immediate_risk=(
            "A késés a követő szakágakat és a projekt kritikus útját bizonyítottan veszélyezteti."
        ),
        evidence_refs=["drive://incidents/repeated-delay"],
    )
    db.refresh(partner)
    assert incident.immediate_suspension is True
    assert partner.status == "suspended"


def test_restrictive_decision_requires_finance_legal_review(db):
    partner = _approved_partner(db)
    decision = propose_decision(
        db,
        partner.partner_id,
        PM,
        decision_type="excluded",
        basis={"reason": "ismétlődő súlyos szerződésszegés", "evidence": "drive://case/1"},
    )
    review_decision(
        db,
        decision.decision_id,
        PM,
        review_type="pm",
        note="A projektoldali tényállás bizonyított.",
    )
    with pytest.raises(ValueError, match="pénzügyi/jogi"):
        approve_decision(
            db,
            decision.decision_id,
            LEADERSHIP,
            notification_evidence_ref="drive://decision/exclusion",
        )
    review_decision(
        db,
        decision.decision_id,
        FINANCE,
        review_type="finance_legal",
        note="Pénzügyi és jogi kockázat ellenőrizve.",
    )
    approve_decision(
        db, decision.decision_id, LEADERSHIP, notification_evidence_ref="drive://decision/exclusion"
    )
    current = db.scalar(
        select(PartnerProfile).where(PartnerProfile.partner_id == partner.partner_id)
    )
    assert current.status == "excluded"


def test_partner_control_screen_and_role_boundary(client, db):
    response = client.post(
        "/login",
        data={"email": "project-manager@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    created = client.post(
        "/partners",
        data={
            "company_name": "Képernyő Teszt Kft.",
            "primary_email": "screen.partner@example.com",
            "tax_number": "99887766-2-41",
            "trade_categories": "gépészet",
            "territories": "Budapest",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    page = client.get("/partners")
    assert page.status_code == 200
    assert "Képernyő Teszt Kft." in page.text
    assert "Partnerincidens" in page.text and "Kapacitásnyilatkozat" in page.text
    assert "Együttműködés" in page.text and "Garanciális visszatérés" in page.text
    client.cookies.clear()
    assert (
        client.post(
            "/login",
            data={"email": "customer@imperial.local", "password": "Imperial2026!"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert client.get("/partners").status_code == 403
    client.cookies.clear()
    assert (
        client.post(
            "/login",
            data={"email": "subcontractor@imperial.local", "password": "Imperial2026!"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert client.get("/partners").status_code == 403
