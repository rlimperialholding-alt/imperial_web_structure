from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.models import EventRecord
from app.services import plancheck


def _user(role: str, email: str):
    return SimpleNamespace(role=role, email=email)


def _pdf(label: str) -> bytes:
    stream = io.BytesIO()
    document = canvas.Canvas(stream)
    document.drawString(50, 750, label)
    document.save()
    return stream.getvalue()


def _case(db):
    detail, token = plancheck.create_case(
        db,
        project_id="PRJ-PLANCHECK-UAT-001",
        title="Családi ház tervellenőrzés",
        contact_name="Teszt Ügyfél",
        contact_email="customer@example.test",
        intake={
            "HouseMatchID": "HM-UAT-1",
            "PlotCheckID": "PLOT-UAT-1",
            "BuildConfigID": "CFG-UAT-1",
        },
        actor="creator@imperial.local",
    )
    return detail, token


def test_upload_validates_magic_versions_every_change_and_resets_gates(db, tmp_path, monkeypatch):
    monkeypatch.setattr(plancheck, "RUNTIME_ROOT", tmp_path)
    detail, token = _case(db)
    assert detail["revision"].version == 1
    with pytest.raises(ValueError, match="kártevőgyanús"):
        plancheck.upload_document(
            db,
            token=token,
            category="site_plan",
            file_name="fake.pdf",
            mime_type="application/pdf",
            content=b"MZ-not-a-pdf",
            uploader="customer@example.test",
        )
    uploaded = plancheck.upload_document(
        db,
        token=token,
        category="site_plan",
        file_name="site.pdf",
        mime_type="application/pdf",
        content=_pdf("site"),
        uploader="customer@example.test",
    )
    assert uploaded["revision"].version == 2
    assert uploaded["revision"].confidence_class == "D"
    assert uploaded["documents"][0].page_count == 1
    assert all(gate.decision == "pending" for gate in uploaded["gates"])


def test_high_assumption_blocks_sendable_and_each_gate_needs_distinct_actor(
    db, tmp_path, monkeypatch
):
    monkeypatch.setattr(plancheck, "RUNTIME_ROOT", tmp_path)
    _detail, token = _case(db)
    for category in plancheck.REQUIRED_CATEGORIES:
        detail = plancheck.upload_document(
            db,
            token=token,
            category=category,
            file_name=f"{category}.pdf",
            mime_type="application/pdf",
            content=_pdf(category),
            uploader="customer@example.test",
        )
    case_id = detail["case"].case_id
    detail = plancheck.add_assumption(
        db,
        case_id,
        description="A talajmechanikai alapadat még mérnöki megerősítésre vár.",
        impact="high",
        owner="engineer@imperial.local",
        actor="technical@imperial.local",
    )
    assumption_id = detail["assumptions"][-1].assumption_id
    plancheck.submit_review(db, case_id, "technical@imperial.local")
    plancheck.review_gate(
        db,
        case_id,
        gate_key="input",
        decision="approve",
        note="A bemeneti csomag formai ellenőrzése megfelelő.",
        user=_user("technical-prep", "input@imperial.local"),
    )
    with pytest.raises(ValueError, match="külön személyek"):
        plancheck.review_gate(
            db,
            case_id,
            gate_key="engineering",
            decision="approve",
            note="A mérnöki ellenőrzés megfelelő eredménnyel zárult.",
            user=_user("designer", "input@imperial.local"),
        )
    plancheck.review_gate(
        db,
        case_id,
        gate_key="engineering",
        decision="approve",
        note="A mérnöki ellenőrzés megfelelő eredménnyel zárult.",
        user=_user("designer", "designer@imperial.local"),
    )
    plancheck.review_gate(
        db,
        case_id,
        gate_key="commercial",
        decision="approve",
        note="A kereskedelmi tartalom és vállalás ellenőrizve.",
        user=_user("sales", "sales@imperial.local"),
    )
    plancheck.review_gate(
        db,
        case_id,
        gate_key="finance",
        decision="approve",
        note="A pénzügyi hatás és keret ellenőrzése megtörtént.",
        user=_user("finance", "finance@imperial.local"),
    )
    plancheck.review_gate(
        db,
        case_id,
        gate_key="executive",
        decision="approve",
        note="A vezetői kapu jóváhagyása elkülönített szerepben megtörtént.",
        user=_user("owner", "owner@imperial.local"),
    )
    with pytest.raises(ValueError, match="SENDABLE"):
        plancheck.finalize_case(
            db,
            case_id,
            outcome="sendable",
            note="A tervcsomag kiadható állapotának lezárása.",
            user=_user("owner", "finalizer@imperial.local"),
        )
    detail = plancheck.resolve_assumption(
        db,
        case_id,
        assumption_id,
        resolution="A geotechnikai szakvélemény beérkezett és a feltételezést igazolta.",
        actor="engineer@imperial.local",
    )
    assert detail["revision"].version == 8
    assert all(gate.decision == "pending" for gate in detail["gates"])


