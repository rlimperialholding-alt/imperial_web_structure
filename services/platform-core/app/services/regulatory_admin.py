from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import desc, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    HouseDesignRevision,
    HouseDesignSession,
    HouseDesignSiteVerification,
    RegulatoryRuleInterpretation,
    RegulatoryRuleSet,
    RegulatorySourceSnapshot,
    utcnow,
)
from .house_designer import decode_revision_site
from .house_designer_geometry import canonical_sha256
from .house_designer_privacy import protect_site, verification_identity_token
from .regulatory_compliance import evaluate_rules
from .regulatory_rule_schema import (
    RULE_SCHEMA_VERSION,
    RegulatoryRuleSchemaError,
    normalize_declarative_rules,
)


class RegulatoryAdminError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class RegulatoryActor:
    subject_id: str
    can_author: bool
    can_review: bool


def create_source(
    db: Session,
    *,
    actor: RegulatoryActor,
    source_key: str,
    source_type: str,
    issuer: str,
    scope_key: str,
    source_url: str,
    effective_from: datetime,
    effective_to: datetime | None,
    content_sha256: str,
    normalized_text_sha256: str,
    storage_ref: str,
) -> dict[str, Any]:
    _require_author(actor)
    source_key = source_key.strip()
    scope_key = scope_key.strip()
    if not source_key or not issuer.strip() or not scope_key:
        raise RegulatoryAdminError("source_fields_required", "A forrás kötelező mezői hiányoznak.")
    parsed = urlsplit(source_url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise RegulatoryAdminError("source_url_invalid", "A forrás URL-je csak HTTPS lehet.")
    _hash(content_sha256, "content_sha256")
    _hash(normalized_text_sha256, "normalized_text_sha256")
    if not storage_ref.strip():
        raise RegulatoryAdminError(
            "storage_ref_required", "A változatlan forrás tárolóhivatkozása kötelező."
        )
    effective_from = _aware(effective_from)
    effective_to = _aware(effective_to) if effective_to else None
    if effective_to and effective_to < effective_from:
        raise RegulatoryAdminError("effective_range_invalid", "A hatály vége megelőzi a kezdetét.")
    _lock_scope(db, scope_key)
    latest = db.scalar(
        select(RegulatorySourceSnapshot)
        .where(RegulatorySourceSnapshot.source_key == source_key)
        .order_by(desc(RegulatorySourceSnapshot.revision))
        .with_for_update()
    )
    revision = (latest.revision if latest else 0) + 1
    row = RegulatorySourceSnapshot(
        source_snapshot_id=_id("RSS"),
        source_key=source_key,
        revision=revision,
        source_type=source_type.strip() or "HESZ",
        issuer=issuer.strip(),
        jurisdiction="HU",
        scope_key=scope_key,
        source_url=source_url.strip(),
        effective_from=effective_from,
        effective_to=effective_to,
        content_sha256=content_sha256.lower(),
        normalized_text_sha256=normalized_text_sha256.lower(),
        storage_ref=storage_ref.strip(),
        parser_version="manual-evidence-v1",
        security_status="pending_review",
        status="captured",
        supersedes_snapshot_id=latest.source_snapshot_id if latest else None,
        created_by=actor.subject_id,
        row_version=1,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="regulatory.source.capture",
        entity_type="RegulatorySourceSnapshot",
        entity_id=row.source_snapshot_id,
        after={
            "source_key": source_key,
            "revision": revision,
            "scope_key": scope_key,
            "content_sha256": row.content_sha256,
        },
    )
    _commit(db, "source_revision_conflict")
    return _source_result(row)


def approve_source(
    db: Session,
    *,
    actor: RegulatoryActor,
    source_snapshot_id: str,
    row_version: int,
) -> dict[str, Any]:
    _require_review(actor)
    preview = _source(db, source_snapshot_id)
    _lock_scope(db, preview.scope_key)
    row = _source(db, source_snapshot_id, lock=True)
    if row.row_version != row_version:
        raise RegulatoryAdminError("stale_source", "A forrás időközben módosult.", status_code=409)
    if row.status != "captured" or row.security_status != "pending_review":
        raise RegulatoryAdminError(
            "source_not_reviewable", "A forrás nem hagyható jóvá.", status_code=409
        )
    if row.created_by == actor.subject_id:
        raise RegulatoryAdminError(
            "four_eyes_required",
            "A forrás rögzítője nem hagyhatja jóvá saját rekordját.",
            status_code=409,
        )
    latest_revision = db.scalar(
        select(func.max(RegulatorySourceSnapshot.revision)).where(
            RegulatorySourceSnapshot.source_key == row.source_key
        )
    )
    if latest_revision != row.revision:
        raise RegulatoryAdminError(
            "source_not_latest", "Csak a legújabb forrásverzió hagyható jóvá."
        )
    prior = db.scalars(
        select(RegulatorySourceSnapshot)
        .where(
            RegulatorySourceSnapshot.source_key == row.source_key,
            RegulatorySourceSnapshot.status == "active",
            RegulatorySourceSnapshot.source_snapshot_id != row.source_snapshot_id,
        )
        .with_for_update()
    ).all()
    for item in prior:
        item.status = "superseded"
        item.row_version += 1
    row.security_status = "approved"
    row.status = "active"
    row.approved_by = actor.subject_id
    row.approved_at = utcnow()
    row.row_version += 1
    audit(
        db,
        actor=actor.subject_id,
        action="regulatory.source.approve",
        entity_type="RegulatorySourceSnapshot",
        entity_id=row.source_snapshot_id,
        after={"status": "active", "security_status": "approved"},
    )
    db.commit()
    return _source_result(row)


def revoke_source(
    db: Session,
    *,
    actor: RegulatoryActor,
    source_snapshot_id: str,
    row_version: int,
) -> dict[str, Any]:
    _require_review(actor)
    preview = _source(db, source_snapshot_id)
    _lock_scope(db, preview.scope_key)
    row = _source(db, source_snapshot_id, lock=True)
    if row.row_version != row_version:
        raise RegulatoryAdminError("stale_source", "A forrás időközben módosult.", status_code=409)
    if row.status != "active" or row.security_status != "approved":
        raise RegulatoryAdminError(
            "source_not_revocable",
            "Csak aktív, jóváhagyott forrás vonható vissza.",
            status_code=409,
        )
    row.status = "revoked"
    row.security_status = "revoked"
    row.row_version += 1
    audit(
        db,
        actor=actor.subject_id,
        action="regulatory.source.revoke",
        entity_type="RegulatorySourceSnapshot",
        entity_id=row.source_snapshot_id,
        after={"status": row.status, "security_status": row.security_status},
    )
    db.commit()
    return _source_result(row)


def create_interpretation(
    db: Session,
    *,
    actor: RegulatoryActor,
    source_snapshot_id: str,
    source_span: str,
    rules: dict[str, Any],
    test_vectors: list[dict[str, Any]],
) -> dict[str, Any]:
    _require_author(actor)
    preview = _source(db, source_snapshot_id)
    _lock_scope(db, preview.scope_key)
    source = _source(db, source_snapshot_id, lock=True)
    _require_active_source(source)
    prepared_rules = deepcopy(rules)
    if isinstance(prepared_rules.get("checks"), list):
        for check in prepared_rules["checks"]:
            if not isinstance(check, dict):
                continue
            source_ref = str(check.get("sourceRef") or "").strip()
            if source_ref and source_ref != source_snapshot_id:
                raise RegulatoryAdminError(
                    "rule_source_mismatch",
                    "A deklaratív szabály csak a kiválasztott forrássnapshotra hivatkozhat.",
                )
            check["sourceRef"] = source_snapshot_id
    validated_rules = _rules(prepared_rules)
    _validate_test_vectors(validated_rules, test_vectors)
    if not source_span.strip():
        raise RegulatoryAdminError("source_span_required", "A pontos forráshely kötelező.")
    latest = db.scalar(
        select(RegulatoryRuleInterpretation)
        .where(RegulatoryRuleInterpretation.source_snapshot_id == source_snapshot_id)
        .order_by(desc(RegulatoryRuleInterpretation.revision))
        .with_for_update()
    )
    revision = (latest.revision if latest else 0) + 1
    canonical = {
        "sourceSnapshotId": source_snapshot_id,
        "sourceSha256": source.content_sha256,
        "revision": revision,
        "sourceSpans": [{"locator": source_span.strip()}],
        "rules": validated_rules,
        "testVectors": test_vectors,
        "interpreterVersion": "regulatory-admin-v1",
    }
    row = RegulatoryRuleInterpretation(
        interpretation_id=_id("RRI"),
        source_snapshot_id=source_snapshot_id,
        revision=revision,
        source_spans_json=_json(canonical["sourceSpans"]),
        interpreted_rules_json=_json(validated_rules),
        test_vectors_json=_json(test_vectors),
        interpreter_version="regulatory-admin-v1",
        canonical_sha256=_sha(canonical),
        status="DRAFT",
        authored_by=actor.subject_id,
        row_version=1,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="regulatory.interpretation.create",
        entity_type="RegulatoryRuleInterpretation",
        entity_id=row.interpretation_id,
        after={"source_snapshot_id": source_snapshot_id, "canonical_sha256": row.canonical_sha256},
    )
    _commit(db, "interpretation_revision_conflict")
    return _interpretation_result(row)


def transition_interpretation(
    db: Session,
    *,
    actor: RegulatoryActor,
    interpretation_id: str,
    row_version: int,
    action: str,
) -> dict[str, Any]:
    preview = db.scalar(
        select(RegulatoryRuleInterpretation).where(
            RegulatoryRuleInterpretation.interpretation_id == interpretation_id
        )
    )
    if preview is None:
        raise RegulatoryAdminError(
            "interpretation_not_found", "Az értelmezés nem található.", status_code=404
        )
    preview_source = _source(db, preview.source_snapshot_id)
    _lock_scope(db, preview_source.scope_key)
    row = db.scalar(
        select(RegulatoryRuleInterpretation)
        .where(RegulatoryRuleInterpretation.interpretation_id == interpretation_id)
        .with_for_update()
    )
    if row is None:
        raise RegulatoryAdminError(
            "interpretation_not_found", "Az értelmezés nem található.", status_code=404
        )
    if row.row_version != row_version:
        raise RegulatoryAdminError(
            "stale_interpretation", "Az értelmezés módosult.", status_code=409
        )
    source = _source(db, row.source_snapshot_id, lock=True)
    _require_active_source(source)
    if action == "submit_review":
        _require_author(actor)
        if row.status != "DRAFT" or row.authored_by != actor.subject_id:
            raise RegulatoryAdminError("transition_forbidden", "Nem küldhető review-ra.")
        next_status = "IN_REVIEW"
    elif action == "approve":
        _require_review(actor)
        if row.status != "IN_REVIEW":
            raise RegulatoryAdminError("interpretation_not_reviewable", "Nem hagyható jóvá.")
        if row.authored_by == actor.subject_id:
            raise RegulatoryAdminError(
                "four_eyes_required",
                "A szerző nem hagyhatja jóvá saját értelmezését.",
                status_code=409,
            )
        latest_revision = db.scalar(
            select(func.max(RegulatoryRuleInterpretation.revision)).where(
                RegulatoryRuleInterpretation.source_snapshot_id == row.source_snapshot_id
            )
        )
        if latest_revision != row.revision:
            raise RegulatoryAdminError(
                "interpretation_not_latest", "Csak a legújabb értelmezés hagyható jóvá."
            )
        next_status = "APPROVED"
        row.approved_by = actor.subject_id
        row.approved_at = utcnow()
    else:
        raise RegulatoryAdminError("transition_invalid", "Ismeretlen értelmezési művelet.")
    row.status = next_status
    row.row_version += 1
    audit(
        db,
        actor=actor.subject_id,
        action=f"regulatory.interpretation.{action}",
        entity_type="RegulatoryRuleInterpretation",
        entity_id=interpretation_id,
        after={"status": next_status, "canonical_sha256": row.canonical_sha256},
    )
    db.commit()
    return _interpretation_result(row)


def create_ruleset(
    db: Session,
    *,
    actor: RegulatoryActor,
    scope_key: str,
    national_basis: str,
    local_plan_basis: str,
    effective_from: datetime,
    effective_to: datetime | None,
    interpretation_ids: list[str],
) -> dict[str, Any]:
    _require_author(actor)
    scope_key = scope_key.strip()
    _lock_scope(db, scope_key)
    if not scope_key or not local_plan_basis.strip():
        raise RegulatoryAdminError(
            "ruleset_fields_required", "A szabálykészlet kötelező mezői hiányoznak."
        )
    if national_basis not in {"TÉKA", "OTÉK_TRANSITION"}:
        raise RegulatoryAdminError("national_basis_invalid", "Ismeretlen országos jogalap.")
    ids = sorted(set(item for item in interpretation_ids if item))
    if not ids:
        raise RegulatoryAdminError("interpretation_required", "Jóváhagyott értelmezés szükséges.")
    interpretations = db.scalars(
        select(RegulatoryRuleInterpretation)
        .where(RegulatoryRuleInterpretation.interpretation_id.in_(ids))
        .with_for_update()
    ).all()
    if len(interpretations) != len(ids):
        raise RegulatoryAdminError("interpretation_not_found", "Egy értelmezés nem található.")
    merged: dict[str, Any] = {}
    source_ids: list[str] = []
    for interpretation in interpretations:
        if interpretation.status != "APPROVED":
            raise RegulatoryAdminError(
                "interpretation_not_approved", "Minden értelmezést jóvá kell hagyni."
            )
        latest = db.scalar(
            select(func.max(RegulatoryRuleInterpretation.revision)).where(
                RegulatoryRuleInterpretation.source_snapshot_id == interpretation.source_snapshot_id
            )
        )
        if latest != interpretation.revision:
            raise RegulatoryAdminError(
                "interpretation_not_latest", "Elavult értelmezés nem használható."
            )
        source = _source(db, interpretation.source_snapshot_id, lock=True)
        _require_active_source(source)
        if source.scope_key not in {scope_key, _municipality_scope(scope_key)}:
            raise RegulatoryAdminError("source_scope_mismatch", "A forrás területi hatálya eltér.")
        _merge_rules(merged, json.loads(interpretation.interpreted_rules_json))
        source_ids.append(source.source_snapshot_id)
    effective_from = _aware(effective_from)
    effective_to = _aware(effective_to) if effective_to else None
    if effective_to and effective_to < effective_from:
        raise RegulatoryAdminError("effective_range_invalid", "A hatály vége megelőzi a kezdetét.")
    family_key = f"{scope_key}|{national_basis}|{local_plan_basis.strip()}"
    latest_ruleset = db.scalar(
        select(RegulatoryRuleSet)
        .where(RegulatoryRuleSet.family_key == family_key)
        .order_by(desc(RegulatoryRuleSet.revision))
        .with_for_update()
    )
    revision = (latest_ruleset.revision if latest_ruleset else 0) + 1
    canonical = {
        "familyKey": family_key,
        "revision": revision,
        "scopeKey": scope_key,
        "nationalBasis": national_basis,
        "localPlanBasis": local_plan_basis.strip(),
        "effectiveFrom": _iso(effective_from),
        "effectiveTo": _iso(effective_to) if effective_to else None,
        "sourceSnapshotIds": sorted(source_ids),
        "interpretationIds": ids,
        "rules": merged,
        "interpreterVersion": "regulatory-admin-v1",
    }
    row = RegulatoryRuleSet(
        ruleset_id=_id("RRS"),
        family_key=family_key,
        revision=revision,
        jurisdiction="HU",
        scope_key=scope_key,
        national_basis=national_basis,
        local_plan_basis=local_plan_basis.strip(),
        effective_from=effective_from,
        effective_to=effective_to,
        source_snapshot_ids_json=_json(sorted(source_ids)),
        interpretation_ids_json=_json(ids),
        interpreter_version="regulatory-admin-v1",
        rules_json=_json(merged),
        canonical_sha256=_sha(canonical),
        status="DRAFT",
        authored_by=actor.subject_id,
        supersedes_ruleset_id=latest_ruleset.ruleset_id if latest_ruleset else None,
        row_version=1,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="regulatory.ruleset.create",
        entity_type="RegulatoryRuleSet",
        entity_id=row.ruleset_id,
        after={"scope_key": scope_key, "canonical_sha256": row.canonical_sha256},
    )
    _commit(db, "ruleset_revision_conflict")
    return _ruleset_result(row)


def transition_ruleset(
    db: Session,
    *,
    actor: RegulatoryActor,
    ruleset_id: str,
    row_version: int,
    action: str,
) -> dict[str, Any]:
    preview = db.scalar(select(RegulatoryRuleSet).where(RegulatoryRuleSet.ruleset_id == ruleset_id))
    if preview is None:
        raise RegulatoryAdminError(
            "ruleset_not_found", "A szabálykészlet nem található.", status_code=404
        )
    _lock_scope(db, preview.scope_key)
    row = db.scalar(
        select(RegulatoryRuleSet)
        .where(RegulatoryRuleSet.ruleset_id == ruleset_id)
        .with_for_update()
    )
    if row is None:
        raise RegulatoryAdminError(
            "ruleset_not_found", "A szabálykészlet nem található.", status_code=404
        )
    if row.row_version != row_version:
        raise RegulatoryAdminError("stale_ruleset", "A szabálykészlet módosult.", status_code=409)
    if row.canonical_sha256 != _sha(_ruleset_manifest(row)):
        raise RegulatoryAdminError(
            "ruleset_manifest_mismatch", "A szabálykészlet manifestje eltér.", status_code=409
        )
    if action == "submit_review":
        _require_author(actor)
        if row.status != "DRAFT" or row.authored_by != actor.subject_id:
            raise RegulatoryAdminError("transition_forbidden", "Nem küldhető review-ra.")
        next_status = "IN_REVIEW"
    elif action == "approve":
        _require_review(actor)
        if row.status != "IN_REVIEW":
            raise RegulatoryAdminError("ruleset_not_reviewable", "Nem hagyható jóvá.")
        if row.authored_by == actor.subject_id:
            raise RegulatoryAdminError(
                "four_eyes_required",
                "A szerző nem hagyhatja jóvá saját szabálykészletét.",
                status_code=409,
            )
        latest = db.scalar(
            select(func.max(RegulatoryRuleSet.revision)).where(
                RegulatoryRuleSet.family_key == row.family_key
            )
        )
        if latest != row.revision:
            raise RegulatoryAdminError(
                "ruleset_not_latest", "Csak a legújabb szabálykészlet hagyható jóvá."
            )
        merged: dict[str, Any] = {}
        for interpretation_id in json.loads(row.interpretation_ids_json):
            interpretation = db.scalar(
                select(RegulatoryRuleInterpretation)
                .where(RegulatoryRuleInterpretation.interpretation_id == interpretation_id)
                .with_for_update()
            )
            if interpretation is None or interpretation.status != "APPROVED":
                raise RegulatoryAdminError(
                    "interpretation_not_approved",
                    "A szabálykészlet egyik értelmezése nem jóváhagyott.",
                )
            latest_interpretation = db.scalar(
                select(func.max(RegulatoryRuleInterpretation.revision)).where(
                    RegulatoryRuleInterpretation.source_snapshot_id
                    == interpretation.source_snapshot_id
                )
            )
            if latest_interpretation != interpretation.revision:
                raise RegulatoryAdminError(
                    "interpretation_not_latest", "A szabálykészlet egyik értelmezése elavult."
                )
            _require_active_source(_source(db, interpretation.source_snapshot_id, lock=True))
            _merge_rules(merged, json.loads(interpretation.interpreted_rules_json))
        if merged != json.loads(row.rules_json):
            raise RegulatoryAdminError(
                "ruleset_material_changed", "Az értelmezések tartalma eltér a szabálykészlettől."
            )
        prior = db.scalars(
            select(RegulatoryRuleSet)
            .where(
                RegulatoryRuleSet.family_key == row.family_key,
                RegulatoryRuleSet.status == "APPROVED",
                RegulatoryRuleSet.ruleset_id != row.ruleset_id,
            )
            .with_for_update()
        ).all()
        for item in prior:
            item.status = "SUPERSEDED"
            item.row_version += 1
        next_status = "APPROVED"
        row.approved_by = actor.subject_id
        row.approved_at = utcnow()
    elif action == "revoke":
        _require_review(actor)
        if row.status != "APPROVED":
            raise RegulatoryAdminError(
                "ruleset_not_revocable",
                "Csak jóváhagyott szabálykészlet vonható vissza.",
                status_code=409,
            )
        next_status = "REVOKED"
    else:
        raise RegulatoryAdminError("transition_invalid", "Ismeretlen szabálykészlet-művelet.")
    row.status = next_status
    row.row_version += 1
    audit(
        db,
        actor=actor.subject_id,
        action=f"regulatory.ruleset.{action}",
        entity_type="RegulatoryRuleSet",
        entity_id=ruleset_id,
        after={"status": next_status, "canonical_sha256": row.canonical_sha256},
    )
    db.commit()
    return _ruleset_result(row)


def verify_design_site(
    db: Session,
    *,
    actor: RegulatoryActor,
    tenant_id: str,
    session_id: str,
    proof_ref: str,
    proof_sha256: str,
    verification_method: str,
    command_id: str,
) -> dict[str, Any]:
    _require_review(actor)
    _hash(proof_sha256, "proof_sha256")
    if not proof_ref.strip() or not verification_method.strip() or not command_id.strip():
        raise RegulatoryAdminError(
            "verification_fields_required",
            "A telekigazolás bizonyítéka és műveletazonosítója kötelező.",
        )
    session = db.scalar(
        select(HouseDesignSession)
        .where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if session is None:
        raise RegulatoryAdminError("session_not_found", "A házterv nem található.", status_code=404)
    current = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    if current is None:
        raise RegulatoryAdminError(
            "revision_not_found", "A tervverzió nem található.", status_code=409
        )
    replay = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.session_id == session_id,
            HouseDesignRevision.command_id == command_id,
        )
    )
    if replay:
        verification = db.scalar(
            select(HouseDesignSiteVerification).where(
                HouseDesignSiteVerification.verified_revision_id == replay.revision_id
            )
        )
        if verification is None:
            raise RegulatoryAdminError(
                "idempotency_collision",
                "A műveletazonosító más tervművelethez tartozik.",
                status_code=409,
            )
        if (
            verification.proof_ref != proof_ref.strip()
            or verification.proof_sha256 != proof_sha256.lower()
            or verification.verification_method != verification_method.strip()
        ):
            raise RegulatoryAdminError(
                "idempotency_collision",
                "A műveletazonosító más igazoláshoz tartozik.",
                status_code=409,
            )
        return _verification_result(db, verification)
    command_payload = {
        "sessionId": session_id,
        "sourceRevisionId": current.revision_id,
        "proofRef": proof_ref.strip(),
        "proofSha256": proof_sha256.lower(),
        "verificationMethod": verification_method.strip(),
    }
    command_sha256 = _sha(command_payload)
    geometry = json.loads(current.geometry_json)
    configuration = json.loads(current.configuration_json)
    site = decode_revision_site(current)
    municipality = str(site.get("municipalityCode") or "").strip()
    parcel = str(site.get("parcelNumber") or "").strip()
    if not municipality or not parcel:
        raise RegulatoryAdminError(
            "site_identity_incomplete",
            "Településkód és helyrajzi szám nélkül a telek nem igazolható.",
        )
    site = {
        **site,
        "verificationStatus": "verified",
        "verifiedAt": _iso(utcnow()),
        "verificationMethod": verification_method.strip(),
        "sourceRefs": [
            {
                "proofRef": proof_ref.strip(),
                "proofSha256": proof_sha256.lower(),
            }
        ],
    }
    revision_id = _id("HDR")
    revision = HouseDesignRevision(
        revision_id=revision_id,
        session_id=session_id,
        revision_no=current.revision_no + 1,
        predecessor_revision_id=current.revision_id,
        command_id=command_id.strip(),
        command_type="verify_site",
        command_sha256=command_sha256,
        geometry_json=current.geometry_json,
        configuration_json=current.configuration_json,
        site_json=_json(protect_site(site, revision_id)),
        canonical_sha256=_sha(
            {
                "geometrySha256": canonical_sha256(geometry),
                "configuration": configuration,
                "site": site,
            }
        ),
        change_summary="A telekazonosító bizonyítékkal igazolva.",
        created_by=actor.subject_id,
    )
    verification = HouseDesignSiteVerification(
        verification_id=_id("HSV"),
        session_id=session_id,
        source_revision_id=current.revision_id,
        verified_revision_id=revision_id,
        municipality_code=municipality,
        parcel_number=verification_identity_token(municipality, parcel),
        proof_ref=proof_ref.strip(),
        proof_sha256=proof_sha256.lower(),
        verification_method=verification_method.strip(),
        verified_by=actor.subject_id,
    )
    session.current_revision_id = revision_id
    session.status = "CHECK_REQUIRED"
    session.row_version += 1
    session.updated_by = actor.subject_id
    db.add_all([revision, verification])
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.site.verify",
        entity_type="HouseDesignSession",
        entity_id=session_id,
        before={"revision_id": current.revision_id, "verificationStatus": "unverified"},
        after={
            "revision_id": revision_id,
            "verification_id": verification.verification_id,
            "verificationStatus": "verified",
            "proof_sha256": verification.proof_sha256,
        },
    )
    _commit(db, "site_verification_conflict")
    return _verification_result(db, verification)


