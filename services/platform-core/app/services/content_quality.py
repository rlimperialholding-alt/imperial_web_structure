from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..copy_gate.campaign_package import (
    CampaignPackage,
    CampaignPackageGateSubmission,
    artifact_set_digest,
    cross_brand_failures,
    package_hash,
)
from ..copy_gate.engine import evaluate_content
from ..copy_gate.models import (
    MANDATORY_COPY_GATE_DIMENSIONS,
    ApprovalSubmission,
    AssemblySubmission,
    CanonicalSources,
    ContentAsset,
    ContentEvaluationRequest,
    CopyBrief,
    CopySourceIn,
    CreativeDirectorReviewSubmission,
    Decision,
    EditorialReview,
    FourGateSubmission,
    GateResult,
    LiveReviewSubmission,
    MandatoryCopyGateReviewSubmission,
    PerformanceMetricIn,
    PublicationState,
    ReleaseReviewSubmission,
    StrategyReviewSubmission,
    VisualProductionSubmission,
)
from ..copy_gate.orchestrator import (
    GENERATION_STAGES,
    copy_mode_allows_source_prevalidation,
    validate_copy_variation_trace,
    validate_visual_variant_trace,
)
from ..copy_gate.promotions import resolve_monthly_promotion
from ..models import (
    CampaignStrategyReviewRecord,
    ContentApprovalRecord,
    ContentAssetRecord,
    ContentGateDecision,
    ContentPerformanceMetric,
    ContentWorkflowReviewRecord,
    CopyBriefRecord,
    CopyReviewRun,
    CopySourceRecord,
    CreativeProductionRunRecord,
    OutboxMessage,
    PublicationBundleRecord,
    TaskRecord,
)
from .commercial_prevalidation import evaluate_commercial_prevalidation

REQUIRED_SOURCE_TYPES = {
    "brand_master",
    "brand_voice_profile",
    "conversion_guide",
    "design_system",
    "offer_version",
    "price_snapshot",
    "terms_version",
    "channel_rules",
}

