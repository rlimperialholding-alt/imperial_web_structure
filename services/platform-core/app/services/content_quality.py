from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..copy_gate.engine import evaluate_content
from ..copy_gate.models import (
    ApprovalSubmission,
    CanonicalSources,
    ContentAsset,
    ContentEvaluationRequest,
    CopyBrief,
    CopySourceIn,
    Decision,
    EditorialReview,
    FourGateSubmission,
    GateResult,
    PerformanceMetricIn,
    PublicationState,
)
from ..copy_gate.orchestrator import GENERATION_STAGES, validate_visual_variant_trace
from ..models import (
    ContentApprovalRecord,
    ContentAssetRecord,
    ContentGateDecision,
    ContentPerformanceMetric,
    CopyBriefRecord,
    CopyReviewRun,
    CopySourceRecord,
    OutboxMessage,
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


def utcnow() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


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
        status="APPROVED",
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
    if not brief_row or brief_row.status != "APPROVED":
        raise ValueError("Csak jóváhagyott CopyBriefhez hozható létre asset.")
    if db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == payload.asset_id)):
        raise ValueError("Az AssetID már létezik.")
    if generation_trace.get("stages", []) != list(GENERATION_STAGES):
        raise ValueError("A kilenc kötelező generálási/szerkesztési szakasz sorrendje hiányos.")
    if not generation_trace.get("generation_run_id"):
        raise ValueError("A generation_run_id kötelező.")
    sibling_traces: list[dict[str, Any]] = []
    sibling_rows = db.scalars(
        select(ContentAssetRecord).where(ContentAssetRecord.copy_brief_id == copy_brief_id)
    ).all()
    for sibling in sibling_rows:
        try:
            sibling_traces.append(json.loads(sibling.generation_trace_json or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("Sérült korábbi generation_trace_json.") from exc
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
    sources, snapshot_hash = resolve_canonical_sources(
        db, brief, visual_asset_ids=content.visual_asset_ids
    )
    asset_row.state = PublicationState.COPY_QA
    result = evaluate_content(
        ContentEvaluationRequest(
            brief=brief,
            sources=sources,
            asset=content,
            editorial_review=editorial_review,
            evaluated_on=evaluated_on or utcnow().date(),
        )
    )
    run_id = f"CQR-{uuid.uuid4().hex[:16].upper()}"
    generation_trace = json.loads(asset_row.generation_trace_json or "{}")
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
        repair_brief_json=_json(result.repair_brief),
        created_by=actor,
    )
    db.add(run)
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
    asset_row.latest_run_id = run_id
    asset_row.gate_1_approved = result.final_decision == Decision.APPROVED
    asset_row.four_gate_approved = False
    asset_row.editorial_approved = False
    asset_row.owner_approved = False
    asset_row.state = (
        PublicationState.FOUR_GATE_QA
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
        or not asset.latest_run_id
    ):
        raise ValueError("A négykapus review csak sikeres COPY_QA után indítható.")
    run = db.get(CopyReviewRun, asset.latest_run_id)
    content = ContentAsset.model_validate_json(asset.content_json)
    prevalidation = evaluate_commercial_prevalidation(asset.brand_id, content)
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
        elif not submitted and prevalidation.eligible and prevalidation.gate_coverage[gate_id]:
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
        asset.source_prevalidated = prevalidation.eligible
        asset.state = (
            PublicationState.SOURCE_PREVALIDATED
            if prevalidation.eligible
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
        asset.state = PublicationState.OWNER_APPROVAL if approved else PublicationState.BLOCKED
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


def publish_content_asset(db: Session, asset_id: str, *, actor: str) -> dict[str, Any]:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise KeyError(asset_id)
    source_prevalidated = (
        asset.state == PublicationState.SOURCE_PREVALIDATED and asset.source_prevalidated
    )
    if asset.state == PublicationState.SOURCE_PREVALIDATED and not asset.source_prevalidated:
        raise ValueError(
            "A SOURCE_PREVALIDATED állapothoz hiányzik az adatbázis-integritási jelző."
        )
    if asset.state not in {
        PublicationState.OWNER_APPROVAL,
        PublicationState.SOURCE_PREVALIDATED,
    }:
        raise ValueError(f"Publikáció nem indítható ebből az állapotból: {asset.state}")
    required_flags = [
        asset.gate_1_approved,
        asset.four_gate_approved,
        asset.latest_run_id,
    ]
    if not source_prevalidated:
        required_flags.extend([asset.editorial_approved, asset.owner_approved])
    if not all(required_flags):
        raise ValueError("Hiányzik legalább egy kötelező gépi vagy emberi jóváhagyás.")
    run = db.get(CopyReviewRun, asset.latest_run_id)
    if not run or run.final_decision != Decision.APPROVED or run.content_hash != asset.content_hash:
        raise ValueError("Nincs az aktuális tartalomhashhez tartozó APPROVED GateResult.")
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
    if not brief_row:
        raise ValueError("A CopyBrief rekord hiányzik.")
    brief = CopyBrief.model_validate_json(brief_row.brief_json)
    content = ContentAsset.model_validate_json(asset.content_json)
    prevalidation = evaluate_commercial_prevalidation(asset.brand_id, content)
    if source_prevalidated and not prevalidation.eligible:
        raise ValueError(
            "A forrás-elővalidáció a specialistakapu óta megváltozott vagy érvénytelen."
        )
    sources, snapshot_hash = resolve_canonical_sources(
        db, brief, visual_asset_ids=content.visual_asset_ids
    )
    if not sources.source_resolution_pass or snapshot_hash != run.source_snapshot_hash:
        raise ValueError("A kanonikus források hiányoznak vagy a review óta megváltoztak.")

    proof_id = f"PUB-{uuid.uuid4().hex[:16].upper()}"
    asset.publication_proof_id = proof_id
    asset.published_at = utcnow()
    asset.state = PublicationState.PUBLISHED
    proof = {
        "publication_proof_id": proof_id,
        "asset_id": asset_id,
        "content_hash": asset.content_hash,
        "run_id": run.run_id,
        "source_snapshot_hash": snapshot_hash,
        "approval_mode": (
            "SOURCE_PREVALIDATED" if source_prevalidated else "HUMAN_EDITORIAL_AND_OWNER"
        ),
        "human_editorial_actor": (
            None if source_prevalidated else approval_by_type["HUMAN_EDITORIAL"].actor
        ),
        "owner_actor": None if source_prevalidated else approval_by_type["OWNER"].actor,
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
        "external_delivery_enabled": settings.content_external_publishing_enabled,
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
    asset.four_gate_approved = False
    asset.editorial_approved = False
    asset.owner_approved = False
    asset.source_prevalidated = False
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