def regulatory_dashboard(db: Session, *, actor_subject_id: str) -> dict[str, Any]:
    sources = db.scalars(
        select(RegulatorySourceSnapshot)
        .order_by(desc(RegulatorySourceSnapshot.created_at))
        .limit(200)
    ).all()
    interpretations = db.scalars(
        select(RegulatoryRuleInterpretation)
        .order_by(desc(RegulatoryRuleInterpretation.created_at))
        .limit(200)
    ).all()
    rulesets = db.scalars(
        select(RegulatoryRuleSet).order_by(desc(RegulatoryRuleSet.created_at)).limit(200)
    ).all()
    verifications = db.scalars(
        select(HouseDesignSiteVerification)
        .order_by(desc(HouseDesignSiteVerification.verified_at))
        .limit(200)
    ).all()
    result = {
        "sources": [_source_result(row) for row in sources],
        "interpretations": [_interpretation_result(row) for row in interpretations],
        "rulesets": [_ruleset_result(row) for row in rulesets],
        "verifications": [_verification_result(db, row) for row in verifications],
    }
    if verifications:
        audit(
            db,
            actor=actor_subject_id,
            action="house_designer.site.read",
            entity_type="HouseDesignSiteVerification",
            after={"channel": "regulatory-admin", "record_count": len(verifications)},
        )
        db.commit()
    return result