def test_complete_a_confidence_flow_creates_verified_pdf_report(db, tmp_path, monkeypatch):
    monkeypatch.setattr(plancheck, "RUNTIME_ROOT", tmp_path)
    _detail, token = _case(db)
    for category in plancheck.REQUIRED_CATEGORIES:
        detail = plancheck.upload_document(
            db,
            token=token,
            category=category,
            file_name=f"{category}.pdf",
            mime_type="application/pdf",
            content=_pdf(category),
            uploader="customer@example.test",
        )
    case_id = detail["case"].case_id
    assert detail["revision"].confidence_class == "A"
    plancheck.submit_review(db, case_id, "technical@imperial.local")
    approvals = [
        ("input", "technical-prep", "input@imperial.local"),
        ("engineering", "designer", "designer@imperial.local"),
        ("commercial", "sales", "sales@imperial.local"),
        ("finance", "finance", "finance@imperial.local"),
        ("executive", "owner", "owner@imperial.local"),
    ]
    for gate, role, email in approvals:
        detail = plancheck.review_gate(
            db,
            case_id,
            gate_key=gate,
            decision="approve",
            note=f"A(z) {gate} kapu dokumentált ellenőrzése megfelelően lezárult.",
            user=_user(role, email),
        )
    assert detail["revision"].final_eligible is True
    final = plancheck.finalize_case(
        db,
        case_id,
        outcome="sendable",
        note="A teljes PlanCheck csomag kiadható és a jelentés elkészült.",
        user=_user("managing-director", "finalizer@imperial.local"),
    )
    assert final["case"].status == "sendable"
    assert final["case"].final_report_document_id
    assert list((tmp_path / case_id / "reports").glob("*.pdf"))
    assert db.scalar(
        select(EventRecord).where(
            EventRecord.event_type == "PLANCHECK_FINALIZED",
            EventRecord.object_id == case_id,
        )
    )
    with pytest.raises(ValueError, match="lezárt PlanCheck"):
        plancheck.upload_document(
            db,
            token=token,
            category="other",
            file_name="late.pdf",
            mime_type="application/pdf",
            content=_pdf("late"),
            uploader="customer@example.test",
        )


def test_internal_workspace_and_public_upload_screen_are_operational(
    logged_in_client, db, tmp_path, monkeypatch
):
    monkeypatch.setattr(plancheck, "RUNTIME_ROOT", tmp_path)
    detail, token = _case(db)
    workspace = logged_in_client.get("/plancheck")
    assert workspace.status_code == 200
    assert detail["case"].case_id in workspace.text
    public = logged_in_client.get(f"/plancheck/upload/{token}")
    assert public.status_code == 200
    assert "Biztonságos feltöltés" in public.text
    uploaded = logged_in_client.post(
        f"/plancheck/upload/{token}",
        data={"category": "site_plan"},
        files={"document": ("site.pdf", _pdf("site"), "application/pdf")},
    )
    assert uploaded.status_code == 200
    assert "új revízióba került" in uploaded.text
    detail_page = logged_in_client.get(f"/plancheck/cases/{detail['case'].case_id}")
    assert detail_page.status_code == 200
    assert "site.pdf" in detail_page.text


def test_upload_link_rotation_and_revocation_are_fail_closed(db):
    detail, original_token = _case(db)
    case_id = detail["case"].case_id
    rotated, replacement_token = plancheck.rotate_upload_link(
        db, case_id, "technical@imperial.local", valid_days=7
    )
    assert rotated["upload_link_active"] is True
    assert replacement_token != original_token
    with pytest.raises(PermissionError, match="érvénytelen vagy lejárt"):
        plancheck.case_for_token(db, original_token)
    assert plancheck.case_for_token(db, replacement_token).case_id == case_id

    revoked = plancheck.revoke_upload_link(db, case_id, "technical@imperial.local")
    assert revoked["upload_link_active"] is False
    with pytest.raises(PermissionError, match="érvénytelen vagy lejárt"):
        plancheck.case_for_token(db, replacement_token)


def test_plancheck_link_management_and_workspace_filters(logged_in_client, db):
    detail, _token = _case(db)
    case_id = detail["case"].case_id
    rotated = logged_in_client.post(
        f"/plancheck/cases/{case_id}/upload-link/rotate",
        data={"valid_days": "14"},
    )
    assert rotated.status_code == 200
    assert "PLANCHECK LINK MEGÚJÍTVA" in rotated.text
    assert "/plancheck/upload/" in rotated.text

    filtered = logged_in_client.get(
        "/plancheck",
        params={"project_id": "PRJ-PLANCHECK-UAT-001", "status": "intake", "query": case_id},
    )
    assert filtered.status_code == 200
    assert case_id in filtered.text
    empty = logged_in_client.get("/plancheck", params={"query": "NINCS-ILYEN-UGY"})
    assert empty.status_code == 200
    assert case_id not in empty.text

    revoked = logged_in_client.post(
        f"/plancheck/cases/{case_id}/upload-link/revoke", follow_redirects=False
    )
    assert revoked.status_code == 303
    detail_page = logged_in_client.get(f"/plancheck/cases/{case_id}")
    assert "lejárt vagy visszavont" in detail_page.text
