from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import ContractWorkflowRecord, EventRecord
from app.services.commercial_integration import generate_contract_package
from app.services.contract_workflow import (
    activate_contract,
    record_contract_dispatch,
    record_signed_contract,
    review_contract,
    submit_contract_review,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "integrations" / "contract_generator_v0_4" / "examples"


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _payload(example: str = "customer_construction_valid.json") -> dict:
    payload = json.loads((EXAMPLES / example).read_text(encoding="utf-8"))
    token = uuid.uuid4().hex[:10].upper()
    payload["contract_number"] = f"UAT-CON-{token}"
    payload["ids"].update(
        {
            "ProjectID": f"PRJ-CON-{token}",
            "OpportunityID": f"OPP-CON-{token}",
            "CompanyID": f"COM-CON-{token}",
            "PersonID": f"PER-CON-{token}",
            "PartnerID": f"PAR-CON-{token}",
        }
    )
    for attachment in payload["attachments"]:
        attachment["file_id"] = f"EVIDENCE-{token}-{attachment['type']}"
    return payload


def _generated(db, example: str = "customer_construction_valid.json", actor: str = "api"):
    result = generate_contract_package(db, _payload(example), actor=actor)
    row = db.scalar(
        select(ContractWorkflowRecord).where(
            ContractWorkflowRecord.contract_id == result["contract_id"]
        )
    )
    assert row is not None
    return row


def _approve_customer(db, row: ContractWorkflowRecord):
    submit_contract_review(db, row.contract_id, _user("sales"))
    review_contract(
        db,
        row.contract_id,
        _user("finance"),
        gate="commercial",
        decision="approve",
        note="A kereskedelmi feltételek és fizetési ütem megfelelő.",
    )
    review_contract(
        db,
        row.contract_id,
        _user("technical-prep"),
        gate="technical",
        decision="approve",
        note="A műszaki scope és a mellékletek hiánytalanok.",
    )
    review_contract(
        db,
        row.contract_id,
        _user("legal"),
        gate="legal",
        decision="approve",
        note="A szerződéses kockázatok és jogi feltételek elfogadhatók.",
    )
    return review_contract(
        db,
        row.contract_id,
        _user("owner"),
        gate="owner",
        decision="approve",
        note="A szerződés vezetői jóváhagyása megtörtént.",
    )


def test_contract_generation_creates_durable_governed_workflow(db):
    row = _generated(db)
    assert row.status == "generated"
    assert row.legal_required is True
    assert len(row.payload_sha256) == 64
    assert row.package_document_id and row.manifest_document_id
    assert row.work_start_allowed is False


def test_creator_cannot_approve_own_contract_and_gate_actors_are_distinct(db):
    row = _generated(db, actor="sales@imperial.local")
    submit_contract_review(db, row.contract_id, _user("sales"))
    with pytest.raises(ValueError, match="készítője"):
        review_contract(
            db,
            row.contract_id,
            _user("sales"),
            gate="commercial",
            decision="approve",
            note="Saját csomag jóváhagyását a rendszernek tiltania kell.",
        )
    review_contract(
        db,
        row.contract_id,
        _user("managing-director"),
        gate="commercial",
        decision="approve",
        note="A kereskedelmi feltételek vezetői szempontból elfogadhatók.",
    )
    with pytest.raises(ValueError, match="külön személyek"):
        review_contract(
            db,
            row.contract_id,
            _user("managing-director"),
            gate="technical",
            decision="approve",
            note="Ugyanaz a személy másik kaput nem hagyhat jóvá.",
        )


def test_customer_contract_full_flow_emits_event_only_after_dual_dispatch(db):
    row = _generated(db)
    approved = _approve_customer(db, row)
    assert approved.status == "approved"
    digest = "a" * 64
    with pytest.raises(ValueError, match="kézbesítési"):
        activate_contract(db, row.contract_id, _user("project-manager"))
    signed = record_signed_contract(
        db,
        row.contract_id,
        _user("legal"),
        file_id="DRIVE-SIGNED-UAT-001",
        document_sha256=digest,
        signed_at=datetime.now(UTC),
    )
    assert signed.status == "signed"
    payload = json.loads(signed.payload_json)
    with pytest.raises(ValueError, match="nem az aláírt"):
        record_contract_dispatch(
            db,
            row.contract_id,
            _user("sales"),
            postal_sent_at=datetime.now(UTC),
            postal_tracking_number="POST-UAT-001",
            postal_proof_file_id="DRIVE-POST-UAT-001",
            electronic_sent_at=datetime.now(UTC),
            electronic_message_id="GMAIL-UAT-001",
            electronic_recipient=payload["counterparty"]["email"],
            electronic_attachment_sha256="b" * 64,
        )
    dispatched = record_contract_dispatch(
        db,
        row.contract_id,
        _user("sales"),
        postal_sent_at=datetime.now(UTC),
        postal_tracking_number="POST-UAT-001",
        postal_proof_file_id="DRIVE-POST-UAT-001",
        electronic_sent_at=datetime.now(UTC),
        electronic_message_id="GMAIL-UAT-001",
        electronic_recipient=payload["counterparty"]["email"],
        electronic_attachment_sha256=digest,
    )
    assert dispatched.status == "dispatched"
    assert db.scalar(
        select(EventRecord).where(
            EventRecord.event_type == "CONTRACT_SIGNED",
            EventRecord.object_id == row.contract_number,
        )
    ) is None
    active = activate_contract(db, row.contract_id, _user("project-manager"))
    assert active.status == "active"
    assert active.work_start_allowed is True
    event = db.scalar(
        select(EventRecord).where(
            EventRecord.event_type == "CONTRACT_SIGNED",
            EventRecord.object_id == row.contract_number,
        )
    )
    assert event is not None
    assert event.evidence_url == "document://DRIVE-SIGNED-UAT-001"


def test_subcontractor_contract_does_not_require_legal_gate(db):
    row = _generated(db, "subcontractor_execution_valid.json")
    assert row.legal_required is False
    submit_contract_review(db, row.contract_id, _user("sales"))
    review_contract(
        db,
        row.contract_id,
        _user("finance"),
        gate="commercial",
        decision="approve",
        note="A vállalkozói díj és fizetési ütem megfelelő.",
    )
    review_contract(
        db,
        row.contract_id,
        _user("technical-prep"),
        gate="technical",
        decision="approve",
        note="A vállalkozói műszaki tartalom hiánytalan.",
    )
    approved = review_contract(
        db,
        row.contract_id,
        _user("owner"),
        gate="owner",
        decision="approve",
        note="A partneri szerződés vezetői jóváhagyása megtörtént.",
    )
    assert approved.status == "approved"
    with pytest.raises(ValueError, match="nem szükséges"):
        review_contract(
            db,
            row.contract_id,
            _user("legal"),
            gate="legal",
            decision="approve",
            note="Ez a jogi kapu nem tartozik ehhez a szerződéshez.",
        )


def test_workflow_screen_and_direct_signed_api_are_fail_closed(client, db):
    row = _generated(db)
    client.post(
        "/login",
        data={"email": "finance@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    page = client.get(f"/commercial/contracts/{row.contract_id}")
    assert page.status_code == 200
    assert row.contract_number in page.text
    assert "Munkakezdési tilalom" in page.text
    direct = client.post(
        f"/api/commercial/contracts/{row.contract_number}/signed",
        params={"project_id": row.project_id, "evidence_url": "https://invalid.example"},
    )
    assert direct.status_code == 409