def _rules(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "maxStoreys",
        "maxGrossAreaM2",
        "allowedRoofTypes",
        "schemaVersion",
        "checks",
    }
    unknown = set(value) - allowed
    if unknown:
        raise RegulatoryAdminError("rule_key_unknown", f"Ismeretlen szabálymező: {sorted(unknown)}")
    result: dict[str, Any] = {}
    if value.get("maxStoreys") not in {None, ""}:
        max_storeys = int(value["maxStoreys"])
        if not 1 <= max_storeys <= 3:
            raise RegulatoryAdminError("max_storeys_invalid", "A szintkorlát 1–3 lehet.")
        result["maxStoreys"] = max_storeys
    if value.get("maxGrossAreaM2") not in {None, ""}:
        max_gross_area_m2 = float(value["maxGrossAreaM2"])
        if not 10 <= max_gross_area_m2 <= 10_000:
            raise RegulatoryAdminError("max_area_invalid", "A területkorlát érvénytelen.")
        result["maxGrossAreaM2"] = max_gross_area_m2
    roof_types = value.get("allowedRoofTypes")
    if roof_types:
        valid = {"gable", "hip", "flat", "shed"}
        roofs = sorted(set(str(item) for item in roof_types))
        if not set(roofs) <= valid:
            raise RegulatoryAdminError("roof_type_invalid", "Ismeretlen tetőtípus.")
        result["allowedRoofTypes"] = roofs
    checks = value.get("checks")
    if checks is not None and checks != "":
        if value.get("schemaVersion") != RULE_SCHEMA_VERSION:
            raise RegulatoryAdminError(
                "rule_schema_invalid",
                f"A deklaratív szabályséma kötelező verziója: {RULE_SCHEMA_VERSION}.",
            )
        try:
            result["checks"] = normalize_declarative_rules(checks)
        except RegulatoryRuleSchemaError as error:
            raise RegulatoryAdminError(error.code, str(error)) from error
        result["schemaVersion"] = RULE_SCHEMA_VERSION
    if not result:
        raise RegulatoryAdminError("rules_required", "Legalább egy végrehajtható szabály kötelező.")
    return result


