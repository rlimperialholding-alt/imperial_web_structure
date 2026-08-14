from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import AuditLog, HouseDesignRevision, HouseDesignSiteVerification, User
from app.services.house_designer import ActorScope, apply_session_command, create_session
from app.services.house_designer_privacy import (
    PRIVATE_SITE_ENVELOPE,
    SitePrivacyError,
    migrate_house_designer_site_encryption,
    protect_site,
    unprotect_site,
)


def _actor(subject: str = "privacy-owner") -> ActorScope:
    return ActorScope(subject, "imperial-holding", frozenset({"imperial"}))


def _site() -> dict[str, object]:
    return {
        "country": "HU",
        "municipalityCode": "011",
        "postalCode": "1111",
        "city": "Mintaváros",
        "address": "Minta utca 12.",
        "parcelNumber": "12345/6",
        "verificationStatus": "unverified",
        "sourceRefs": [],
    }


def test_site_envelope_round_trip_and_tamper_detection():
    protected = protect_site(_site(), "HDR-PRIVACY")
    serialized = json.dumps(protected, ensure_ascii=False)

    assert PRIVATE_SITE_ENVELOPE in protected
    assert "Mintaváros" not in serialized
    assert "Minta utca" not in serialized
    assert "12345/6" not in serialized
    assert unprotect_site(protected, "HDR-PRIVACY") == _site()

    tampered = json.loads(serialized)
    ciphertext = tampered[PRIVATE_SITE_ENVELOPE]["encryptedContent"]
    tampered[PRIVATE_SITE_ENVELOPE]["encryptedContent"] = (
        "A" if ciphertext[0] != "A" else "B"
    ) + ciphertext[1:]
    with pytest.raises(SitePrivacyError) as failure:
        unprotect_site(tampered, "HDR-PRIVACY")
    assert failure.value.code == "site_decryption_failed"


def test_service_stores_private_site_only_as_ciphertext(db):
    design = create_session(
        db,
        actor=_actor(),
        brand_id="imperial",
        title="Titkosított telek",
        command_id=str(uuid4()),
    )
    revision = design["revision"]
    changed = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=_actor(),
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=str(uuid4()),
        command_type="set_site",
        payload=_site(),
    )
    row = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == changed["revision"]["revisionId"]
        )
    )
    assert row is not None
    assert "Mintaváros" not in row.site_json
    assert "Minta utca" not in row.site_json
    assert "12345/6" not in row.site_json
    assert PRIVATE_SITE_ENVELOPE in json.loads(row.site_json)
    assert changed["revision"]["site"] == _site()


def test_startup_cutover_encrypts_legacy_site_and_tokenizes_verification(db):
    design = create_session(
        db,
        actor=_actor("legacy-owner"),
        brand_id="imperial",
        title="Legacy telek",
        command_id=str(uuid4()),
    )
    row = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == design["revision"]["revisionId"]
        )
    )
    assert row is not None
    row.site_json = json.dumps(_site(), ensure_ascii=False)
    original_sha = row.canonical_sha256
    verification = HouseDesignSiteVerification(
        verification_id="HSV-LEGACY",
        session_id=design["sessionId"],
        source_revision_id=row.revision_id,
        verified_revision_id=row.revision_id,
        municipality_code="011",
        parcel_number="12345/6",
        proof_ref="test:legacy-proof",
        proof_sha256="a" * 64,
        verification_method="test_fixture",
        verified_by="legacy-reviewer",
    )
    db.add(verification)
    db.commit()

    result = migrate_house_designer_site_encryption(db)
    db.refresh(row)
    db.refresh(verification)

    assert result == {"encrypted": 1, "tokenized": 1}
    assert row.canonical_sha256 == original_sha
    assert "12345/6" not in row.site_json
    assert verification.parcel_number.startswith("h1:")
    assert verification.parcel_number != "12345/6"
    cutover_audit = db.scalar(
        select(AuditLog).where(AuditLog.action == "house_designer.site.encryption_cutover")
    )
    assert cutover_audit is not None
    assert "12345/6" not in str(cutover_audit.after_json)


def test_api_private_site_read_is_audited_without_values(db, logged_in_client):
    user = db.scalar(select(User).where(User.email == "platform-admin@imperial.local"))
    assert user is not None
    actor = _actor(str(user.itep_subject_id or user.email))
    design = create_session(
        db,
        actor=actor,
        brand_id="imperial",
        title="Auditált telek",
        command_id=str(uuid4()),
    )
    revision = design["revision"]
    changed = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=actor,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=str(uuid4()),
        command_type="set_site",
        payload=_site(),
    )

    response = logged_in_client.get(f"/api/v1/house-designer/sessions/{design['sessionId']}")
    assert response.status_code == 200
    assert response.json()["revision"]["site"] == _site()
    read_audit = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "house_designer.site.read",
            AuditLog.entity_id == changed["revision"]["revisionId"],
        )
        .order_by(AuditLog.id.desc())
    )
    assert read_audit is not None
    serialized_audit = str(read_audit.after_json)
    assert "api-v1" in serialized_audit
    assert "Mintaváros" not in serialized_audit
    assert "Minta utca" not in serialized_audit
    assert "12345/6" not in serialized_audit