SPECIALIST_GATE_AGENTS = {
    "GATE_2_LEGAL_POLICY": "AGT-016",
    "GATE_3_FINANCIAL_COMMERCIAL": "AGT-011",
    "GATE_4_TECHNICAL_FACTUAL": "AGT-013",
}
EXPERT_REVIEW_PROMPT_VERSION = "expert-hungarian-direct-response-v2"
MANDATORY_COPY_GATE_PROMPT_VERSIONS = {
    "MARKETING": "marketing-gate-v1",
    "DIRECT_RESPONSE": "direct-response-copy-gate-v1",
}
VISUAL_REVIEW_PROMPT_VERSION = "visual-art-direction-gate-v1"
PUBLICATION_ADAPTER_CONTRACT_VERSION = "publication-gate-envelope-v2"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _signed_submission(payload: Any, secret: str) -> Any:
    signature = hmac.new(
        secret.encode("utf-8"),
        _json(payload.model_dump(mode="json", exclude={"attestation_sha256"})).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return payload.model_copy(update={"attestation_sha256": signature})


def _verify_campaign_package_attestation(submission: CampaignPackageGateSubmission) -> None:
    if submission.attestation_key_id != settings.content_campaign_package_key_id:
        raise ValueError("A kampánycsomag-kapu ismeretlen attestation key azonosítót használ.")
    if len(settings.content_campaign_package_secret) < 32:
        raise ValueError("A kampánycsomag-kapu külön, legalább 32 karakteres secretje hiányzik.")
    expected = hmac.new(
        settings.content_campaign_package_secret.encode("utf-8"),
        _json(submission.model_dump(mode="json", exclude={"attestation_sha256"})).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, submission.attestation_sha256):
        raise ValueError("A kampánycsomag-kapu attestation aláírása érvénytelen.")


def _release_token(
    *,
    asset: ContentAssetRecord,
    bundle: PublicationBundleRecord,
    actor: str,
    proof_id: str,
    approved_at: datetime,
) -> dict[str, str]:
    if len(settings.imperial_release_hmac_key) < 32:
        raise ValueError("Az IMPERIAL_RELEASE_HMAC_KEY külön release-secretként kötelező.")
    payload = {
        "asset_id": asset.asset_id,
        "brand_id": asset.brand_id,
        "publication_proof_id": proof_id,
        "campaign_package_hash": str(asset.campaign_package_hash or ""),
        "artifact_set_sha256": str(asset.campaign_artifact_set_hash or ""),
        "publication_bundle_hash": bundle.bundle_hash,
        "human_reviewer_id": actor,
        "approved_at": approved_at.isoformat(),
        "r6_r7": "HUMAN_ONLY",
    }
    signature = hmac.new(
        settings.imperial_release_hmac_key.encode("utf-8"),
        _json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return payload | {"hmac_sha256": signature}


def _verify_release_token(token: dict[str, Any]) -> None:
    if len(settings.imperial_release_hmac_key) < 32:
        raise ValueError("Az IMPERIAL_RELEASE_HMAC_KEY hiányzik a secret-managementből.")
    signature = str(token.get("hmac_sha256") or "")
    unsigned = {key: value for key, value in token.items() if key != "hmac_sha256"}
    expected = hmac.new(
        settings.imperial_release_hmac_key.encode("utf-8"),
        _json(unsigned).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("A release-token HMAC aláírása érvénytelen.")


def build_human_editorial_review(
    asset: ContentAssetRecord,
    *,
    reviewer_identity: str,
    decision: str,
    scores: dict[str, int],
    consumer_interpretation: str,
    offer_interpretation: str,
    cta_interpretation: str,
    findings: list[str],
    required_repairs: list[str],
) -> EditorialReview:
    if asset.created_by.strip().lower() == reviewer_identity.strip().lower():
        raise ValueError("A négy szem elve miatt az asset létrehozója nem végezheti a Copy QA-t.")
    trace = json.loads(asset.generation_trace_json or "{}")
    score_fields = {
        "idiomatic_hungarian_score",
        "grammar_score",
        "semantic_clarity_score",
        "terminology_score",
        "hook_strength_score",
        "offer_clarity_score",
        "specificity_score",
        "persuasion_score",
        "brand_voice_score",
        "conversion_path_score",
    }
    if set(scores) != score_fields:
        raise ValueError("A Copy QA pontozási dimenziói hiányosak.")
    draft = EditorialReview(
        decision=Decision(decision),
        reviewed_asset_id=asset.asset_id,
        reviewed_content_sha256=asset.content_hash,
        reviewer_run_id=f"HUMAN-COPY-QA-{uuid.uuid4().hex[:12].upper()}",
        generation_run_id=str(trace.get("generation_run_id") or ""),
        reviewer_identity=reviewer_identity,
        reviewer_type="human_expert",
        attestation_key_id=settings.content_expert_review_key_id,
        attestation_sha256="0" * 64,
        model_version="authenticated-human-copy-expert-v1",
        prompt_version=EXPERT_REVIEW_PROMPT_VERSION,
        consumer_interpretation=consumer_interpretation,
        offer_interpretation=offer_interpretation,
        cta_interpretation=cta_interpretation,
        ambiguous_phrases=findings,
        unnatural_phrases=[],
        unsupported_claims=[],
        required_repairs=required_repairs,
        findings=[],
        **scores,
    )
    return _signed_submission(draft, settings.content_expert_review_secret)


def build_human_mandatory_gate_review(
    asset: ContentAssetRecord,
    *,
    gate_id: str,
    reviewer_identity: str,
    decision: str,
    dimension_scores: dict[str, int],
    consumer_readback: str,
    conversion_rationale: str,
    strongest_objection: str,
    dry_copy_detected: bool,
    generic_copy_detected: bool,
    brand_voice_violation_detected: bool,
    findings: list[str],
    required_repairs: list[str],
) -> MandatoryCopyGateReviewSubmission:
    if gate_id not in MANDATORY_COPY_GATE_DIMENSIONS:
        raise ValueError("Ismeretlen kötelező tartalomkapu.")
    if asset.created_by.strip().lower() == reviewer_identity.strip().lower():
        raise ValueError(
            "A négy szem elve miatt az asset létrehozója nem értékelheti a saját tartalmát."
        )
    trace = json.loads(asset.generation_trace_json or "{}")
    draft = MandatoryCopyGateReviewSubmission(
        gate_id=gate_id,
        decision=Decision(decision),
        reviewed_asset_id=asset.asset_id,
        reviewed_content_sha256=asset.content_hash,
        generation_run_id=str(trace.get("generation_run_id") or ""),
        reviewer_run_id=f"HUMAN-{gate_id}-{uuid.uuid4().hex[:12].upper()}",
        reviewer_identity=reviewer_identity,
        reviewer_model_version=f"authenticated-human-{gate_id.lower()}-v1",
        prompt_version=MANDATORY_COPY_GATE_PROMPT_VERSIONS[gate_id],
        attestation_key_id=(
            settings.content_marketing_review_key_id
            if gate_id == "MARKETING"
            else settings.content_copywriter_review_key_id
        ),
        attestation_sha256="0" * 64,
        dimension_scores=dimension_scores,
        consumer_readback=consumer_readback,
        conversion_rationale=conversion_rationale,
        strongest_objection=strongest_objection,
        dry_copy_detected=dry_copy_detected,
        generic_copy_detected=generic_copy_detected,
        brand_voice_violation_detected=brand_voice_violation_detected,
        findings=findings,
        required_repairs=required_repairs,
    )
    secret = (
        settings.content_marketing_review_secret
        if gate_id == "MARKETING"
        else settings.content_copywriter_review_secret
    )
    return _signed_submission(draft, secret)


def build_human_creative_director_review(
    asset: ContentAssetRecord,
    creative: CreativeProductionRunRecord,
    *,
    reviewer_identity: str,
    decision: str,
    review: dict[str, Any],
) -> CreativeDirectorReviewSubmission:
    if creative.producer_identity.strip().lower() == reviewer_identity.strip().lower():
        raise ValueError("A kreatív producer nem végezheti a saját munkája igazgatói review-ját.")
    draft = CreativeDirectorReviewSubmission(
        decision=Decision(decision),
        reviewed_asset_id=asset.asset_id,
        reviewed_content_sha256=asset.content_hash,
        reviewed_visual_sha256=creative.output_sha256,
        generation_run_id=creative.generation_run_id,
        reviewer_run_id=f"HUMAN-VISUAL-QA-{uuid.uuid4().hex[:12].upper()}",
        reviewer_identity=reviewer_identity,
        reviewer_model_version="authenticated-human-creative-director-v1",
        prompt_version=VISUAL_REVIEW_PROMPT_VERSION,
        attestation_key_id=settings.content_visual_review_key_id,
        attestation_sha256="0" * 64,
        **review,
    )
    return _signed_submission(draft, settings.content_visual_review_secret)


def _verify_expert_review_attestation(editorial_review: EditorialReview) -> None:
    secret = settings.content_expert_review_secret
    if len(secret) < 32:
        raise ValueError(
            "A szakértői review nem ellenőrizhető: a secret-managementből hiányzik "
            "a legalább 32 karakteres CONTENT_EXPERT_REVIEW_SECRET."
        )
    if editorial_review.attestation_key_id != settings.content_expert_review_key_id:
        raise ValueError(
            "A szakértői review ismeretlen vagy visszavont attestation-kulcsot használ."
        )
    if editorial_review.prompt_version != EXPERT_REVIEW_PROMPT_VERSION:
        raise ValueError(
            "A szakértői review nem a kötelező, verziózott magyar nyelvi és "
            "direct-response ellenőrzési protokollal készült."
        )
    signed_payload = editorial_review.model_dump(
        mode="json",
        exclude={"attestation_sha256"},
    )
    expected = hmac.new(
        secret.encode("utf-8"),
        _json(signed_payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, editorial_review.attestation_sha256):
        raise ValueError("Érvénytelen szakértői review-attestation; a COPY_QA blokkolva.")


def _verify_hmac_attestation(
    payload: Any,
    *,
    secret: str,
    expected_key_id: str,
    expected_prompt_version: str,
    gate_name: str,
) -> None:
    if len(secret) < 32:
        raise ValueError(
            f"A {gate_name} kapu nem ellenőrizhető: a secret-managementből hiányzik "
            "a legalább 32 karakteres, kapuspecifikus secret."
        )
    if payload.attestation_key_id != expected_key_id:
        raise ValueError(f"A {gate_name} kapu ismeretlen vagy visszavont kulcsot használ.")
    if payload.prompt_version != expected_prompt_version:
        raise ValueError(f"A {gate_name} kapu nem a kötelező, verziózott protokollt használja.")
    signed_payload = payload.model_dump(mode="json", exclude={"attestation_sha256"})
    expected = hmac.new(
        secret.encode("utf-8"),
        _json(signed_payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, payload.attestation_sha256):
        raise ValueError(f"Érvénytelen {gate_name} kapu-attestation; a folyamat blokkolva.")


def _verify_mandatory_copy_gate_attestation(
    submission: MandatoryCopyGateReviewSubmission,
) -> None:
    if submission.gate_id == "MARKETING":
        secret = settings.content_marketing_review_secret
        key_id = settings.content_marketing_review_key_id
    else:
        secret = settings.content_copywriter_review_secret
        key_id = settings.content_copywriter_review_key_id
    _verify_hmac_attestation(
        submission,
        secret=secret,
        expected_key_id=key_id,
        expected_prompt_version=MANDATORY_COPY_GATE_PROMPT_VERSIONS[submission.gate_id],
        gate_name=submission.gate_id,
    )


def _verify_visual_review_attestation(
    submission: CreativeDirectorReviewSubmission,
) -> None:
    _verify_hmac_attestation(
        submission,
        secret=settings.content_visual_review_secret,
        expected_key_id=settings.content_visual_review_key_id,
        expected_prompt_version=VISUAL_REVIEW_PROMPT_VERSION,
        gate_name="VISUAL",
    )


def validate_copy_brief(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        brief = CopyBrief.model_validate(payload)
    except ValidationError as exc:
        return {
            "valid": False,
            "decision": Decision.RETURN_FOR_REVISION,
            "error_ticket": {
                "code": "COPY_BRIEF_INCOMPLETE",
                "message": "Hiányos vagy érvénytelen CopyBriefből tartalom nem készülhet.",
                "errors": exc.errors(include_url=False),
                "repair_instruction": (
                    "Pótolja a felsorolt mezőket kanonikus forrásból; adat nem található ki."
                ),
            },
        }
    return {
        "valid": True,
        "decision": Decision.APPROVED,
        "brief": brief.model_dump(mode="json"),
    }


def register_copy_source(db: Session, source: CopySourceIn, *, actor: str) -> CopySourceRecord:
    existing = db.scalar(
        select(CopySourceRecord).where(
            CopySourceRecord.source_key == source.source_key,
            CopySourceRecord.version == source.version,
        )
    )
    if existing:
        raise ValueError("Ez a forráskulcs és verzió már regisztrálva van.")
    row = CopySourceRecord(
        source_key=source.source_key,
        source_type=source.source_type,
        brand_id=source.brand_id,
        page_id=source.page_id,
        campaign_id=source.campaign_id,
        asset_type=source.asset_type,
        version=source.version,
        priority=source.priority,
        status=source.status,
        approved=source.approved,
        valid_from=(
            datetime.combine(source.valid_from, time.min, tzinfo=UTC) if source.valid_from else None
        ),
        valid_until=(
            datetime.combine(source.valid_until, time.max, tzinfo=UTC)
            if source.valid_until
            else None
        ),
        source_url=source.source_url,
        content_hash=_hash(source.payload),
        payload_json=_json(source.payload),
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="copy_source_registered",
        entity_type="copy_source",
        entity_id=f"{source.source_key}@{source.version}",
        after=source.model_dump(mode="json") | {"content_hash": row.content_hash},
    )
    db.commit()
    db.refresh(row)
    return row


def review_copy_source(
    db: Session,
    source_id: int,
    decision: str,
    note: str,
    *,
    actor: str,
) -> CopySourceRecord:
    row = db.get(CopySourceRecord, source_id)
    if not row:
        raise KeyError(source_id)
    if decision not in {"approved", "retired"}:
        raise ValueError("A forrásdöntés csak approved vagy retired lehet.")
    if decision == "retired" and len(note.strip()) < 5:
        raise ValueError("A forrás visszavonásának indoklása kötelező.")
    before = {"status": row.status, "approved": row.approved}
    row.status = decision
    row.approved = decision == "approved"
    audit(
        db,
        actor=actor,
        action=f"copy_source_{decision}",
        entity_type="copy_source",
        entity_id=f"{row.source_key}@{row.version}",
        before=before,
        after={"status": row.status, "approved": row.approved, "note": note.strip()},
    )
    db.commit()
    db.refresh(row)
    return row


def _active(record: CopySourceRecord, now: datetime) -> bool:
    valid_from = (
        record.valid_from.replace(tzinfo=UTC)
        if record.valid_from and record.valid_from.tzinfo is None
        else record.valid_from
    )
    valid_until = (
        record.valid_until.replace(tzinfo=UTC)
        if record.valid_until and record.valid_until.tzinfo is None
        else record.valid_until
    )
    return (
        record.status == "approved"
        and record.approved
        and (valid_from is None or valid_from <= now)
        and (valid_until is None or valid_until >= now)
    )


def _scope_matches(record: CopySourceRecord, brief: CopyBrief) -> bool:
    return (
        record.brand_id == brief.brand_id
        and (record.page_id is None or record.page_id == brief.page_id)
        and (record.campaign_id is None or record.campaign_id == brief.campaign_id)
        and (record.asset_type is None or record.asset_type == brief.asset_type)
    )


def _payload(record: CopySourceRecord) -> dict[str, Any]:
    return json.loads(record.payload_json or "{}")


def resolve_canonical_sources(
    db: Session,
    brief: CopyBrief,
    *,
    visual_asset_ids: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[CanonicalSources, str]:
    now = now or utcnow()
    candidates = [
        record
        for record in db.scalars(
            select(CopySourceRecord)
            .where(CopySourceRecord.brand_id == brief.brand_id)
            .order_by(
                CopySourceRecord.source_type,
                CopySourceRecord.priority,
                CopySourceRecord.id.desc(),
            )
        ).all()
        if _scope_matches(record, brief) and _active(record, now)
    ]
    by_type: dict[str, list[CopySourceRecord]] = {}
    for record in candidates:
        by_type.setdefault(record.source_type, []).append(record)

    conflicts: list[str] = []
    selected: dict[str, CopySourceRecord] = {}
    for source_type in REQUIRED_SOURCE_TYPES:
        rows = by_type.get(source_type, [])
        if not rows:
            conflicts.append(f"MISSING:{source_type}")
            continue
        best_priority = min(row.priority for row in rows)
        winners = [row for row in rows if row.priority == best_priority]
        if len({row.content_hash for row in winners}) > 1:
            conflicts.append(f"CONFLICT:{source_type}")
            continue
        selected[source_type] = winners[0]

    identity_requirements = {
        "offer_version": brief.offer_version_id,
        "price_snapshot": brief.price_snapshot_id,
        "terms_version": brief.terms_version_id,
        "product": brief.product_id,
        "house_plan": brief.house_plan_id,
    }
    active_flags: dict[str, bool] = {}
    for source_type, expected_id in identity_requirements.items():
        if not expected_id:
            continue
        matches = [
            row
            for row in by_type.get(source_type, [])
            if _payload(row).get("record_id") == expected_id
        ]
        active_flags[source_type] = bool(matches)
        if not matches:
            conflicts.append(f"MISSING:{source_type}:{expected_id}")
        elif source_type not in selected:
            selected[source_type] = matches[0]

    claims: set[str] = set()
    for row in by_type.get("claim", []):
        record_id = _payload(row).get("record_id")
        if isinstance(record_id, str):
            claims.add(record_id)
    proofs: set[str] = set()
    for row in by_type.get("proof", []):
        record_id = _payload(row).get("record_id")
        if isinstance(record_id, str):
            proofs.add(record_id)
    conflicts.extend(f"MISSING:claim:{item}" for item in sorted(set(brief.claim_ids) - claims))
    conflicts.extend(f"MISSING:proof:{item}" for item in sorted(set(brief.proof_ids) - proofs))

    requested_visuals = set(visual_asset_ids or [])
    visuals: set[str] = set()
    for row in by_type.get("visual_rights", []):
        payload = _payload(row)
        record_id = payload.get("record_id")
        if isinstance(record_id, str) and payload.get("rights_status") == "approved":
            visuals.add(record_id)
    conflicts.extend(
        f"MISSING:visual_rights:{item}" for item in sorted(requested_visuals - visuals)
    )

    profile = _payload(selected["brand_voice_profile"]) if "brand_voice_profile" in selected else {}
    source_versions = {
        source_type: f"{record.source_key}@{record.version}#{record.content_hash[:12]}"
        for source_type, record in selected.items()
    }
    snapshot_hash = _hash(source_versions)
    return (
        CanonicalSources(
            source_resolution_pass=not conflicts,
            source_versions=source_versions,
            source_conflicts=conflicts,
            active_offer=active_flags.get("offer_version", False),
            active_price=active_flags.get("price_snapshot", False),
            active_terms=active_flags.get("terms_version", False),
            active_product=active_flags.get("product", active_flags.get("house_plan", False)),
            claims_resolved=sorted(claims),
            proofs_resolved=sorted(proofs),
            visuals_resolved=sorted(visuals),
            brand_addressing=profile.get("addressing", "formal"),
            required_brand_concepts=profile.get("required_concepts", []),
            forbidden_brand_phrases=profile.get("forbidden_phrases", []),
        ),
        snapshot_hash,
    )


def _enrich_monthly_promotion_sources(
    sources: CanonicalSources,
    brief: CopyBrief,
    *,
    evaluated_on: date,
) -> tuple[CanonicalSources, str]:
    requirement = resolve_monthly_promotion(brief.brand_id, on_date=evaluated_on)
    source_versions = dict(sources.source_versions)
    source_versions["monthly_promotion"] = (
        f"{requirement.promotion_id or 'none'}@{evaluated_on.isoformat()}"
        f"#{requirement.status.value}"
    )
    enriched = sources.model_copy(
        update={
            "source_versions": source_versions,
            "monthly_promotion_id": requirement.promotion_id,
            "monthly_promotion_copy_required": requirement.copy_required,
            "monthly_promotion_publication_allowed": requirement.publication_allowed,
        }
    )
    return enriched, _hash(source_versions)


def _monthly_promotion_snapshot_date(run: CopyReviewRun) -> date | None:
    source_versions = json.loads(run.source_versions_json or "{}")
    version = source_versions.get("monthly_promotion")
    if not isinstance(version, str) or "@" not in version or "#" not in version:
        return None
    raw_date = version.split("@", 1)[1].split("#", 1)[0]
    try:
        return date.fromisoformat(raw_date)
    except ValueError:
        return None


def create_copy_brief(db: Session, payload: dict[str, Any], *, actor: str) -> CopyBriefRecord:
    validation = validate_copy_brief(payload)
    if not validation["valid"]:
        raise ValueError(_json(validation["error_ticket"]))
    brief = CopyBrief.model_validate(payload)
    if db.get(CopyBriefRecord, brief.copy_brief_id):
        raise ValueError("A CopyBriefID már létezik.")
    sources, snapshot_hash = resolve_canonical_sources(db, brief)
    if not sources.source_resolution_pass:
        raise ValueError(
            f"Kanonikus forrásfeloldás sikertelen: {', '.join(sources.source_conflicts)}"
        )
    row = CopyBriefRecord(
        copy_brief_id=brief.copy_brief_id,
        brand_id=brief.brand_id,
        asset_type=brief.asset_type,
        channel=brief.channel,
        page_id=brief.page_id,
        campaign_id=brief.campaign_id,
        status="STRATEGY_QA",
        valid_from=datetime.combine(brief.valid_from, time.min, tzinfo=UTC),
        valid_until=datetime.combine(brief.valid_until, time.max, tzinfo=UTC),
        brief_json=_json(brief),
        source_snapshot_hash=snapshot_hash,
        created_by=actor,
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="copy_brief_created",
        entity_type="copy_brief",
        entity_id=row.copy_brief_id,
        after={
            "brief": brief.model_dump(mode="json"),
            "source_snapshot_hash": snapshot_hash,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def record_strategy_review(
    db: Session,
    copy_brief_id: str,
    submission: StrategyReviewSubmission,
    *,
    actor: str,
) -> CampaignStrategyReviewRecord:
    if actor != submission.reviewer_identity:
        raise ValueError("A stratégiai reviewer_identity az autentikált actor kell legyen.")
    brief_row = db.get(CopyBriefRecord, copy_brief_id)
    if not brief_row:
        raise KeyError(copy_brief_id)
    if brief_row.status != "STRATEGY_QA":
        raise ValueError(
            f"Stratégiai review nem rögzíthető ebből az állapotból: {brief_row.status}"
        )
    if brief_row.created_by.strip().lower() == actor.strip().lower():
        raise ValueError(
            "A négy szem elve miatt a brief létrehozója nem végezheti a stratégiai jóváhagyást."
        )
    if db.scalar(
        select(CampaignStrategyReviewRecord).where(
            CampaignStrategyReviewRecord.copy_brief_id == copy_brief_id
        )
    ):
        raise ValueError("Ehhez a CopyBriefhez már tartozik stratégiai review.")
    brief_hash = _hash(json.loads(brief_row.brief_json))
    row = CampaignStrategyReviewRecord(
        review_id=f"STR-{uuid.uuid4().hex[:16].upper()}",
        copy_brief_id=copy_brief_id,
        brief_hash=brief_hash,
        strategist_run_id=submission.strategist_run_id,
        reviewer_run_id=submission.reviewer_run_id,
        reviewer_identity=submission.reviewer_identity,
        decision=submission.decision,
        review_json=_json(submission),
        created_by=actor,
    )
    db.add(row)
    brief_row.status = (
        "STRATEGY_APPROVED" if submission.decision == Decision.APPROVED else "STRATEGY_BLOCKED"
    )
    audit(
        db,
        actor=actor,
        action="campaign_strategy_reviewed",
        entity_type="copy_brief",
        entity_id=copy_brief_id,
        after={
            "review_id": row.review_id,
            "brief_hash": brief_hash,
            "decision": submission.decision,
            "state": brief_row.status,
            "reviewer_identity": submission.reviewer_identity,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def create_content_asset(
    db: Session,
    payload: ContentAsset,
    *,
    copy_brief_id: str,
    project_id: str | None,
    generation_trace: dict[str, Any],
    actor: str,
) -> ContentAssetRecord:
    brief_row = db.get(CopyBriefRecord, copy_brief_id)
    if not brief_row or brief_row.status != "STRATEGY_APPROVED":
        raise ValueError(
            "Csak külön stratégiai kapun jóváhagyott CopyBriefhez hozható létre asset."
        )
    strategy_review = db.scalar(
        select(CampaignStrategyReviewRecord).where(
            CampaignStrategyReviewRecord.copy_brief_id == copy_brief_id,
            CampaignStrategyReviewRecord.decision == Decision.APPROVED,
        )
    )
    if not strategy_review or strategy_review.brief_hash != _hash(json.loads(brief_row.brief_json)):
        raise ValueError("Hiányzik az aktuális briefhashhez tartozó stratégiai GateResult.")
    if db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == payload.asset_id)):
        raise ValueError("Az AssetID már létezik.")
    if generation_trace.get("stages", []) != list(GENERATION_STAGES):
        raise ValueError("A kilenc kötelező generálási/szerkesztési szakasz sorrendje hiányos.")
    if not generation_trace.get("generation_run_id"):
        raise ValueError("A generation_run_id kötelező.")
    if generation_trace.get("brand_id") != brief_row.brand_id:
        raise ValueError("A generation_trace brand_id mezője nem egyezik a CopyBrieffel.")
    sibling_traces: list[dict[str, Any]] = []
    sibling_query = select(ContentAssetRecord)
    if brief_row.campaign_id:
        sibling_query = sibling_query.join(
            CopyBriefRecord,
            CopyBriefRecord.copy_brief_id == ContentAssetRecord.copy_brief_id,
        ).where(CopyBriefRecord.campaign_id == brief_row.campaign_id)
    else:
        sibling_query = sibling_query.where(ContentAssetRecord.copy_brief_id == copy_brief_id)
    sibling_rows = db.scalars(sibling_query).all()
    for sibling in sibling_rows:
        try:
            sibling_traces.append(json.loads(sibling.generation_trace_json or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("Sérült korábbi generation_trace_json.") from exc
    validate_copy_variation_trace(generation_trace, sibling_traces=sibling_traces)
    validate_visual_variant_trace(generation_trace, sibling_traces=sibling_traces)
    brief = CopyBrief.model_validate_json(brief_row.brief_json)
    if payload.detected_brand_ids != [brief.brand_id]:
        raise ValueError("Az asset márkaazonosítója nem egyezik a CopyBrieffel.")
    row = ContentAssetRecord(
        asset_id=payload.asset_id,
        copy_brief_id=copy_brief_id,
        project_id=project_id,
        brand_id=brief.brand_id,
        asset_type=brief.asset_type,
        channel=brief.channel,
        state=PublicationState.DRAFT,
        content_hash=_hash(payload),
        content_json=_json(payload),
        generation_trace_json=_json(generation_trace),
        created_by=actor,
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="content_asset_created",
        entity_type="content_asset",
        entity_id=row.asset_id,
        after={
            "state": row.state,
            "content_hash": row.content_hash,
            "generation_trace": generation_trace,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def run_copy_quality(
    db: Session,
    asset_id: str,
    editorial_review: EditorialReview,
    *,
    actor: str,
    evaluated_on: date | None = None,
) -> CopyReviewRun:
    asset_row = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset_row:
        raise KeyError(asset_id)
    if asset_row.state not in {
        PublicationState.DRAFT,
        PublicationState.BLOCKED,
        PublicationState.COPY_QA,
    }:
        raise ValueError(f"COPY_QA nem indítható ebből az állapotból: {asset_row.state}")
    brief_row = db.get(CopyBriefRecord, asset_row.copy_brief_id)
    if not brief_row:
        raise ValueError("A CopyBrief rekord hiányzik.")
    brief = CopyBrief.model_validate_json(brief_row.brief_json)
    content = ContentAsset.model_validate_json(asset_row.content_json)
    review_date = evaluated_on or utcnow().date()
    sources, snapshot_hash = resolve_canonical_sources(
        db, brief, visual_asset_ids=content.visual_asset_ids
    )
    sources, snapshot_hash = _enrich_monthly_promotion_sources(
        sources,
        brief,
        evaluated_on=review_date,
    )
    generation_trace = json.loads(asset_row.generation_trace_json or "{}")
    if editorial_review.generation_run_id != generation_trace.get("generation_run_id"):
        raise ValueError(
            "A szakértői jegyzőkönyv generation_run_id mezője nem az aktuális "
            "generálási futáshoz tartozik."
        )
    if editorial_review.model_version == generation_trace.get("model_version"):
        raise ValueError("A generáló és a szakértői ellenőrző modell nem lehet azonos.")
    if editorial_review.reviewed_asset_id != asset_row.asset_id:
        raise ValueError("A szakértői jegyzőkönyv másik assethez tartozik.")
    if editorial_review.reviewed_content_sha256 != asset_row.content_hash:
        raise ValueError("A szakértői jegyzőkönyv nem az aktuális tartalomhashhez tartozik.")
    _verify_expert_review_attestation(editorial_review)
    asset_row.state = PublicationState.COPY_QA
    result = evaluate_content(
        ContentEvaluationRequest(
            brief=brief,
            sources=sources,
            asset=content,
            editorial_review=editorial_review,
            evaluated_on=review_date,
        )
    )
    run_id = f"CQR-{uuid.uuid4().hex[:16].upper()}"
    expert_review_json = _json(editorial_review)
    run = CopyReviewRun(
        run_id=run_id,
        asset_id=asset_id,
        copy_brief_id=asset_row.copy_brief_id,
        content_hash=asset_row.content_hash,
        source_snapshot_hash=snapshot_hash,
        source_versions_json=_json(sources.source_versions),
        model_versions_json=_json(
            {
                "generator": generation_trace.get("model_version"),
                "editorial": editorial_review.model_version,
            }
        ),
        prompt_versions_json=_json(
            {
                "generator": generation_trace.get("prompt_version"),
                "editorial": editorial_review.prompt_version,
            }
        ),
        total_score=result.total_score,
        final_decision=result.final_decision,
        scorecard_json=_json(result),
        expert_review_json=expert_review_json,
        expert_review_hash=_hash(editorial_review),
        repair_brief_json=_json(result.repair_brief),
        created_by=actor,
    )
    db.add(run)
    # Persist the parent review row before inserting gate decisions. PostgreSQL
    # enforces the FK immediately and SQLAlchemy cannot infer the dependency
    # without an ORM relationship between these two record types.
    db.flush()
    db.add(
        ContentGateDecision(
            run_id=run_id,
            asset_id=asset_id,
            gate_id=result.gate_1.gate_id,
            agent_id=result.gate_1.agent_id,
            decision=result.gate_1.decision,
            relevant=True,
            certainty=result.gate_1.certainty,
            findings_json=_json(result.gate_1.findings),
            source_versions_json=_json(result.gate_1.source_versions),
        )
    )
    for gate_id, agent_id, approved in (
        (
            "GATE_HU_LANGUAGE_EXPERT",
            "AGT-HU-LANGUAGE-EXPERT",
            bool(result.metadata["expert_language_approved"]),
        ),
    ):
        db.add(
            ContentGateDecision(
                run_id=run_id,
                asset_id=asset_id,
                gate_id=gate_id,
                agent_id=agent_id,
                decision=Decision.APPROVED if approved else Decision.RETURN_FOR_REVISION,
                relevant=True,
                certainty="HIGH",
                findings_json=_json(
                    []
                    if approved
                    else [
                        {
                            "code": f"{gate_id}_FAILED",
                            "message": "A kötelező szakértői minimum nem teljesült.",
                            "severity": "CRITICAL",
                        }
                    ]
                ),
                source_versions_json=_json(
                    {
                        "review_model": editorial_review.model_version,
                        "review_prompt": editorial_review.prompt_version,
                        "review_hash": _hash(editorial_review),
                    }
                ),
            )
        )
    asset_row.latest_run_id = run_id
    asset_row.gate_1_approved = result.final_decision == Decision.APPROVED
    asset_row.expert_language_approved = bool(result.metadata["expert_language_approved"])
    asset_row.expert_marketing_approved = False
    asset_row.copywriter_approved = False
    asset_row.four_gate_approved = False
    asset_row.editorial_approved = False
    asset_row.owner_approved = False
    asset_row.state = (
        PublicationState.SPECIALIST_QA
        if result.final_decision == Decision.APPROVED
        else PublicationState.BLOCKED
    )
    audit(
        db,
        actor=actor,
        action="copy_quality_evaluated",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "run_id": run_id,
            "score": result.total_score,
            "decision": result.final_decision,
            "state": asset_row.state,
            "expert_review_hash": run.expert_review_hash,
            "expert_reviewer_identity": editorial_review.reviewer_identity,
            "expert_language_approved": asset_row.expert_language_approved,
            "expert_marketing_approved": False,
            "copywriter_approved": False,
        },
    )
    db.commit()
    db.refresh(run)
    return run


def _create_human_gate_task(
    db: Session,
    asset: ContentAssetRecord,
    gate: GateResult,
    *,
    actor: str,
) -> None:
    task_id = f"TASK-CQ-{uuid.uuid4().hex[:12].upper()}"
    db.add(
        TaskRecord(
            task_id=task_id,
            project_id=asset.project_id or "CONTENT-QUALITY",
            title=f"Emberi döntés szükséges: {gate.gate_id} / {asset.asset_id}",
            description=_json([finding.model_dump(mode="json") for finding in gate.findings]),
            assignee=gate.agent_id,
            priority="critical",
            status="open",
            executive_relevance=True,
        )
    )
    db.add(
        OutboxMessage(
            message_id=f"MSG-CQ-{uuid.uuid4().hex[:12].upper()}",
            destination_module="email-notification",
            endpoint=None,
            payload_json=_json(
                {
                    "template": "content_gate_human_approval",
                    "task_id": task_id,
                    "asset_id": asset.asset_id,
                    "gate_id": gate.gate_id,
                    "agent_id": gate.agent_id,
                }
            ),
            status="pending",
            next_attempt_at=utcnow(),
        )
    )
    audit(
        db,
        actor=actor,
        action="content_gate_human_task_created",
        entity_type="task",
        entity_id=task_id,
        after={"asset_id": asset.asset_id, "gate_id": gate.gate_id},
    )


def record_mandatory_copy_gate_review(
    db: Session,
    asset_id: str,
    submission: MandatoryCopyGateReviewSubmission,
    *,
    actor: str,
) -> ContentWorkflowReviewRecord:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.SPECIALIST_QA:
        raise ValueError(
            "Kötelező marketing/copywriter review nem rögzíthető ebből az állapotból: "
            f"{asset.state}"
        )
    generation_trace = json.loads(asset.generation_trace_json or "{}")
    if submission.reviewed_asset_id != asset.asset_id:
        raise ValueError("A kötelező kapujegyzőkönyv másik assethez tartozik.")
    if submission.reviewed_content_sha256 != asset.content_hash:
        raise ValueError("A kötelező kapujegyzőkönyv nem az aktuális tartalomhashhez tartozik.")
    if submission.generation_run_id != generation_trace.get("generation_run_id"):
        raise ValueError("A kötelező kapujegyzőkönyv másik generálási futáshoz tartozik.")
    if submission.reviewer_model_version == generation_trace.get("model_version"):
        raise ValueError("A generáló és a kötelező szakértői reviewer modell nem lehet azonos.")
    _verify_mandatory_copy_gate_attestation(submission)

    stage = f"{submission.gate_id}_QA"
    existing_same_gate = db.scalar(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage == stage,
        )
    )
    if existing_same_gate:
        raise ValueError("Ehhez a tartalomverzióhoz ez a kötelező kapu már döntött.")
    other_stage = "DIRECT_RESPONSE_QA" if submission.gate_id == "MARKETING" else "MARKETING_QA"
    other_review = db.scalar(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage == other_stage,
            ContentWorkflowReviewRecord.decision == Decision.APPROVED,
        )
    )
    if other_review:
        other_payload = MandatoryCopyGateReviewSubmission.model_validate_json(
            other_review.review_json
        )
        if (
            other_payload.reviewer_identity == submission.reviewer_identity
            or other_payload.reviewer_run_id == submission.reviewer_run_id
            or other_payload.reviewer_model_version == submission.reviewer_model_version
        ):
            raise ValueError(
                "A marketing- és direct-response kaput külön reviewer entitásnak, "
                "külön modellnek és külön futásnak kell elvégeznie."
            )

    row = ContentWorkflowReviewRecord(
        review_id=f"{submission.gate_id[:3]}-{uuid.uuid4().hex[:16].upper()}",
        asset_id=asset_id,
        content_version=asset.content_version,
        stage=stage,
        reviewer_role=(
            "ONLINE_MARKETING_MANAGER"
            if submission.gate_id == "MARKETING"
            else "DIRECT_RESPONSE_COPYWRITER"
        ),
        reviewer_identity=submission.reviewer_identity,
        reviewer_run_id=submission.reviewer_run_id,
        decision=submission.decision,
        artifact_hash=asset.content_hash,
        review_json=_json(submission),
        created_by=actor,
    )
    db.add(row)
    approved = submission.decision == Decision.APPROVED
    if submission.gate_id == "MARKETING":
        asset.expert_marketing_approved = approved
    else:
        asset.copywriter_approved = approved
    if not approved:
        asset.state = PublicationState.BLOCKED
    elif asset.expert_marketing_approved and asset.copywriter_approved:
        asset.state = PublicationState.FOUR_GATE_QA
    audit(
        db,
        actor=actor,
        action="mandatory_copy_gate_reviewed",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "review_id": row.review_id,
            "gate_id": submission.gate_id,
            "reviewer_identity": submission.reviewer_identity,
            "reviewer_run_id": submission.reviewer_run_id,
            "reviewed_content_sha256": submission.reviewed_content_sha256,
            "decision": submission.decision,
            "state": asset.state,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def submit_four_gates(
    db: Session,
    asset_id: str,
    submission: FourGateSubmission,
    *,
    actor: str,
) -> dict[str, Any]:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if (
        asset.state != PublicationState.FOUR_GATE_QA
        or not asset.gate_1_approved
        or not asset.expert_language_approved
        or not asset.expert_marketing_approved
        or not asset.copywriter_approved
        or not asset.latest_run_id
    ):
        raise ValueError("A négykapus review csak sikeres COPY_QA után indítható.")
    run = db.get(CopyReviewRun, asset.latest_run_id)
    content = ContentAsset.model_validate_json(asset.content_json)
    prevalidation = evaluate_commercial_prevalidation(asset.brand_id, content)
    generation_trace = json.loads(asset.generation_trace_json or "{}")
    copy_fast_lane_allowed = copy_mode_allows_source_prevalidation(generation_trace)
    supplied = {result.gate_id: result for result in submission.specialist_results}
    results: list[GateResult] = []
    routing = {
        "GATE_2_LEGAL_POLICY": submission.legal_relevant,
        "GATE_3_FINANCIAL_COMMERCIAL": submission.financial_relevant,
        "GATE_4_TECHNICAL_FACTUAL": submission.technical_relevant,
    }
    for gate_id, relevant in routing.items():
        expected_agent = SPECIALIST_GATE_AGENTS[gate_id]
        submitted = supplied.get(gate_id)
        if not relevant:
            result = GateResult(
                gate_id=gate_id,
                agent_id=expected_agent,
                decision=Decision.SKIPPED_NOT_RELEVANT,
                relevance=False,
                certainty="HIGH",
            )
        elif (
            not submitted
            and prevalidation.eligible
            and copy_fast_lane_allowed
            and prevalidation.gate_coverage[gate_id]
        ):
            result = GateResult(
                gate_id=gate_id,
                agent_id=expected_agent,
                decision=Decision.APPROVED,
                relevance=True,
                certainty="HIGH",
                source_versions={
                    "commercial_prevalidation": (
                        f"{prevalidation.registry_version}#{prevalidation.registry_sha256[:12]}"
                    )
                },
            )
        elif not submitted:
            result = GateResult(
                gate_id=gate_id,
                agent_id=expected_agent,
                decision=Decision.HUMAN_APPROVAL_REQUIRED,
                relevance=True,
                certainty="LOW",
            )
        else:
            if submitted.agent_id != expected_agent:
                raise ValueError(f"{gate_id} kötelező AgentID-je: {expected_agent}.")
            if submitted.decision == Decision.SKIPPED_NOT_RELEVANT:
                raise ValueError("Releváns specialistakapu nem adhat SKIPPED_NOT_RELEVANT döntést.")
            result = GateResult(
                gate_id=gate_id,
                agent_id=submitted.agent_id,
                decision=submitted.decision,
                relevance=True,
                certainty=submitted.certainty,
                findings=submitted.findings,
                source_versions=submitted.source_versions,
            )
        results.append(result)
        existing = db.scalar(
            select(ContentGateDecision).where(
                ContentGateDecision.run_id == asset.latest_run_id,
                ContentGateDecision.gate_id == gate_id,
            )
        )
        if existing:
            db.delete(existing)
            db.flush()
        db.add(
            ContentGateDecision(
                run_id=asset.latest_run_id,
                asset_id=asset_id,
                gate_id=gate_id,
                agent_id=result.agent_id,
                decision=result.decision,
                relevant=result.relevance,
                certainty=result.certainty,
                findings_json=_json(result.findings),
                source_versions_json=_json(result.source_versions),
            )
        )

    decisions = {result.decision for result in results}
    asset.source_prevalidated = False
    if Decision.RETURN_FOR_REVISION in decisions:
        final = Decision.RETURN_FOR_REVISION
        asset.state = PublicationState.BLOCKED
    elif Decision.HUMAN_APPROVAL_REQUIRED in decisions:
        final = Decision.HUMAN_APPROVAL_REQUIRED
        asset.state = PublicationState.FOUR_GATE_QA
        for result in results:
            if result.decision == Decision.HUMAN_APPROVAL_REQUIRED:
                _create_human_gate_task(db, asset, result, actor=actor)
    else:
        final = Decision.APPROVED
        asset.four_gate_approved = True
        asset.source_prevalidated = prevalidation.eligible and copy_fast_lane_allowed
        asset.state = (
            PublicationState.VISUAL_PRODUCTION
            if asset.source_prevalidated
            else PublicationState.HUMAN_EDITORIAL
        )
    if run:
        run.final_decision = final
    audit(
        db,
        actor=actor,
        action="four_gate_review_completed",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "decision": final,
            "state": asset.state,
            "gates": [result.model_dump(mode="json") for result in results],
            "commercial_prevalidation": {
                "eligible": prevalidation.eligible,
                "copy_fast_lane_allowed": copy_fast_lane_allowed,
                "registry_version": prevalidation.registry_version,
                "registry_sha256": prevalidation.registry_sha256,
                "verified_evidence_ids": prevalidation.verified_evidence_ids,
                "findings": prevalidation.findings,
            },
        },
    )
    db.commit()
    return {
        "asset_id": asset_id,
        "run_id": asset.latest_run_id,
        "decision": final,
        "state": asset.state,
        "gates": [result.model_dump(mode="json") for result in results],
        "commercial_prevalidation": {
            "eligible": prevalidation.eligible,
            "registry_version": prevalidation.registry_version,
            "verified_evidence_ids": prevalidation.verified_evidence_ids,
            "findings": prevalidation.findings,
        },
    }


def review_human_specialist_gate(
    db: Session,
    asset_id: str,
    gate_id: str,
    decision: str,
    relevant: bool,
    evidence: str,
    *,
    actor: str,
) -> dict[str, Any]:
    if gate_id not in SPECIALIST_GATE_AGENTS:
        raise ValueError("Ismeretlen specialistakapu.")
    if decision not in {
        Decision.APPROVED,
        Decision.RETURN_FOR_REVISION,
        Decision.SKIPPED_NOT_RELEVANT,
    }:
        raise ValueError("Érvénytelen specialistadöntés.")
    if relevant and decision == Decision.SKIPPED_NOT_RELEVANT:
        raise ValueError("Releváns specialistakapu nem hagyható ki.")
    if not relevant and decision != Decision.SKIPPED_NOT_RELEVANT:
        raise ValueError("Nem releváns kapuhoz SKIPPED_NOT_RELEVANT döntés szükséges.")
    if len(evidence.strip()) < 10:
        raise ValueError("A specialistadöntés bizonyítéka legalább 10 karakter legyen.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.FOUR_GATE_QA or not asset.latest_run_id:
        raise ValueError(f"Specialistakapu nem értékelhető ebből az állapotból: {asset.state}")
    if asset.created_by.strip().lower() == actor.strip().lower():
        raise ValueError("A tartalom létrehozója nem értékelheti a saját specialistakapuját.")
    existing = db.scalar(
        select(ContentGateDecision).where(
            ContentGateDecision.run_id == asset.latest_run_id,
            ContentGateDecision.gate_id == gate_id,
        )
    )
    if existing and existing.decision != Decision.HUMAN_APPROVAL_REQUIRED:
        raise ValueError("Ez a specialistakapu már végleges döntést rögzített.")
    if existing:
        db.delete(existing)
        db.flush()
    other_rows = list(
        db.scalars(
            select(ContentGateDecision).where(
                ContentGateDecision.run_id == asset.latest_run_id,
                ContentGateDecision.gate_id.in_(tuple(SPECIALIST_GATE_AGENTS)),
                ContentGateDecision.gate_id != gate_id,
            )
        )
    )
    for other in other_rows:
        try:
            other_evidence = json.loads(other.source_versions_json or "{}")
        except json.JSONDecodeError:
            other_evidence = {}
        if str(other_evidence.get("reviewer") or "").strip().lower() == actor.strip().lower():
            raise ValueError(
                "A jogi, pénzügyi és műszaki specialistakaput három külön "
                "felhasználónak kell értékelnie."
            )
    db.add(
        ContentGateDecision(
            run_id=asset.latest_run_id,
            asset_id=asset_id,
            gate_id=gate_id,
            agent_id=SPECIALIST_GATE_AGENTS[gate_id],
            decision=decision,
            relevant=relevant,
            certainty="HIGH",
            findings_json=_json(
                [] if decision != Decision.RETURN_FOR_REVISION else [evidence.strip()]
            ),
            source_versions_json=_json({"human_evidence": evidence.strip(), "reviewer": actor}),
        )
    )
    db.flush()
    rows = list(
        db.scalars(
            select(ContentGateDecision).where(
                ContentGateDecision.run_id == asset.latest_run_id,
                ContentGateDecision.gate_id.in_(tuple(SPECIALIST_GATE_AGENTS)),
            )
        )
    )
    decisions = {row.gate_id: row.decision for row in rows}
    if Decision.RETURN_FOR_REVISION in decisions.values():
        asset.state = PublicationState.BLOCKED
        asset.four_gate_approved = False
        final = Decision.RETURN_FOR_REVISION
    elif set(decisions) == set(SPECIALIST_GATE_AGENTS) and all(
        value in {Decision.APPROVED, Decision.SKIPPED_NOT_RELEVANT} for value in decisions.values()
    ):
        asset.state = PublicationState.HUMAN_EDITORIAL
        asset.four_gate_approved = True
        asset.source_prevalidated = False
        final = Decision.APPROVED
    else:
        final = Decision.HUMAN_APPROVAL_REQUIRED
    run = db.get(CopyReviewRun, asset.latest_run_id)
    if run:
        run.final_decision = final
    audit(
        db,
        actor=actor,
        action="human_specialist_gate_reviewed",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "gate_id": gate_id,
            "decision": decision,
            "relevant": relevant,
            "evidence": evidence.strip(),
            "state": asset.state,
        },
    )
    db.commit()
    return {"asset_id": asset_id, "gate_id": gate_id, "decision": decision, "state": asset.state}


def record_approval(
    db: Session,
    asset_id: str,
    approval_type: str,
    submission: ApprovalSubmission,
    *,
    actor: str,
) -> ContentAssetRecord:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    expected_state = {
        "HUMAN_EDITORIAL": PublicationState.HUMAN_EDITORIAL,
        "OWNER": PublicationState.OWNER_APPROVAL,
    }.get(approval_type)
    if expected_state is None or asset.state != expected_state:
        raise ValueError(
            f"{approval_type} jóváhagyás nem rögzíthető ebből az állapotból: {asset.state}"
        )
    if approval_type == "OWNER":
        editorial = db.scalar(
            select(ContentApprovalRecord).where(
                ContentApprovalRecord.asset_id == asset_id,
                ContentApprovalRecord.content_version == asset.content_version,
                ContentApprovalRecord.approval_type == "HUMAN_EDITORIAL",
                ContentApprovalRecord.decision == "APPROVED",
            )
        )
        if not editorial:
            raise ValueError("Tulajdonosi döntés előtt jóváhagyott szerkesztői döntés szükséges.")
        if editorial.actor.strip().lower() == actor.strip().lower():
            raise ValueError(
                "A szerkesztői és tulajdonosi döntést két külön felhasználónak kell elvégeznie."
            )
    existing = db.scalar(
        select(ContentApprovalRecord).where(
            ContentApprovalRecord.asset_id == asset_id,
            ContentApprovalRecord.content_version == asset.content_version,
            ContentApprovalRecord.approval_type == approval_type,
        )
    )
    if existing:
        raise ValueError("Ehhez a tartalomverzióhoz ez a jóváhagyás már rögzítve van.")
    db.add(
        ContentApprovalRecord(
            asset_id=asset_id,
            content_version=asset.content_version,
            approval_type=approval_type,
            decision=submission.decision,
            actor=actor,
            note=submission.note,
            content_hash=asset.content_hash,
        )
    )
    approved = submission.decision == "APPROVED"
    if approval_type == "HUMAN_EDITORIAL":
        asset.editorial_approved = approved
        asset.state = PublicationState.OWNER_APPROVAL if approved else PublicationState.BLOCKED
    else:
        asset.owner_approved = approved
        asset.state = PublicationState.VISUAL_PRODUCTION if approved else PublicationState.BLOCKED
    audit(
        db,
        actor=actor,
        action=f"content_{approval_type.lower()}_decision",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "decision": submission.decision,
            "content_hash": asset.content_hash,
            "state": asset.state,
        },
    )
    db.commit()
    db.refresh(asset)
    return asset


def submit_visual_production(
    db: Session,
    asset_id: str,
    submission: VisualProductionSubmission,
    *,
    actor: str,
) -> CreativeProductionRunRecord:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.VISUAL_PRODUCTION:
        raise ValueError(f"Vizuális gyártás nem indítható ebből az állapotból: {asset.state}")
    generation_trace = json.loads(asset.generation_trace_json or "{}")
    if submission.generation_run_id == generation_trace.get("generation_run_id"):
        raise ValueError("A copy- és vizuális generálási futás nem lehet azonos.")
    if submission.contains_text:
        raise ValueError(
            "A vizuális alap nem tartalmazhat ráégetett kampányszöveget; "
            "a szöveg az assembly szakaszban kerül rá."
        )
    existing_runs = db.scalars(
        select(CreativeProductionRunRecord)
        .where(
            CreativeProductionRunRecord.asset_id == asset_id,
            CreativeProductionRunRecord.content_version == asset.content_version,
        )
        .order_by(CreativeProductionRunRecord.sequence_number)
    ).all()
    if any(run.status == "DIRECTOR_QA" for run in existing_runs):
        raise ValueError("Egyszerre csak egy kreatív lehet aktív kreatív igazgatói review alatt.")
    if any(run.output_sha256 == submission.output_sha256 for run in existing_runs):
        raise ValueError("A vizuális output nem ismételhet korábbi kreatívot.")
    if any(run.visual_direction_id == submission.visual_direction_id for run in existing_runs):
        raise ValueError("Az újragenerálásnak külön visual_direction_id szükséges.")
    row = CreativeProductionRunRecord(
        generation_run_id=submission.generation_run_id,
        asset_id=asset_id,
        content_version=asset.content_version,
        sequence_number=len(existing_runs) + 1,
        producer_identity=submission.producer_identity,
        visual_direction_id=submission.visual_direction_id,
        platform=submission.platform,
        width_px=submission.width_px,
        height_px=submission.height_px,
        output_uri=submission.output_uri,
        output_sha256=submission.output_sha256,
        generation_prompt_hash=submission.generation_prompt_hash,
        contains_text=False,
        status="DIRECTOR_QA",
        created_by=actor,
    )
    db.add(row)
    asset.state = PublicationState.CREATIVE_DIRECTOR_QA
    asset.creative_director_approved = False
    asset.assembly_approved = False
    asset.campaign_package_approved = False
    asset.campaign_package_hash = None
    asset.campaign_artifact_set_hash = None
    asset.release_approved = False
    asset.live_review_approved = False
    audit(
        db,
        actor=actor,
        action="visual_production_completed",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "generation_run_id": row.generation_run_id,
            "sequence_number": row.sequence_number,
            "output_sha256": row.output_sha256,
            "state": asset.state,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def record_creative_director_review(
    db: Session,
    asset_id: str,
    submission: CreativeDirectorReviewSubmission,
    *,
    actor: str,
) -> ContentWorkflowReviewRecord:
    if actor != submission.reviewer_identity:
        raise ValueError("A kreatív reviewer_identity az autentikált actor kell legyen.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.CREATIVE_DIRECTOR_QA:
        raise ValueError(
            f"Kreatív igazgatói review nem rögzíthető ebből az állapotból: {asset.state}"
        )
    creative = db.scalar(
        select(CreativeProductionRunRecord)
        .where(
            CreativeProductionRunRecord.asset_id == asset_id,
            CreativeProductionRunRecord.content_version == asset.content_version,
            CreativeProductionRunRecord.status == "DIRECTOR_QA",
        )
        .order_by(CreativeProductionRunRecord.sequence_number.desc())
    )
    if not creative:
        raise ValueError("Nincs review-ra váró kreatív futás.")
    if submission.reviewed_asset_id != asset.asset_id:
        raise ValueError("A vizuális review másik assethez tartozik.")
    if submission.reviewed_content_sha256 != asset.content_hash:
        raise ValueError("A vizuális review nem az aktuális copy hashhez tartozik.")
    if submission.reviewed_visual_sha256 != creative.output_sha256:
        raise ValueError("A vizuális review nem az aktuális képi output hashhez tartozik.")
    if submission.generation_run_id != creative.generation_run_id:
        raise ValueError("A vizuális review másik generálási futáshoz tartozik.")
    _verify_visual_review_attestation(submission)
    if submission.reviewer_run_id == creative.generation_run_id:
        raise ValueError("A kreatív generáló és reviewer futása nem lehet azonos.")
    if submission.reviewer_identity == creative.producer_identity:
        raise ValueError("A kreatív producer nem hagyhatja jóvá a saját munkáját.")
    row = ContentWorkflowReviewRecord(
        review_id=f"CDR-{uuid.uuid4().hex[:16].upper()}",
        asset_id=asset_id,
        content_version=asset.content_version,
        stage="CREATIVE_DIRECTOR_QA",
        reviewer_role="CREATIVE_DIRECTOR",
        reviewer_identity=submission.reviewer_identity,
        reviewer_run_id=submission.reviewer_run_id,
        decision=submission.decision,
        artifact_hash=creative.output_sha256,
        review_json=_json(submission),
        created_by=actor,
    )
    db.add(row)
    approved = submission.decision == Decision.APPROVED
    creative.status = "APPROVED" if approved else "REJECTED"
    asset.creative_director_approved = approved
    asset.state = PublicationState.ASSEMBLY_QA if approved else PublicationState.VISUAL_PRODUCTION
    audit(
        db,
        actor=actor,
        action="creative_director_reviewed",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "review_id": row.review_id,
            "visual_generation_run_id": creative.generation_run_id,
            "decision": submission.decision,
            "state": asset.state,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def assemble_publication_bundle(
    db: Session,
    asset_id: str,
    submission: AssemblySubmission,
    *,
    actor: str,
) -> PublicationBundleRecord:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.ASSEMBLY_QA or not asset.creative_director_approved:
        raise ValueError(f"Assembly nem indítható ebből az állapotból: {asset.state}")
    if submission.copy_content_sha256 != asset.content_hash:
        raise ValueError("Az assembly nem az aktuális, jóváhagyott copy hashét használja.")
    creative = db.get(CreativeProductionRunRecord, submission.visual_generation_run_id)
    if (
        not creative
        or creative.asset_id != asset_id
        or creative.content_version != asset.content_version
        or creative.status != "APPROVED"
    ):
        raise ValueError(
            "Az assembly vizuális futása nem jóváhagyott vagy másik assethez tartozik."
        )
    if submission.assembler_identity == creative.producer_identity:
        raise ValueError("A vizuális producer nem végezheti a végső assembly ellenőrzött lépését.")
    if creative.platform not in {item.platform for item in submission.exports}:
        raise ValueError("A jóváhagyott kreatív platformjához nem készült export.")
    bundle_payload = {
        "asset_id": asset_id,
        "content_version": asset.content_version,
        "content_hash": asset.content_hash,
        "visual_generation_run_id": creative.generation_run_id,
        "visual_hash": creative.output_sha256,
        "assembly": submission.model_dump(mode="json"),
    }
    row = PublicationBundleRecord(
        bundle_id=f"BND-{uuid.uuid4().hex[:16].upper()}",
        asset_id=asset_id,
        content_version=asset.content_version,
        content_hash=asset.content_hash,
        visual_generation_run_id=creative.generation_run_id,
        assembly_run_id=submission.assembly_run_id,
        assembler_identity=submission.assembler_identity,
        bundle_hash=_hash(bundle_payload),
        exports_json=_json([export.model_dump(mode="json") for export in submission.exports]),
        pairing_rationale=submission.pairing_rationale,
        status="RELEASE_QA",
        created_by=actor,
    )
    db.add(row)
    asset.active_bundle_id = row.bundle_id
    asset.assembly_approved = True
    asset.campaign_package_approved = False
    asset.campaign_package_hash = None
    asset.campaign_artifact_set_hash = None
    asset.release_approved = False
    asset.state = PublicationState.RELEASE_QA
    audit(
        db,
        actor=actor,
        action="publication_bundle_assembled",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "bundle_id": row.bundle_id,
            "bundle_hash": row.bundle_hash,
            "export_count": len(submission.exports),
            "state": asset.state,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def _campaign_package_reviewers(
    db: Session,
    asset: ContentAssetRecord,
    *,
    package_gate_actor: str,
) -> dict[str, str]:
    brief_row = db.get(CopyBriefRecord, asset.copy_brief_id)
    strategy = db.scalar(
        select(CampaignStrategyReviewRecord).where(
            CampaignStrategyReviewRecord.copy_brief_id == asset.copy_brief_id,
            CampaignStrategyReviewRecord.decision == Decision.APPROVED,
        )
    )
    run = db.get(CopyReviewRun, asset.latest_run_id) if asset.latest_run_id else None
    if not brief_row or not strategy or not run:
        raise ValueError("A kampánycsomaghoz hiányzik a stratégiai vagy nyelvi review.")
    expert = EditorialReview.model_validate_json(run.expert_review_json)
    workflow_rows = db.scalars(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset.asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage.in_(
                ("MARKETING_QA", "DIRECT_RESPONSE_QA", "CREATIVE_DIRECTOR_QA")
            ),
            ContentWorkflowReviewRecord.decision == Decision.APPROVED,
        )
    ).all()
    workflow = {row.stage: row for row in workflow_rows}
    if set(workflow) != {"MARKETING_QA", "DIRECT_RESPONSE_QA", "CREATIVE_DIRECTOR_QA"}:
        raise ValueError(
            "A kampánycsomaghoz hiányzik marketing-, copywriter- vagy vizuális review."
        )
    approvals = db.scalars(
        select(ContentApprovalRecord).where(
            ContentApprovalRecord.asset_id == asset.asset_id,
            ContentApprovalRecord.content_version == asset.content_version,
            ContentApprovalRecord.decision == "APPROVED",
        )
    ).all()
    approval_by_type = {row.approval_type: row for row in approvals}
    specialist_rows = db.scalars(
        select(ContentGateDecision).where(
            ContentGateDecision.asset_id == asset.asset_id,
            ContentGateDecision.run_id == asset.latest_run_id,
            ContentGateDecision.gate_id.in_(("GATE_2_LEGAL_POLICY", "GATE_3_FINANCIAL_COMMERCIAL")),
        )
    ).all()
    specialist = {row.gate_id: row for row in specialist_rows}
    if set(specialist) != {"GATE_2_LEGAL_POLICY", "GATE_3_FINANCIAL_COMMERCIAL"}:
        raise ValueError("A kampánycsomaghoz hiányzik jogi vagy pénzügyi kapudöntés.")
    if any(row.decision == Decision.HUMAN_APPROVAL_REQUIRED for row in specialist.values()):
        raise ValueError(
            "Nyitott jogi vagy pénzügyi eszkaláció mellett nincs kampánycsomag-approval."
        )
    brand_guardian = approval_by_type.get("HUMAN_EDITORIAL")
    return {
        "marketing_strategist": strategy.reviewer_identity,
        "direct_response_copywriter": workflow["DIRECT_RESPONSE_QA"].reviewer_identity,
        "hungarian_language_editor": expert.reviewer_identity,
        "brand_guardian": brand_guardian.actor if brand_guardian else package_gate_actor,
        "creative_director": workflow["CREATIVE_DIRECTOR_QA"].reviewer_identity,
        "legal": specialist["GATE_2_LEGAL_POLICY"].agent_id,
        "financial": specialist["GATE_3_FINANCIAL_COMMERCIAL"].agent_id,
    }


def _validate_campaign_package_bindings(
    db: Session,
    asset: ContentAssetRecord,
    package: CampaignPackage,
    *,
    package_gate_actor: str,
) -> tuple[PublicationBundleRecord, CreativeProductionRunRecord, str]:
    if not asset.active_bundle_id:
        raise ValueError("A kampánycsomaghoz nincs aktív PublicationBundle.")
    bundle = db.get(PublicationBundleRecord, asset.active_bundle_id)
    if (
        not bundle
        or bundle.asset_id != asset.asset_id
        or bundle.content_version != asset.content_version
        or bundle.content_hash != asset.content_hash
    ):
        raise ValueError("A kampánycsomag nem az aktuális PublicationBundle-höz tartozik.")
    creative = db.get(CreativeProductionRunRecord, bundle.visual_generation_run_id)
    if not creative or creative.status != "APPROVED":
        raise ValueError("A kampánycsomag vizuális forrása nem jóváhagyott.")
    brief_row = db.get(CopyBriefRecord, asset.copy_brief_id)
    if not brief_row:
        raise ValueError("A kampánycsomag CopyBriefje hiányzik.")
    brief = CopyBrief.model_validate_json(brief_row.brief_json)
    expected_campaign_id = brief.campaign_id or brief.page_id
    if package.brand_id != asset.brand_id or package.campaign_id != expected_campaign_id:
        raise ValueError("A kampánycsomag márka- vagy kampányazonosítója eltér az assettől.")
    content = ContentAsset.model_validate_json(asset.content_json)
    if (
        package.copy_spec.headline != content.title
        or package.copy_spec.primary_text != content.body
        or package.copy_spec.cta != content.cta
    ):
        raise ValueError("A kampánycsomag copyja nem egyezik az aktuális tartalomhash tartalmával.")

    artifact_set = artifact_set_digest(package.artifacts)
    artifacts_by_role: dict[str, list[tuple[str, str]]] = {}
    for artifact in package.artifacts:
        artifacts_by_role.setdefault(artifact.role, []).append((artifact.path, artifact.sha256))
    if ("content.json", asset.content_hash) not in artifacts_by_role.get("copy", []):
        raise ValueError("A kampánycsomag copy artifactja nem az aktuális content hashhez kötött.")
    if (creative.output_uri, creative.output_sha256) not in artifacts_by_role.get(
        "visual_source", []
    ):
        raise ValueError("A kampánycsomag nem a jóváhagyott vizuális forrást használja.")
    required_named_artifacts = {
        "canonical_master": package.visual.canonical_master,
        "render_1080": package.visual.render_1080,
        "subject_mask": package.visual.subject_mask,
    }
    for role, path in required_named_artifacts.items():
        if not any(candidate_path == path for candidate_path, _ in artifacts_by_role.get(role, [])):
            raise ValueError(f"A {role} artifact útvonala nem egyezik a vizuális manifeszttel.")
    exports = json.loads(bundle.exports_json)
    export_bindings = set(artifacts_by_role.get("platform_export", []))
    expected_exports = {(item["output_uri"], item["output_sha256"]) for item in exports}
    if export_bindings != expected_exports:
        raise ValueError("A kampánycsomag platformexport-listája eltér a PublicationBundle-től.")

    visual_rows = db.scalars(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset.asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage == "CREATIVE_DIRECTOR_QA",
            ContentWorkflowReviewRecord.decision == Decision.APPROVED,
        )
    ).all()
    if len(visual_rows) != 1:
        raise ValueError("Pontosan egy aktuális kreatívigazgatói approval szükséges.")
    visual_review = CreativeDirectorReviewSubmission.model_validate_json(visual_rows[0].review_json)
    if (
        visual_review.minimum_source_font_px != package.visual.min_text_px
        or abs(visual_review.primary_subject_area_ratio - package.visual.photo_visible_ratio)
        > 0.0001
        or visual_review.text_overlaps_primary_subject
        or visual_review.text_background_overlaps_primary_subject
        or not visual_review.text_boxes_within_bounds
        or not visual_review.logo_lockup_brand_native
    ):
        raise ValueError("A vizuális manifeszt eltér a kreatívigazgatói mérési jegyzőkönyvtől.")

    expected_reviewers = _campaign_package_reviewers(
        db, asset, package_gate_actor=package_gate_actor
    )
    actual_reviewers = {review.role: review.reviewer_id for review in package.reviews}
    if actual_reviewers != expected_reviewers:
        raise ValueError(
            "A kampánycsomag review-identitásai nem egyeznek a tárolt kapubizonyítékokkal."
        )

    other_rows = db.scalars(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.stage == "CAMPAIGN_PACKAGE_QA",
            ContentWorkflowReviewRecord.decision == Decision.APPROVED,
        )
    ).all()
    other_packages: list[CampaignPackage] = []
    for row in other_rows:
        stored = CampaignPackageGateSubmission.model_validate_json(row.review_json)
        _verify_campaign_package_attestation(stored)
        other_packages.append(stored.package)
    failures = cross_brand_failures(package, other_packages)
    if failures:
        raise ValueError("Márkaközi elkülönítési hiba: " + " ".join(failures))
    return bundle, creative, artifact_set


def record_campaign_package_gate(
    db: Session,
    asset_id: str,
    package: CampaignPackage,
    *,
    actor: str,
) -> ContentWorkflowReviewRecord:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.RELEASE_QA or not asset.assembly_approved:
        raise ValueError(f"Kampánycsomag-review nem indítható ebből az állapotból: {asset.state}")
    if actor.casefold() == package.author_id.casefold():
        raise ValueError("A kampánycsomag szerzője nem futtathatja a végső csomagkaput.")
    existing = db.scalar(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage == "CAMPAIGN_PACKAGE_QA",
        )
    )
    if existing:
        raise ValueError("Ehhez a tartalomverzióhoz már létezik kampánycsomag-kapudöntés.")
    _, _, artifact_set = _validate_campaign_package_bindings(
        db, asset, package, package_gate_actor=actor
    )
    if len(settings.content_campaign_package_secret) < 32:
        raise ValueError("A CONTENT_CAMPAIGN_PACKAGE_SECRET kötelező és legalább 32 karakteres.")
    draft = CampaignPackageGateSubmission(
        package=package,
        gate_run_id=f"CPG-{uuid.uuid4().hex[:16].upper()}",
        reviewer_identity=actor,
        attestation_key_id=settings.content_campaign_package_key_id,
        attestation_sha256="0" * 64,
    )
    signed = _signed_submission(draft, settings.content_campaign_package_secret)
    _verify_campaign_package_attestation(signed)
    digest = package_hash(package)
    row = ContentWorkflowReviewRecord(
        review_id=f"CPG-{uuid.uuid4().hex[:16].upper()}",
        asset_id=asset_id,
        content_version=asset.content_version,
        stage="CAMPAIGN_PACKAGE_QA",
        reviewer_role="CONVERSION_CAMPAIGN_GATE",
        reviewer_identity=actor,
        reviewer_run_id=signed.gate_run_id,
        decision=Decision.APPROVED,
        artifact_hash=digest,
        review_json=_json(signed),
        created_by=actor,
    )
    db.add(row)
    asset.campaign_package_approved = True
    asset.campaign_package_hash = digest
    asset.campaign_artifact_set_hash = artifact_set
    audit(
        db,
        actor=actor,
        action="conversion_campaign_package_approved",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "review_id": row.review_id,
            "campaign_package_hash": digest,
            "artifact_set_sha256": artifact_set,
            "skill": "imperial-conversion-campaign-gate",
            "skill_version": "1.0",
            "publication_authorized": False,
            "r6_r7": "HUMAN_ONLY",
        },
    )
    db.commit()
    db.refresh(row)
    return row


def _verify_stored_campaign_package_gate(
    db: Session,
    asset: ContentAssetRecord,
) -> CampaignPackageGateSubmission:
    rows = db.scalars(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset.asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage == "CAMPAIGN_PACKAGE_QA",
            ContentWorkflowReviewRecord.decision == Decision.APPROVED,
        )
    ).all()
    if len(rows) != 1:
        raise ValueError("Pontosan egy hitelesített kampánycsomag-kapudöntés kötelező.")
    row = rows[0]
    submission = CampaignPackageGateSubmission.model_validate_json(row.review_json)
    _verify_campaign_package_attestation(submission)
    _, _, artifact_set = _validate_campaign_package_bindings(
        db,
        asset,
        submission.package,
        package_gate_actor=submission.reviewer_identity,
    )
    digest = package_hash(submission.package)
    if (
        row.artifact_hash != digest
        or asset.campaign_package_hash != digest
        or asset.campaign_artifact_set_hash != artifact_set
        or not asset.campaign_package_approved
    ):
        raise ValueError("A tárolt kampánycsomag-kapu hashkötése vagy adatbázis-állapota sérült.")
    return submission


def record_release_review(
    db: Session,
    asset_id: str,
    submission: ReleaseReviewSubmission,
    *,
    actor: str,
) -> ContentWorkflowReviewRecord:
    if actor != submission.reviewer_identity:
        raise ValueError("A release reviewer_identity az autentikált actor kell legyen.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.RELEASE_QA or not asset.active_bundle_id:
        raise ValueError(f"Release QA nem rögzíthető ebből az állapotból: {asset.state}")
    bundle = db.get(PublicationBundleRecord, asset.active_bundle_id)
    if (
        not bundle
        or bundle.asset_id != asset_id
        or bundle.content_hash != asset.content_hash
        or bundle.content_version != asset.content_version
    ):
        raise ValueError("Az aktív PublicationBundle hiányzik vagy elavult.")
    if submission.reviewer_identity == bundle.assembler_identity:
        raise ValueError("Az assembler nem hagyhatja jóvá a saját PublicationBundle-jét.")
    if not all(
        (
            asset.campaign_package_approved,
            asset.campaign_package_hash,
            asset.campaign_artifact_set_hash,
        )
    ):
        raise ValueError("A release QA előtt kötelező a hitelesített kampánycsomag-kapu.")
    if not all(
        (
            asset.gate_1_approved,
            asset.expert_language_approved,
            asset.expert_marketing_approved,
            asset.copywriter_approved,
            asset.four_gate_approved,
            asset.creative_director_approved,
            asset.assembly_approved,
        )
    ):
        raise ValueError("A release QA előtt hiányzik legalább egy korábbi kötelező kapu.")
    _verify_stored_campaign_package_gate(db, asset)
    row = ContentWorkflowReviewRecord(
        review_id=f"REL-{uuid.uuid4().hex[:16].upper()}",
        asset_id=asset_id,
        content_version=asset.content_version,
        stage="RELEASE_QA",
        reviewer_role="ONLINE_MARKETING_MANAGER",
        reviewer_identity=submission.reviewer_identity,
        reviewer_run_id=submission.reviewer_run_id,
        decision=submission.decision,
        artifact_hash=bundle.bundle_hash,
        review_json=_json(submission),
        created_by=actor,
    )
    db.add(row)
    approved = submission.decision == Decision.APPROVED
    asset.release_approved = approved
    bundle.status = "APPROVED" if approved else "REJECTED"
    if approved:
        asset.state = PublicationState.RELEASE_APPROVED
    else:
        asset.state = PublicationState.ASSEMBLY_QA
        asset.assembly_approved = False
        asset.campaign_package_approved = False
        asset.campaign_package_hash = None
        asset.campaign_artifact_set_hash = None
        asset.active_bundle_id = None
    audit(
        db,
        actor=actor,
        action="integrated_release_reviewed",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "review_id": row.review_id,
            "bundle_id": bundle.bundle_id,
            "decision": submission.decision,
            "state": asset.state,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def _verify_stored_mandatory_gate_reviews(
    db: Session,
    asset: ContentAssetRecord,
    creative: CreativeProductionRunRecord,
) -> dict[str, dict[str, Any]]:
    rows = db.scalars(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset.asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage.in_(
                ("MARKETING_QA", "DIRECT_RESPONSE_QA", "CREATIVE_DIRECTOR_QA")
            ),
            ContentWorkflowReviewRecord.decision == Decision.APPROVED,
        )
    ).all()
    by_stage = {row.stage: row for row in rows}
    required_stages = {"MARKETING_QA", "DIRECT_RESPONSE_QA", "CREATIVE_DIRECTOR_QA"}
    if set(by_stage) != required_stages:
        raise ValueError(
            "Hiányzik az aktuális tartalomhoz tartozó, hitelesített marketing-, "
            "copywriter- vagy vizuális kapudöntés."
        )

    copy_reviews: dict[str, MandatoryCopyGateReviewSubmission] = {}
    for stage, gate_id in (
        ("MARKETING_QA", "MARKETING"),
        ("DIRECT_RESPONSE_QA", "DIRECT_RESPONSE"),
    ):
        row = by_stage[stage]
        submission = MandatoryCopyGateReviewSubmission.model_validate_json(row.review_json)
        _verify_mandatory_copy_gate_attestation(submission)
        if (
            submission.gate_id != gate_id
            or submission.decision != Decision.APPROVED
            or submission.reviewed_asset_id != asset.asset_id
            or submission.reviewed_content_sha256 != asset.content_hash
            or submission.generation_run_id
            != json.loads(asset.generation_trace_json or "{}").get("generation_run_id")
            or row.artifact_hash != asset.content_hash
        ):
            raise ValueError(f"A tárolt {gate_id} kapudöntés kötése vagy integritása sérült.")
        copy_reviews[gate_id] = submission
    marketing = copy_reviews["MARKETING"]
    copywriter = copy_reviews["DIRECT_RESPONSE"]
    if (
        marketing.reviewer_identity == copywriter.reviewer_identity
        or marketing.reviewer_run_id == copywriter.reviewer_run_id
        or marketing.reviewer_model_version == copywriter.reviewer_model_version
    ):
        raise ValueError(
            "A marketing- és direct-response kapudöntés nem független reviewerhez tartozik."
        )

    visual_row = by_stage["CREATIVE_DIRECTOR_QA"]
    visual = CreativeDirectorReviewSubmission.model_validate_json(visual_row.review_json)
    _verify_visual_review_attestation(visual)
    if (
        visual.decision != Decision.APPROVED
        or visual.reviewed_asset_id != asset.asset_id
        or visual.reviewed_content_sha256 != asset.content_hash
        or visual.reviewed_visual_sha256 != creative.output_sha256
        or visual.generation_run_id != creative.generation_run_id
        or visual_row.artifact_hash != creative.output_sha256
    ):
        raise ValueError("A tárolt vizuális kapudöntés kötése vagy integritása sérült.")

    return {
        "MARKETING": {
            "review_id": by_stage["MARKETING_QA"].review_id,
            "review_hash": _hash(marketing),
            "artifact_hash": asset.content_hash,
            "reviewer_identity": marketing.reviewer_identity,
        },
        "DIRECT_RESPONSE": {
            "review_id": by_stage["DIRECT_RESPONSE_QA"].review_id,
            "review_hash": _hash(copywriter),
            "artifact_hash": asset.content_hash,
            "reviewer_identity": copywriter.reviewer_identity,
        },
        "VISUAL": {
            "review_id": visual_row.review_id,
            "review_hash": _hash(visual),
            "artifact_hash": creative.output_sha256,
            "reviewer_identity": visual.reviewer_identity,
        },
    }


def _delivery_targets(exports: list[dict[str, Any]]) -> list[str]:
    targets: set[str] = set()
    for export in exports:
        platform = str(export.get("platform") or "").strip().lower()
        if platform in {"facebook", "instagram", "meta", "meta_ads"}:
            targets.add("META_ADS")
        elif platform in {"google", "google_ads"}:
            targets.add("GOOGLE_ADS")
        elif platform:
            targets.add(f"CONTENT:{platform.upper()}")
    return sorted(targets)


def validate_publication_adapter_envelope(
    db: Session,
    payload: dict[str, Any],
) -> dict[str, Any]:
    asset_id = str(payload.get("asset_id") or "")
    proof_id = str(payload.get("publication_proof_id") or "")
    if not asset_id or not proof_id:
        raise ValueError("A publication-adapter üzenetből hiányzik az asset- vagy proofazonosító.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise ValueError("A publication-adapter üzenet ismeretlen assetre hivatkozik.")
    if asset.publication_proof_id != proof_id:
        raise ValueError(
            "A publication-adapter üzenet proofazonosítója nem az aktuális publikációé."
        )

    if payload.get("action") == "PAUSE_OR_UNPUBLISH":
        if asset.state != PublicationState.QUARANTINED:
            raise ValueError("PAUSE_OR_UNPUBLISH csak karanténba helyezett assetre küldhető.")
        if payload.get("automatic_republish_allowed") is not False:
            raise ValueError("Karantén után az automatikus újrapublikálásnak tiltva kell maradnia.")
        return {
            "action": "PAUSE_OR_UNPUBLISH",
            "asset_id": asset_id,
            "publication_proof_id": proof_id,
            "validated": True,
        }
    if payload.get("action") not in {None, "PUBLISH"}:
        raise ValueError("Ismeretlen publication-adapter művelet.")
    if asset.state not in {PublicationState.LIVE_QA, PublicationState.PUBLISHED}:
        raise ValueError(f"Publikációs adapter nem futhat ebből az állapotból: {asset.state}")
    if (
        payload.get("content_hash") != asset.content_hash
        or payload.get("publication_bundle_id") != asset.active_bundle_id
    ):
        raise ValueError("A publication-adapter envelope copy- vagy bundle-kötése elavult.")

    bundle = db.get(PublicationBundleRecord, asset.active_bundle_id)
    if (
        not bundle
        or bundle.status != "APPROVED"
        or bundle.asset_id != asset_id
        or bundle.content_version != asset.content_version
        or bundle.content_hash != asset.content_hash
    ):
        raise ValueError(
            "A publication-adapter envelope mögött nincs aktuális, jóváhagyott bundle."
        )
    creative = db.get(CreativeProductionRunRecord, bundle.visual_generation_run_id)
    if not creative or creative.status != "APPROVED":
        raise ValueError("A publication-adapter envelope vizuális forrása nem jóváhagyott.")
    exports = json.loads(bundle.exports_json)
    assembly_payload = {
        "assembly_run_id": bundle.assembly_run_id,
        "assembler_identity": bundle.assembler_identity,
        "visual_generation_run_id": bundle.visual_generation_run_id,
        "copy_content_sha256": bundle.content_hash,
        "pairing_rationale": bundle.pairing_rationale,
        "exports": exports,
    }
    expected_bundle_hash = _hash(
        {
            "asset_id": asset_id,
            "content_version": asset.content_version,
            "content_hash": asset.content_hash,
            "visual_generation_run_id": creative.generation_run_id,
            "visual_hash": creative.output_sha256,
            "assembly": assembly_payload,
        }
    )
    if (
        bundle.bundle_hash != expected_bundle_hash
        or payload.get("publication_bundle_hash") != expected_bundle_hash
        or payload.get("exports") != exports
    ):
        raise ValueError("A publication-adapter envelope bundle-je vagy exportlistája sérült.")

    gate_manifest = _verify_stored_mandatory_gate_reviews(db, asset, creative)
    gate_manifest_hash = _hash(gate_manifest)
    if (
        payload.get("mandatory_gate_manifest") != gate_manifest
        or payload.get("mandatory_gate_manifest_hash") != gate_manifest_hash
    ):
        raise ValueError("A publication-adapter envelope kötelező kapumanifesztje sérült.")
    campaign_package = _verify_stored_campaign_package_gate(db, asset)
    if (
        payload.get("campaign_package_hash") != package_hash(campaign_package.package)
        or payload.get("campaign_artifact_set_hash") != asset.campaign_artifact_set_hash
    ):
        raise ValueError("A publication-adapter kampánycsomag-kötése hiányzik vagy sérült.")
    release_token = payload.get("release_token")
    if not isinstance(release_token, dict):
        raise ValueError("A publication-adapter envelope-ból hiányzik a release-token.")
    _verify_release_token(release_token)
    expected_release_token = {
        "asset_id": asset.asset_id,
        "brand_id": asset.brand_id,
        "publication_proof_id": proof_id,
        "campaign_package_hash": asset.campaign_package_hash,
        "artifact_set_sha256": asset.campaign_artifact_set_hash,
        "publication_bundle_hash": bundle.bundle_hash,
        "human_reviewer_id": payload.get("owner_actor"),
        "approved_at": payload.get("published_at"),
        "r6_r7": "HUMAN_ONLY",
    }
    if {key: value for key, value in release_token.items() if key != "hmac_sha256"} != (
        expected_release_token
    ):
        raise ValueError(
            "A release-token nem az aktuális assethez, csomaghoz vagy emberhez kötött."
        )
    expected_contract = {
        "version": PUBLICATION_ADAPTER_CONTRACT_VERSION,
        "idempotency_key": proof_id,
        "mandatory_gate_manifest_hash": gate_manifest_hash,
        "campaign_package_hash": asset.campaign_package_hash,
        "campaign_artifact_set_hash": asset.campaign_artifact_set_hash,
        "release_token_hash": _hash(release_token),
        "delivery_targets": _delivery_targets(exports),
    }
    if payload.get("adapter_contract") != expected_contract:
        raise ValueError("A publication-adapter szerződés hiányzik, sérült vagy elavult.")
    return {
        "action": "PUBLISH",
        "asset_id": asset_id,
        "publication_proof_id": proof_id,
        "adapter_contract": expected_contract,
        "validated": True,
    }


def publish_content_asset(db: Session, asset_id: str, *, actor: str) -> dict[str, Any]:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    source_prevalidated = asset.source_prevalidated
    if asset.state != PublicationState.RELEASE_APPROVED:
        raise ValueError(f"Publikáció nem indítható ebből az állapotból: {asset.state}")
    required_flags = [
        asset.gate_1_approved,
        asset.expert_language_approved,
        asset.expert_marketing_approved,
        asset.copywriter_approved,
        asset.four_gate_approved,
        asset.creative_director_approved,
        asset.assembly_approved,
        asset.campaign_package_approved,
        asset.campaign_package_hash,
        asset.campaign_artifact_set_hash,
        asset.release_approved,
        asset.active_bundle_id,
        asset.latest_run_id,
    ]
    if not source_prevalidated:
        required_flags.extend([asset.editorial_approved, asset.owner_approved])
    if not all(required_flags):
        raise ValueError("Hiányzik legalább egy kötelező gépi vagy emberi jóváhagyás.")
    run = db.get(CopyReviewRun, asset.latest_run_id)
    if not run or run.final_decision != Decision.APPROVED or run.content_hash != asset.content_hash:
        raise ValueError("Nincs az aktuális tartalomhashhez tartozó APPROVED GateResult.")
    expert_gates = db.scalars(
        select(ContentGateDecision).where(
            ContentGateDecision.run_id == run.run_id,
            ContentGateDecision.gate_id == "GATE_HU_LANGUAGE_EXPERT",
            ContentGateDecision.decision == Decision.APPROVED,
            ContentGateDecision.certainty == "HIGH",
        )
    ).all()
    if {gate.gate_id for gate in expert_gates} != {"GATE_HU_LANGUAGE_EXPERT"}:
        raise ValueError(
            "Hiányzik az aktuális futáshoz tartozó magyar nyelvi vagy "
            "online marketing-szövegírói szakértői GateResult."
        )
    if run.expert_review_hash != _hash(json.loads(run.expert_review_json)):
        raise ValueError("A tárolt szakértői jegyzőkönyv integritása sérült.")
    stored_expert_review = EditorialReview.model_validate_json(run.expert_review_json)
    _verify_expert_review_attestation(stored_expert_review)
    if (
        stored_expert_review.reviewed_asset_id != asset.asset_id
        or stored_expert_review.reviewed_content_sha256 != asset.content_hash
        or stored_expert_review.generation_run_id
        != json.loads(asset.generation_trace_json or "{}").get("generation_run_id")
    ):
        raise ValueError(
            "A tárolt szakértői jegyzőkönyv nem az aktuális assethez, "
            "tartalomhashhez vagy generálási futáshoz tartozik."
        )
    approval_by_type: dict[str, ContentApprovalRecord] = {}
    if not source_prevalidated:
        approvals = db.scalars(
            select(ContentApprovalRecord).where(
                ContentApprovalRecord.asset_id == asset_id,
                ContentApprovalRecord.content_version == asset.content_version,
                ContentApprovalRecord.decision == "APPROVED",
            )
        ).all()
        approval_by_type = {
            row.approval_type: row for row in approvals if row.content_hash == asset.content_hash
        }
        if set(approval_by_type) != {"HUMAN_EDITORIAL", "OWNER"}:
            raise ValueError(
                "Az emberi szerkesztői vagy tulajdonosi approval hiányzik az aktuális hashhez."
            )
    brief_row = db.get(CopyBriefRecord, asset.copy_brief_id)
    strategy_review = db.scalar(
        select(CampaignStrategyReviewRecord).where(
            CampaignStrategyReviewRecord.copy_brief_id == asset.copy_brief_id,
            CampaignStrategyReviewRecord.decision == Decision.APPROVED,
        )
    )
    if (
        not brief_row
        or brief_row.status != "STRATEGY_APPROVED"
        or not strategy_review
        or strategy_review.brief_hash != _hash(json.loads(brief_row.brief_json))
    ):
        raise ValueError("Az aktuális CopyBrief stratégiai jóváhagyása hiányzik vagy elavult.")
    brief = CopyBrief.model_validate_json(brief_row.brief_json)
    content = ContentAsset.model_validate_json(asset.content_json)
    prevalidation = evaluate_commercial_prevalidation(asset.brand_id, content)
    generation_trace = json.loads(asset.generation_trace_json or "{}")
    copy_fast_lane_allowed = copy_mode_allows_source_prevalidation(generation_trace)
    if source_prevalidated and (not prevalidation.eligible or not copy_fast_lane_allowed):
        raise ValueError(
            "A forrás-elővalidáció a specialistakapu óta megváltozott vagy érvénytelen."
        )
    sources, snapshot_hash = resolve_canonical_sources(
        db, brief, visual_asset_ids=content.visual_asset_ids
    )
    promotion_snapshot_date = _monthly_promotion_snapshot_date(run)
    if promotion_snapshot_date is not None:
        sources, snapshot_hash = _enrich_monthly_promotion_sources(
            sources,
            brief,
            evaluated_on=promotion_snapshot_date,
        )
    if not sources.source_resolution_pass or snapshot_hash != run.source_snapshot_hash:
        raise ValueError("A kanonikus források hiányoznak vagy a review óta megváltoztak.")
    bundle = db.get(PublicationBundleRecord, asset.active_bundle_id)
    if (
        not bundle
        or bundle.status != "APPROVED"
        or bundle.asset_id != asset_id
        or bundle.content_version != asset.content_version
        or bundle.content_hash != asset.content_hash
    ):
        raise ValueError("Nincs jóváhagyott, aktuális PublicationBundle.")
    creative = db.get(CreativeProductionRunRecord, bundle.visual_generation_run_id)
    if not creative or creative.status != "APPROVED":
        raise ValueError("A PublicationBundle jóváhagyott vizuális forrása hiányzik.")
    mandatory_gate_manifest = _verify_stored_mandatory_gate_reviews(db, asset, creative)
    mandatory_gate_manifest_hash = _hash(mandatory_gate_manifest)
    exports = json.loads(bundle.exports_json)
    assembly_payload = {
        "assembly_run_id": bundle.assembly_run_id,
        "assembler_identity": bundle.assembler_identity,
        "visual_generation_run_id": bundle.visual_generation_run_id,
        "copy_content_sha256": bundle.content_hash,
        "pairing_rationale": bundle.pairing_rationale,
        "exports": exports,
    }
    expected_bundle_hash = _hash(
        {
            "asset_id": asset_id,
            "content_version": asset.content_version,
            "content_hash": asset.content_hash,
            "visual_generation_run_id": creative.generation_run_id,
            "visual_hash": creative.output_sha256,
            "assembly": assembly_payload,
        }
    )
    if bundle.bundle_hash != expected_bundle_hash:
        raise ValueError("A PublicationBundle integritása sérült.")
    campaign_package = _verify_stored_campaign_package_gate(db, asset)

    proof_id = f"PUB-{uuid.uuid4().hex[:16].upper()}"
    published_at = utcnow()
    release_token = _release_token(
        asset=asset,
        bundle=bundle,
        actor=actor,
        proof_id=proof_id,
        approved_at=published_at,
    )
    asset.publication_proof_id = proof_id
    asset.published_at = published_at
    asset.state = PublicationState.LIVE_QA
    proof = {
        "publication_proof_id": proof_id,
        "asset_id": asset_id,
        "content_hash": asset.content_hash,
        "run_id": run.run_id,
        "expert_review_hash": run.expert_review_hash,
        "mandatory_gate_manifest": mandatory_gate_manifest,
        "mandatory_gate_manifest_hash": mandatory_gate_manifest_hash,
        "campaign_package_hash": package_hash(campaign_package.package),
        "campaign_artifact_set_hash": asset.campaign_artifact_set_hash,
        "publication_bundle_id": bundle.bundle_id,
        "publication_bundle_hash": bundle.bundle_hash,
        "exports": exports,
        "source_snapshot_hash": snapshot_hash,
        "approval_mode": (
            "SOURCE_PREVALIDATED" if source_prevalidated else "HUMAN_EDITORIAL_AND_OWNER"
        ),
        "human_editorial_actor": (
            None if source_prevalidated else approval_by_type["HUMAN_EDITORIAL"].actor
        ),
        "owner_actor": actor,
        "release_token": release_token,
        "commercial_prevalidation": (
            {
                "registry_version": prevalidation.registry_version,
                "registry_sha256": prevalidation.registry_sha256,
                "verified_evidence_ids": prevalidation.verified_evidence_ids,
            }
            if source_prevalidated
            else None
        ),
        "published_at": asset.published_at.isoformat(),
        "state": asset.state,
        "external_delivery_enabled": settings.content_external_publishing_enabled,
        "adapter_contract": {
            "version": PUBLICATION_ADAPTER_CONTRACT_VERSION,
            "idempotency_key": proof_id,
            "mandatory_gate_manifest_hash": mandatory_gate_manifest_hash,
            "campaign_package_hash": asset.campaign_package_hash,
            "campaign_artifact_set_hash": asset.campaign_artifact_set_hash,
            "release_token_hash": _hash(release_token),
            "delivery_targets": _delivery_targets(exports),
        },
    }
    if settings.content_external_publishing_enabled:
        db.add(
            OutboxMessage(
                message_id=f"MSG-CQ-{uuid.uuid4().hex[:12].upper()}",
                destination_module="publication-adapter",
                payload_json=_json(proof),
                status="pending",
                next_attempt_at=utcnow(),
            )
        )
    audit(
        db,
        actor=actor,
        action="content_published",
        entity_type="content_asset",
        entity_id=asset_id,
        after=proof,
    )
    db.commit()
    return proof


def record_live_publication_review(
    db: Session,
    asset_id: str,
    submission: LiveReviewSubmission,
    *,
    actor: str,
) -> dict[str, Any]:
    if actor != submission.reviewer_identity:
        raise ValueError("Az élő reviewer_identity az autentikált actor kell legyen.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if asset.state != PublicationState.LIVE_QA or not asset.publication_proof_id:
        raise ValueError(f"Élő review nem rögzíthető ebből az állapotból: {asset.state}")
    if submission.rendered_copy_sha256 != asset.content_hash:
        raise ValueError("Az élő felületről visszaolvasott copy hash eltér a jóváhagyott copytól.")
    existing = db.scalars(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset_id,
            ContentWorkflowReviewRecord.content_version == asset.content_version,
            ContentWorkflowReviewRecord.stage == "LIVE_QA",
        )
    ).all()
    if submission.reviewer_role in {row.reviewer_role for row in existing}:
        raise ValueError("Ez a szakértői szerep már rögzítette az élő double checket.")
    if submission.reviewer_identity in {row.reviewer_identity for row in existing}:
        raise ValueError("A három élő review-t három külön reviewer entitásnak kell elvégeznie.")
    row = ContentWorkflowReviewRecord(
        review_id=f"LIVE-{uuid.uuid4().hex[:16].upper()}",
        asset_id=asset_id,
        content_version=asset.content_version,
        stage="LIVE_QA",
        reviewer_role=submission.reviewer_role,
        reviewer_identity=submission.reviewer_identity,
        reviewer_run_id=f"LIVE-{submission.reviewer_role}-{asset.publication_proof_id}",
        decision=submission.decision,
        artifact_hash=submission.screenshot_sha256,
        review_json=_json(submission),
        created_by=actor,
    )
    db.add(row)
    if submission.decision == "REJECTED":
        asset.state = PublicationState.QUARANTINED
        asset.live_review_approved = False
        db.add(
            OutboxMessage(
                message_id=f"MSG-CQ-{uuid.uuid4().hex[:12].upper()}",
                destination_module="publication-adapter",
                payload_json=_json(
                    {
                        "action": "PAUSE_OR_UNPUBLISH",
                        "asset_id": asset_id,
                        "publication_proof_id": asset.publication_proof_id,
                        "reason": submission.findings,
                        "automatic_republish_allowed": False,
                    }
                ),
                status="pending",
                next_attempt_at=utcnow(),
            )
        )
    else:
        approved_roles = {
            item.reviewer_role for item in existing if item.decision == "APPROVED"
        } | {submission.reviewer_role}
        required_roles = {
            "ONLINE_MARKETING_MANAGER",
            "CREATIVE_DIRECTOR",
            "DIRECT_RESPONSE_COPYWRITER",
        }
        if approved_roles == required_roles:
            asset.state = PublicationState.PUBLISHED
            asset.live_review_approved = True
    audit(
        db,
        actor=actor,
        action="live_publication_reviewed",
        entity_type="content_asset",
        entity_id=asset_id,
        after={
            "review_id": row.review_id,
            "reviewer_role": submission.reviewer_role,
            "reviewer_identity": submission.reviewer_identity,
            "decision": submission.decision,
            "state": asset.state,
        },
    )
    db.commit()
    return {
        "asset_id": asset_id,
        "review_id": row.review_id,
        "state": asset.state,
        "live_review_approved": asset.live_review_approved,
    }


def rollback_content_asset(
    db: Session, asset_id: str, *, actor: str, reason: str
) -> ContentAssetRecord:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    before = {
        "state": asset.state,
        "publication_proof_id": asset.publication_proof_id,
        "content_version": asset.content_version,
    }
    asset.content_version += 1
    asset.state = PublicationState.DRAFT
    asset.gate_1_approved = False
    asset.expert_language_approved = False
    asset.expert_marketing_approved = False
    asset.copywriter_approved = False
    asset.four_gate_approved = False
    asset.editorial_approved = False
    asset.owner_approved = False
    asset.source_prevalidated = False
    asset.creative_director_approved = False
    asset.assembly_approved = False
    asset.campaign_package_approved = False
    asset.campaign_package_hash = None
    asset.campaign_artifact_set_hash = None
    asset.release_approved = False
    asset.live_review_approved = False
    asset.active_bundle_id = None
    asset.latest_run_id = None
    asset.publication_proof_id = None
    asset.published_at = None
    audit(
        db,
        actor=actor,
        action="content_publication_rolled_back",
        entity_type="content_asset",
        entity_id=asset_id,
        before=before,
        after={
            "state": asset.state,
            "content_version": asset.content_version,
            "reason": reason,
        },
    )
    db.commit()
    db.refresh(asset)
    return asset


def record_performance_metric(
    db: Session,
    asset_id: str,
    metric: PerformanceMetricIn,
    *,
    source_system: str,
    actor: str,
) -> ContentPerformanceMetric:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    if metric.numeric_value is None and not metric.text_value:
        raise ValueError("numeric_value vagy text_value kötelező.")
    row = ContentPerformanceMetric(
        metric_id=f"CQM-{uuid.uuid4().hex[:16].upper()}",
        asset_id=asset_id,
        metric_type=metric.metric_type,
        numeric_value=metric.numeric_value,
        text_value=metric.text_value,
        occurred_on=datetime.combine(metric.occurred_on, time.min, tzinfo=UTC),
        source_system=source_system,
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="content_performance_recorded",
        entity_type="content_asset",
        entity_id=asset_id,
        after=metric.model_dump(mode="json") | {"source_system": source_system},
    )
    db.commit()
    db.refresh(row)
    return row