def _merge_rules(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if key in {"checks", "schemaVersion"}:
            continue
        if key in target and target[key] != value:
            raise RegulatoryAdminError("rule_conflict", f"Ellentmondó szabály: {key}.")
        target[key] = value
    checks = incoming.get("checks")
    if checks is None:
        return
    if incoming.get("schemaVersion") != RULE_SCHEMA_VERSION:
        raise RegulatoryAdminError("rule_schema_invalid", "Eltérő deklaratív szabályséma.")
    existing = {item["code"]: item for item in target.get("checks", [])}
    for item in checks:
        prior = existing.get(item["code"])
        if prior is not None and prior != item:
            raise RegulatoryAdminError(
                "rule_conflict", f"Ellentmondó deklaratív szabály: {item['code']}."
            )
        existing[item["code"]] = item
    target["schemaVersion"] = RULE_SCHEMA_VERSION
    target["checks"] = [existing[code] for code in sorted(existing)]


def _validate_test_vectors(rules: dict[str, Any], vectors: list[dict[str, Any]]) -> None:
    if not vectors:
        raise RegulatoryAdminError("test_vectors_required", "Legalább egy szabályteszt kötelező.")
    for index, vector in enumerate(vectors):
        if not isinstance(vector, dict) or not isinstance(vector.get("geometry"), dict):
            raise RegulatoryAdminError(
                "test_vector_invalid", f"A(z) {index + 1}. tesztvektor geometriája hiányzik."
            )
        if not isinstance(vector.get("site"), dict):
            raise RegulatoryAdminError(
                "test_vector_invalid", f"A(z) {index + 1}. tesztvektor telekadata hiányzik."
            )
        expected = str(vector.get("expectedOutcome") or "")
        if expected not in {"PASS", "FAIL", "UNKNOWN"}:
            raise RegulatoryAdminError(
                "test_vector_invalid", f"A(z) {index + 1}. teszt várt eredménye hibás."
            )
        configuration = vector.get("configuration") or {}
        if not isinstance(configuration, dict):
            raise RegulatoryAdminError(
                "test_vector_invalid",
                f"A(z) {index + 1}. tesztvektor konfigurációja hibás.",
            )
        outcome, _ = evaluate_rules(
            vector["geometry"], vector["site"], rules, configuration
        )
        if outcome != expected:
            raise RegulatoryAdminError(
                "test_vector_failed",
                f"A(z) {index + 1}. teszt {expected} helyett {outcome} eredményt adott.",
            )


def _source(
    db: Session, source_snapshot_id: str, *, lock: bool = False
) -> RegulatorySourceSnapshot:
    query = select(RegulatorySourceSnapshot).where(
        RegulatorySourceSnapshot.source_snapshot_id == source_snapshot_id
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise RegulatoryAdminError("source_not_found", "A forrás nem található.", status_code=404)
    return row


def _require_active_source(row: RegulatorySourceSnapshot) -> None:
    if row.status != "active" or row.security_status != "approved":
        raise RegulatoryAdminError(
            "source_not_approved", "A forrás nem aktív és jóváhagyott.", status_code=409
        )


def _require_author(actor: RegulatoryActor) -> None:
    if not actor.can_author:
        raise RegulatoryAdminError(
            "author_forbidden", "Nincs szabályszerzői jogosultság.", status_code=403
        )


def _require_review(actor: RegulatoryActor) -> None:
    if not actor.can_review:
        raise RegulatoryAdminError(
            "review_forbidden", "Nincs szabályreview-jogosultság.", status_code=403
        )


def _source_result(row: RegulatorySourceSnapshot) -> dict[str, Any]:
    return {
        "sourceSnapshotId": row.source_snapshot_id,
        "sourceKey": row.source_key,
        "revision": row.revision,
        "issuer": row.issuer,
        "scopeKey": row.scope_key,
        "sourceUrl": row.source_url,
        "storageRef": row.storage_ref,
        "contentSha256": row.content_sha256,
        "securityStatus": row.security_status,
        "status": row.status,
        "rowVersion": row.row_version,
        "createdBy": row.created_by,
        "createdAt": row.created_at,
    }


def _interpretation_result(row: RegulatoryRuleInterpretation) -> dict[str, Any]:
    return {
        "interpretationId": row.interpretation_id,
        "sourceSnapshotId": row.source_snapshot_id,
        "revision": row.revision,
        "rules": json.loads(row.interpreted_rules_json),
        "sourceSpans": json.loads(row.source_spans_json),
        "canonicalSha256": row.canonical_sha256,
        "status": row.status,
        "rowVersion": row.row_version,
        "authoredBy": row.authored_by,
        "createdAt": row.created_at,
    }


def _ruleset_result(row: RegulatoryRuleSet) -> dict[str, Any]:
    return {
        "rulesetId": row.ruleset_id,
        "revision": row.revision,
        "scopeKey": row.scope_key,
        "nationalBasis": row.national_basis,
        "localPlanBasis": row.local_plan_basis,
        "rules": json.loads(row.rules_json),
        "sourceSnapshotIds": json.loads(row.source_snapshot_ids_json),
        "interpretationIds": json.loads(row.interpretation_ids_json),
        "canonicalSha256": row.canonical_sha256,
        "status": row.status,
        "rowVersion": row.row_version,
        "authoredBy": row.authored_by,
        "effectiveFrom": row.effective_from,
        "effectiveTo": row.effective_to,
        "createdAt": row.created_at,
    }


def _ruleset_manifest(row: RegulatoryRuleSet) -> dict[str, Any]:
    return {
        "familyKey": row.family_key,
        "revision": row.revision,
        "scopeKey": row.scope_key,
        "nationalBasis": row.national_basis,
        "localPlanBasis": row.local_plan_basis,
        "effectiveFrom": _iso(row.effective_from),
        "effectiveTo": _iso(row.effective_to) if row.effective_to else None,
        "sourceSnapshotIds": sorted(json.loads(row.source_snapshot_ids_json)),
        "interpretationIds": sorted(json.loads(row.interpretation_ids_json)),
        "rules": json.loads(row.rules_json),
        "interpreterVersion": row.interpreter_version,
    }


def _verification_result(db: Session, row: HouseDesignSiteVerification) -> dict[str, Any]:
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == row.verified_revision_id
        )
    )
    if revision is None:
        raise RegulatoryAdminError(
            "verified_revision_missing", "Az igazolt tervverzió nem található.", status_code=409
        )
    parcel_number = str(decode_revision_site(revision).get("parcelNumber") or "")
    return {
        "verificationId": row.verification_id,
        "sessionId": row.session_id,
        "sourceRevisionId": row.source_revision_id,
        "verifiedRevisionId": row.verified_revision_id,
        "municipalityCode": row.municipality_code,
        "parcelNumber": parcel_number,
        "proofRef": row.proof_ref,
        "proofSha256": row.proof_sha256,
        "verificationMethod": row.verification_method,
        "verifiedBy": row.verified_by,
        "verifiedAt": _iso(row.verified_at),
    }


def _hash(value: str, field: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value.strip()):
        raise RegulatoryAdminError("hash_invalid", f"A(z) {field} nem SHA-256 érték.")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return _aware(value).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _municipality_scope(scope_key: str) -> str:
    parts = scope_key.split(":")
    return f"{parts[0]}:{parts[1]}:*" if len(parts) >= 2 else scope_key


def _lock_scope(db: Session, scope_key: str) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"house-designer-regulatory:{_municipality_scope(scope_key)}"},
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _commit(db: Session, code: str) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise RegulatoryAdminError(
            code, "Párhuzamos verzióütközés történt.", status_code=409
        ) from error
