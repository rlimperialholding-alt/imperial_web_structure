from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from secrets import token_urlsafe
from typing import TypedDict
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    ContentAssetRecord,
    ContentPerformanceMetric,
    CopyBriefRecord,
    EnterpriseCanonicalRecord,
    MailSuppression,
    MarketingCampaign,
    MarketingCampaignDailyMetric,
    MarketingLead,
    MarketingLeadActivity,
    MarketingOptimizationDecision,
    ModuleBusinessRecord,
    ProjectRegistry,
    TaskRecord,
)

CAMPAIGN_ROLES = {"owner", "managing-director", "marketing", "platform-admin"}
CAMPAIGN_APPROVERS = {"owner", "managing-director", "platform-admin"}
LEAD_ROLES = CAMPAIGN_ROLES | {"sales"}
SALES_ROLES = {"owner", "managing-director", "sales", "platform-admin"}


class CampaignPerformance(TypedDict):
    days: int
    impressions: int
    clicks: int
    landing_sessions: int
    form_starts: int
    form_completes: int
    spend_net: Decimal
    leads: int
    mql: int
    sales_accepted: int
    ctr_percent: Decimal
    landing_conversion_percent: Decimal
    mql_rate_percent: Decimal
    sales_acceptance_percent: Decimal
    actual_cpl_net: Decimal | None
    cost_per_mql_net: Decimal | None


def _identity(user: object) -> tuple[str, str]:
    return str(getattr(user, "role", "")), str(getattr(user, "email", "")).lower()


def _require(user: object, roles: set[str]) -> tuple[str, str]:
    role, email = _identity(user)
    if role not in roles:
        raise PermissionError("Ehhez a marketing- vagy leadművelethez nincs jogosultsága.")
    return role, email


def _money(value: object) -> Decimal:
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Érvénytelen pénzügyi összeg.") from exc
    if amount < 0:
        raise ValueError("Negatív marketingösszeg nem rögzíthető.")
    return amount


def _campaign(db: Session, campaign_id: str) -> MarketingCampaign:
    row = db.scalar(select(MarketingCampaign).where(MarketingCampaign.campaign_id == campaign_id))
    if not row:
        raise KeyError(campaign_id)
    return row


def _lead(db: Session, lead_id: str) -> MarketingLead:
    row = db.scalar(select(MarketingLead).where(MarketingLead.lead_id == lead_id))
    if not row:
        raise KeyError(lead_id)
    return row


def _json_object(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"legacy_raw_payload": raw}
    if isinstance(loaded, dict):
        return loaded
    return {"legacy_payload": loaded}


def _sync_lead_consent_downstream(db: Session, row: MarketingLead, actor: str) -> None:
    consent_payload = {
        "marketingConsent": row.marketing_consent,
        "marketingConsentUpdatedAt": (
            row.marketing_consent_updated_at.isoformat()
            if row.marketing_consent_updated_at
            else None
        ),
        "marketingConsentSource": row.marketing_consent_source,
        "marketingConsentWithdrawnAt": (
            row.marketing_consent_withdrawn_at.isoformat()
            if row.marketing_consent_withdrawn_at
            else None
        ),
    }
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.domain == "customer",
            EnterpriseCanonicalRecord.entity_type == "lead",
            EnterpriseCanonicalRecord.external_key == row.lead_id,
        )
    )
    if canonical:
        payload = _json_object(canonical.data_json)
        payload.update(consent_payload)
        canonical.data_json = json.dumps(payload, ensure_ascii=False, default=str)
    if row.crm_record_id:
        crm_record = db.scalar(
            select(ModuleBusinessRecord).where(
                ModuleBusinessRecord.record_id == row.crm_record_id
            )
        )
        if crm_record:
            payload = _json_object(crm_record.data_json)
            payload.update(consent_payload)
            crm_record.data_json = json.dumps(payload, ensure_ascii=False, default=str)
            crm_record.updated_by = actor


def _set_mail_suppression(db: Session, row: MarketingLead, *, consent: bool) -> None:
    if not row.email:
        return
    normalized_email = row.email.strip().lower()
    suppression = db.scalar(
        select(MailSuppression).where(MailSuppression.email == normalized_email)
    )
    if not consent:
        if not suppression:
            db.add(
                MailSuppression(
                    email=normalized_email,
                    reason="marketing_consent_withdrawn",
                    source="marketing_automation",
                    active=True,
                    details_json=json.dumps({"lead_id": row.lead_id}),
                )
            )
        elif suppression.reason == "marketing_consent_withdrawn":
            suppression.reason = "marketing_consent_withdrawn"
            suppression.source = "marketing_automation"
            suppression.active = True
            suppression.details_json = json.dumps({"lead_id": row.lead_id})
        else:
            details = _json_object(suppression.details_json)
            details["marketing_consent_withdrawn"] = True
            details["marketing_lead_id"] = row.lead_id
            suppression.details_json = json.dumps(details, ensure_ascii=False)
            suppression.active = True
    elif suppression and suppression.reason == "marketing_consent_withdrawn":
        suppression.active = False


def _change_marketing_consent(
    db: Session,
    row: MarketingLead,
    *,
    consent: bool,
    actor: str,
    source: str,
    evidence: str,
) -> MarketingLead:
    clean_source = source.strip()
    clean_evidence = evidence.strip()
    if not clean_source:
        raise ValueError("A hozzájárulás forrása kötelező.")
    if len(clean_evidence) < 10:
        raise ValueError("A hozzájárulási döntéshez legalább 10 karakteres bizonyíték kell.")
    if consent and row.email:
        suppression = db.scalar(
            select(MailSuppression).where(
                MailSuppression.email == row.email.strip().lower(),
                MailSuppression.active.is_(True),
            )
        )
        if suppression and suppression.reason != "marketing_consent_withdrawn":
            raise ValueError(
                "Az e-mail-cím más okból aktív tiltólistán van; a hozzájárulás "
                "külön tiltásfeloldás nélkül nem engedélyezhető."
            )
    now = datetime.now(UTC)
    row.marketing_consent = consent
    row.marketing_consent_updated_at = now
    row.marketing_consent_source = clean_source
    row.marketing_consent_evidence = clean_evidence
    row.marketing_consent_withdrawn_at = None if consent else now
    _set_mail_suppression(db, row, consent=consent)
    _sync_lead_consent_downstream(db, row, actor)
    action = "granted" if consent else "withdrawn"
    _activity(
        db,
        row.lead_id,
        f"marketing_consent_{action}",
        actor=actor,
        detail={"source": clean_source, "evidence": clean_evidence},
    )
    audit(
        db,
        actor=actor,
        action=f"marketing_consent_{action}",
        entity_type="marketing_lead",
        entity_id=row.lead_id,
        after={"marketing_consent": consent, "source": clean_source},
    )
    db.commit()
    db.refresh(row)
    return row


def set_marketing_consent(
    db: Session,
    lead_id: str,
    user: object,
    *,
    consent: bool,
    source: str,
    evidence: str,
) -> MarketingLead:
    _role, actor = _require(user, LEAD_ROLES)
    row = _lead(db, lead_id)
    return _change_marketing_consent(
        db,
        row,
        consent=consent,
        actor=actor,
        source=source,
        evidence=evidence,
    )


def marketing_lead_by_consent_token(db: Session, token: str) -> MarketingLead:
    row = db.scalar(
        select(MarketingLead).where(MarketingLead.consent_management_token == token)
    )
    if not row:
        raise KeyError(token)
    return row


def withdraw_marketing_consent_by_token(db: Session, token: str) -> MarketingLead:
    row = marketing_lead_by_consent_token(db, token)
    if not row.marketing_consent:
        return row
    return _change_marketing_consent(
        db,
        row,
        consent=False,
        actor="data-subject",
        source="self_service",
        evidence="A címzett a személyes leiratkozási hivatkozással visszavonta.",
    )


def _activity(
    db: Session,
    lead_id: str,
    activity_type: str,
    *,
    actor: str | None,
    detail: dict[str, object],
) -> None:
    db.add(
        MarketingLeadActivity(
            activity_id=f"LEAD-ACT-{uuid4().hex[:14].upper()}",
            lead_id=lead_id,
            activity_type=activity_type,
            detail_json=json.dumps(detail, ensure_ascii=False, default=str),
            actor=actor,
        )
    )


def campaign_content_ready(db: Session, campaign_id: str) -> bool:
    return bool(
        db.scalar(
            select(ContentAssetRecord.id)
            .join(
                CopyBriefRecord,
                CopyBriefRecord.copy_brief_id == ContentAssetRecord.copy_brief_id,
            )
            .where(
                CopyBriefRecord.campaign_id == campaign_id,
                ContentAssetRecord.state == "PUBLISHED",
                ContentAssetRecord.live_review_approved.is_(True),
            )
            .limit(1)
        )
    )


def marketing_automation_workspace(db: Session) -> dict[str, object]:
    campaigns = db.scalars(
        select(MarketingCampaign).order_by(desc(MarketingCampaign.updated_at)).limit(100)
    ).all()
    leads = db.scalars(
        select(MarketingLead).order_by(desc(MarketingLead.updated_at)).limit(250)
    ).all()
    activities = db.scalars(
        select(MarketingLeadActivity).order_by(desc(MarketingLeadActivity.occurred_at)).limit(100)
    ).all()
    decisions = db.scalars(
        select(MarketingOptimizationDecision)
        .order_by(desc(MarketingOptimizationDecision.proposed_at))
        .limit(100)
    ).all()
    campaign_items = []
    for row in campaigns:
        campaign_items.append(
            {
                "row": row,
                "content_ready": campaign_content_ready(db, row.campaign_id),
                "performance": campaign_performance(db, row.campaign_id),
            }
        )
    return {
        "campaigns": campaign_items,
        "leads": leads,
        "activities": activities,
        "decisions": decisions,
        "metrics": {
            "campaigns": len(campaigns),
            "active_campaigns": sum(row.status == "active" for row in campaigns),
            "leads": len(leads),
            "mql": sum(
                row.status
                in {
                    "marketing_qualified",
                    "crm_handoff",
                    "sales_accepted",
                    "converted",
                }
                for row in leads
            ),
            "sales_accepted": sum(row.status in {"sales_accepted", "converted"} for row in leads),
            "consented": sum(row.marketing_consent for row in leads),
        },
    }


def campaign_performance(db: Session, campaign_id: str) -> CampaignPerformance:
    rows = db.scalars(
        select(MarketingCampaignDailyMetric).where(
            MarketingCampaignDailyMetric.campaign_id == campaign_id
        )
    ).all()
    leads = db.scalars(select(MarketingLead).where(MarketingLead.campaign_id == campaign_id)).all()
    impressions = sum(row.impressions for row in rows)
    clicks = sum(row.clicks for row in rows)
    sessions = sum(row.landing_sessions for row in rows)
    form_starts = sum(row.form_starts for row in rows)
    form_completes = sum(row.form_completes for row in rows)
    spend = sum((row.spend_net for row in rows), Decimal("0"))
    mql = sum(
        row.status
        in {
            "marketing_qualified",
            "crm_handoff",
            "sales_accepted",
            "converted",
        }
        for row in leads
    )
    accepted = sum(row.status in {"sales_accepted", "converted"} for row in leads)
    lead_count = len(leads)

    def ratio(numerator: int, denominator: int) -> Decimal:
        if not denominator:
            return Decimal("0")
        return (Decimal(numerator) / Decimal(denominator) * 100).quantize(Decimal("0.01"))

    return {
        "days": len({row.metric_date for row in rows}),
        "impressions": impressions,
        "clicks": clicks,
        "landing_sessions": sessions,
        "form_starts": form_starts,
        "form_completes": form_completes,
        "spend_net": spend,
        "leads": lead_count,
        "mql": mql,
        "sales_accepted": accepted,
        "ctr_percent": ratio(clicks, impressions),
        "landing_conversion_percent": ratio(lead_count, sessions),
        "mql_rate_percent": ratio(mql, lead_count),
        "sales_acceptance_percent": ratio(accepted, mql),
        "actual_cpl_net": (spend / lead_count).quantize(Decimal("0.01")) if lead_count else None,
        "cost_per_mql_net": (spend / mql).quantize(Decimal("0.01")) if mql else None,
    }


def ingest_campaign_metric(
    db: Session,
    user: object,
    *,
    campaign_id: str,
    asset_id: str,
    metric_date: date,
    channel: str,
    source_system: str,
    external_key: str,
    impressions: int,
    clicks: int,
    landing_sessions: int,
    form_starts: int,
    form_completes: int,
    platform_conversions: int,
    spend_net: object,
    currency: str,
    raw_payload: dict[str, object],
) -> MarketingCampaignDailyMetric:
    _role, email = _require(user, CAMPAIGN_ROLES)
    campaign = _campaign(db, campaign_id)
    if campaign.status not in {"active", "paused", "completed"}:
        raise ValueError(
            "Teljesítménymetrika csak aktív, szüneteltetett vagy lezárt kampányhoz rögzíthető."
        )
    channel, source_system, external_key = (
        channel.strip().lower(),
        source_system.strip().lower(),
        external_key.strip(),
    )
    if not channel or not source_system or not external_key:
        raise ValueError("Csatorna, forrásrendszer és külső metrikakulcs kötelező.")
    counts = {
        "impressions": impressions,
        "clicks": clicks,
        "landing_sessions": landing_sessions,
        "form_starts": form_starts,
        "form_completes": form_completes,
        "platform_conversions": platform_conversions,
    }
    if any(value < 0 for value in counts.values()):
        raise ValueError("A kampánymetrikák nem lehetnek negatívak.")
    if clicks > impressions:
        raise ValueError("A kattintások száma nem haladhatja meg a megjelenéseket.")
    if form_starts > landing_sessions or form_completes > form_starts:
        raise ValueError("Érvénytelen landing–űrlap tölcsérszámok.")
    normalized_currency = currency.strip().upper()
    if normalized_currency not in {"HUF", "EUR"}:
        raise ValueError("A metrika pénzneme HUF vagy EUR lehet.")
    if normalized_currency != campaign.currency:
        raise ValueError("A metrika pénznemének egyeznie kell a kampány pénznemével.")
    if asset_id.strip():
        linked_asset = db.scalar(
            select(ContentAssetRecord)
            .join(
                CopyBriefRecord,
                CopyBriefRecord.copy_brief_id == ContentAssetRecord.copy_brief_id,
            )
            .where(
                ContentAssetRecord.asset_id == asset_id.strip(),
                CopyBriefRecord.campaign_id == campaign_id,
            )
        )
        if not linked_asset:
            raise ValueError("Az asset nem ehhez a kampányhoz tartozik.")
    canonical_payload = {
        "campaign_id": campaign_id,
        "asset_id": asset_id.strip() or None,
        "metric_date": metric_date.isoformat(),
        "channel": channel,
        "source_system": source_system,
        "external_key": external_key,
        **counts,
        "spend_net": str(_money(spend_net)),
        "currency": normalized_currency,
        "raw_payload": raw_payload,
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    row = db.scalar(
        select(MarketingCampaignDailyMetric).where(
            MarketingCampaignDailyMetric.source_system == source_system,
            MarketingCampaignDailyMetric.external_key == external_key,
        )
    )
    if row and row.raw_payload_hash == payload_hash:
        return row
    if row and row.campaign_id != campaign_id:
        raise ValueError(
            "A külső metrikakulcs már egy másik kampányhoz tartozik; az átkötés tiltott."
        )
    before = None
    if row:
        before = {"raw_payload_hash": row.raw_payload_hash}
    else:
        row = MarketingCampaignDailyMetric(
            metric_id=f"MKT-MET-{uuid4().hex[:14].upper()}",
            source_system=source_system,
            external_key=external_key,
            imported_by=email,
        )
        db.add(row)
    row.campaign_id = campaign_id
    row.asset_id = asset_id.strip() or None
    row.metric_date = metric_date
    row.channel = channel
    for key, value in counts.items():
        setattr(row, key, value)
    row.spend_net = _money(spend_net)
    row.currency = normalized_currency
    row.raw_payload_hash = payload_hash
    row.imported_by = email
    row.imported_at = datetime.now(UTC)
    db.flush()
    if row.asset_id:
        occurred = datetime(metric_date.year, metric_date.month, metric_date.day, tzinfo=UTC)
        derived: dict[str, Decimal] = {
            "ctr": (Decimal(clicks) / Decimal(impressions) * 100).quantize(Decimal("0.0001"))
            if impressions
            else Decimal("0"),
            "form_complete": Decimal(form_completes),
        }
        for metric_type, metric_value in derived.items():
            derived_id = f"CQM-{row.metric_id}-{metric_type.upper()}"
            content_metric = db.scalar(
                select(ContentPerformanceMetric).where(
                    ContentPerformanceMetric.metric_id == derived_id
                )
            )
            if not content_metric:
                content_metric = ContentPerformanceMetric(
                    metric_id=derived_id,
                    asset_id=row.asset_id,
                    metric_type=metric_type,
                    occurred_on=occurred,
                    source_system=source_system,
                )
                db.add(content_metric)
            content_metric.numeric_value = metric_value
    audit(
        db,
        actor=email,
        action="marketing_campaign_metric_upserted",
        entity_type="marketing_campaign",
        entity_id=campaign_id,
        before=before,
        after={"metric_id": row.metric_id, "payload_hash": payload_hash, **counts},
    )
    db.commit()
    db.refresh(row)
    return row


def propose_optimization(
    db: Session, campaign_id: str, user: object, *, rationale: str
) -> MarketingOptimizationDecision:
    _role, email = _require(user, CAMPAIGN_ROLES)
    campaign = _campaign(db, campaign_id)
    if campaign.status not in {"active", "paused"}:
        raise ValueError("Optimalizálás csak aktív vagy szüneteltetett kampányra kérhető.")
    if db.scalar(
        select(MarketingOptimizationDecision).where(
            MarketingOptimizationDecision.campaign_id == campaign_id,
            MarketingOptimizationDecision.status.in_(["proposed", "approved"]),
        )
    ):
        raise ValueError("A kampányhoz már van nyitott optimalizálási döntés.")
    evidence = campaign_performance(db, campaign_id)
    if not evidence["days"] or evidence["spend_net"] <= 0:
        raise ValueError("Optimalizáláshoz költést tartalmazó teljesítményadat szükséges.")
    actual_cpl = evidence["actual_cpl_net"]
    if evidence["leads"] == 0 and evidence["spend_net"] >= campaign.target_cpl_net * 2:
        decision_type = "pause"
        auto_reason = "Két cél-CPL feletti költés mellett nincs attribuált lead."
    elif (
        actual_cpl is not None
        and actual_cpl <= campaign.target_cpl_net
        and evidence["mql_rate_percent"] >= 30
    ):
        decision_type = "scale"
        auto_reason = "A CPL célon belül van és az MQL-arány legalább 30%."
    elif evidence["ctr_percent"] < Decimal("0.80"):
        decision_type = "creative_test"
        auto_reason = "A CTR 0,80% alatt van; új kreatív hipotézis szükséges."
    elif evidence["landing_conversion_percent"] < Decimal("2.00"):
        decision_type = "landing_test"
        auto_reason = "A landing leadkonverzió 2% alatt van."
    else:
        decision_type = "hold"
        auto_reason = "A jelenlegi adatok még nem indokolnak költés- vagy kreatívváltást."
    full_rationale = f"{auto_reason} {rationale.strip()}".strip()
    if len(full_rationale) < 30:
        raise ValueError("Az optimalizálási indoklás legalább 30 karakter legyen.")
    proposed_budget = (
        (campaign.budget_net * Decimal("1.20")).quantize(Decimal("0.01"))
        if decision_type == "scale"
        else None
    )
    row = MarketingOptimizationDecision(
        decision_id=f"MKT-OPT-{uuid4().hex[:14].upper()}",
        campaign_id=campaign_id,
        decision_type=decision_type,
        rationale=full_rationale,
        evidence_json=json.dumps(evidence, ensure_ascii=False, default=str),
        proposed_budget_net=proposed_budget,
        proposed_by=email,
    )
    db.add(row)
    audit(
        db,
        actor=email,
        action="marketing_optimization_proposed",
        entity_type="marketing_optimization",
        entity_id=row.decision_id,
        after={"campaign_id": campaign_id, "decision_type": decision_type},
    )
    db.commit()
    db.refresh(row)
    return row


def decide_optimization(
    db: Session,
    decision_id: str,
    user: object,
    *,
    decision: str,
    note: str,
) -> MarketingOptimizationDecision:
    _role, email = _require(user, CAMPAIGN_APPROVERS)
    row = db.scalar(
        select(MarketingOptimizationDecision).where(
            MarketingOptimizationDecision.decision_id == decision_id
        )
    )
    if not row:
        raise KeyError(decision_id)
    if row.status != "proposed":
        raise ValueError("Csak javasolt optimalizálási döntés bírálható el.")
    if row.proposed_by.lower() == email:
        raise ValueError("Az optimalizálási javaslatot független döntőnek kell elbírálnia.")
    if decision not in {"approve", "reject"}:
        raise ValueError("A döntés approve vagy reject lehet.")
    if len(note.strip()) < 15:
        raise ValueError("A döntési indoklás legalább 15 karakteres legyen.")
    row.status = "approved" if decision == "approve" else "rejected"
    row.decided_by = email
    row.decision_note = note.strip()
    row.decided_at = datetime.now(UTC)
    audit(
        db,
        actor=email,
        action=f"marketing_optimization_{row.status}",
        entity_type="marketing_optimization",
        entity_id=decision_id,
        after={"note": note.strip()},
    )
    db.commit()
    db.refresh(row)
    return row


def execute_optimization(
    db: Session, decision_id: str, user: object
) -> MarketingOptimizationDecision:
    _role, email = _require(user, CAMPAIGN_ROLES)
    row = db.scalar(
        select(MarketingOptimizationDecision).where(
            MarketingOptimizationDecision.decision_id == decision_id
        )
    )
    if not row:
        raise KeyError(decision_id)
    if row.status != "approved":
        raise ValueError("Csak jóváhagyott optimalizálási döntés hajtható végre.")
    campaign = _campaign(db, row.campaign_id)
    if row.decision_type == "pause":
        if campaign.status != "active":
            raise ValueError("A pause döntéshez aktív kampány szükséges.")
        campaign.status = "paused"
    elif row.decision_type == "scale":
        if row.proposed_budget_net is None:
            raise ValueError("A scale döntésből hiányzik a jóváhagyott keret.")
        campaign.budget_net = row.proposed_budget_net
    elif row.decision_type in {"creative_test", "landing_test", "audience_test"}:
        assignee = (
            "creative-director@imperial.local"
            if row.decision_type == "creative_test"
            else "marketing@imperial.local"
        )
        _ensure_commercial_pipeline(db, assignee)
        db.add(
            TaskRecord(
                task_id=f"TASK-MKT-OPT-{uuid4().hex[:10].upper()}",
                project_id="COMMERCIAL-PIPELINE",
                source_event_id=row.decision_id,
                title=f"Marketing optimalizálás: {row.decision_type}",
                description=row.rationale,
                assignee=assignee,
                priority="high",
                status="open",
            )
        )
    row.status = "executed"
    row.executed_by = email
    row.executed_at = datetime.now(UTC)
    audit(
        db,
        actor=email,
        action="marketing_optimization_executed",
        entity_type="marketing_optimization",
        entity_id=decision_id,
        after={"decision_type": row.decision_type, "campaign_status": campaign.status},
    )
    db.commit()
    db.refresh(row)
    return row


def _ensure_commercial_pipeline(db: Session, responsible: str) -> ProjectRegistry:
    project = db.scalar(
        select(ProjectRegistry).where(ProjectRegistry.project_id == "COMMERCIAL-PIPELINE")
    )
    if project:
        return project
    project = ProjectRegistry(
        project_id="COMMERCIAL-PIPELINE",
        name="Értékesítési lead pipeline",
        project_type="commercial_pipeline",
        status="active",
        responsible=responsible,
        next_action="Minősített leadek értékesítői feldolgozása",
    )
    db.add(project)
    db.flush()
    return project


def create_campaign(
    db: Session,
    user: object,
    *,
    name: str,
    brand_id: str,
    objective: str,
    audience: str,
    channels: list[str],
    budget_net: object,
    currency: str,
    target_leads: int,
    target_cpl_net: object,
    start_date: date,
    end_date: date,
    utm_source: str,
    utm_medium: str,
    utm_campaign: str,
    landing_page_url: str,
) -> MarketingCampaign:
    _role, email = _require(user, CAMPAIGN_ROLES)
    name, brand_id = name.strip(), brand_id.strip().lower()
    objective, audience = objective.strip(), audience.strip()
    channels = sorted({item.strip().lower() for item in channels if item.strip()})
    if not name or not brand_id or len(objective) < 20 or len(audience) < 20:
        raise ValueError("Név, márka, részletes kampánycél és célközönség kötelező.")
    if not channels:
        raise ValueError("Legalább egy kampánycsatorna kötelező.")
    if end_date < start_date:
        raise ValueError("A kampány záródátuma nem előzheti meg a kezdődátumot.")
    if target_leads <= 0:
        raise ValueError("A céllead-számnak pozitívnak kell lennie.")
    normalized_currency = currency.strip().upper()
    if normalized_currency not in {"HUF", "EUR"}:
        raise ValueError("A kampány pénzneme HUF vagy EUR lehet.")
    utm_source, utm_medium = utm_source.strip().lower(), utm_medium.strip().lower()
    utm_campaign = utm_campaign.strip().lower()
    if not utm_source or not utm_medium or not utm_campaign:
        raise ValueError("Az UTM source, medium és campaign mező kötelező.")
    if db.scalar(select(MarketingCampaign).where(MarketingCampaign.utm_campaign == utm_campaign)):
        raise ValueError("Ez az UTM campaign azonosító már használatban van.")
    row = MarketingCampaign(
        campaign_id=f"CMP-{uuid4().hex[:14].upper()}",
        name=name,
        brand_id=brand_id,
        objective=objective,
        audience=audience,
        channels_json=json.dumps(channels, ensure_ascii=False),
        budget_net=_money(budget_net),
        currency=normalized_currency,
        target_leads=target_leads,
        target_cpl_net=_money(target_cpl_net),
        start_date=start_date,
        end_date=end_date,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        landing_page_url=landing_page_url.strip() or None,
        owner_email=email,
        created_by=email,
    )
    db.add(row)
    audit(
        db,
        actor=email,
        action="marketing_campaign_created",
        entity_type="marketing_campaign",
        entity_id=row.campaign_id,
        after={"name": name, "channels": channels, "utm_campaign": utm_campaign},
    )
    db.commit()
    db.refresh(row)
    return row


def submit_campaign(db: Session, campaign_id: str, user: object) -> MarketingCampaign:
    _role, email = _require(user, CAMPAIGN_ROLES)
    row = _campaign(db, campaign_id)
    if row.status != "draft":
        raise ValueError("Csak piszkozat kampány küldhető jóváhagyásra.")
    if row.budget_net <= 0 or row.target_cpl_net <= 0:
        raise ValueError("Pozitív kampánykeret és cél-CPL kötelező.")
    row.status = "review"
    row.submitted_by = email
    audit(
        db,
        actor=email,
        action="marketing_campaign_submitted",
        entity_type="marketing_campaign",
        entity_id=campaign_id,
    )
    db.commit()
    db.refresh(row)
    return row


def approve_campaign(db: Session, campaign_id: str, user: object) -> MarketingCampaign:
    _role, email = _require(user, CAMPAIGN_APPROVERS)
    row = _campaign(db, campaign_id)
    if row.status != "review":
        raise ValueError("Csak ellenőrzés alatt álló kampány hagyható jóvá.")
    if email in {row.created_by.lower(), (row.submitted_by or "").lower()}:
        raise ValueError("A kampány jóváhagyásához független, négy szem elvű döntő kell.")
    row.status = "approved"
    row.approved_by = email
    row.approved_at = datetime.now(UTC)
    audit(
        db,
        actor=email,
        action="marketing_campaign_approved",
        entity_type="marketing_campaign",
        entity_id=campaign_id,
    )
    db.commit()
    db.refresh(row)
    return row


def activate_campaign(db: Session, campaign_id: str, user: object) -> MarketingCampaign:
    _role, email = _require(user, CAMPAIGN_ROLES)
    row = _campaign(db, campaign_id)
    if row.status not in {"approved", "paused"}:
        raise ValueError("Csak jóváhagyott vagy szüneteltetett kampány aktiválható.")
    if not campaign_content_ready(db, campaign_id):
        raise ValueError(
            "Aktiválás csak publikált, élő QA-val jóváhagyott kampányassettel lehetséges."
        )
    row.status = "active"
    row.activated_at = row.activated_at or datetime.now(UTC)
    audit(
        db,
        actor=email,
        action="marketing_campaign_activated",
        entity_type="marketing_campaign",
        entity_id=campaign_id,
    )
    db.commit()
    db.refresh(row)
    return row


def pause_campaign(db: Session, campaign_id: str, user: object) -> MarketingCampaign:
    _role, email = _require(user, CAMPAIGN_ROLES)
    row = _campaign(db, campaign_id)
    if row.status != "active":
        raise ValueError("Csak aktív kampány szüneteltethető.")
    row.status = "paused"
    audit(
        db,
        actor=email,
        action="marketing_campaign_paused",
        entity_type="marketing_campaign",
        entity_id=campaign_id,
    )
    db.commit()
    db.refresh(row)
    return row


def complete_campaign(db: Session, campaign_id: str, user: object) -> MarketingCampaign:
    _role, email = _require(user, CAMPAIGN_ROLES)
    row = _campaign(db, campaign_id)
    if row.status not in {"active", "paused"}:
        raise ValueError("Csak aktív vagy szüneteltetett kampány zárható le.")
    row.status = "completed"
    audit(
        db,
        actor=email,
        action="marketing_campaign_completed",
        entity_type="marketing_campaign",
        entity_id=campaign_id,
    )
    db.commit()
    db.refresh(row)
    return row


def _dedupe_key(email: str, phone: str) -> str:
    normalized_email = email.strip().lower()
    normalized_phone = re.sub(r"\D", "", phone)
    if normalized_email:
        source = f"email:{normalized_email}"
    elif len(normalized_phone) >= 7:
        source = f"phone:{normalized_phone}"
    else:
        raise ValueError("Érvényes e-mail-cím vagy telefonszám kötelező.")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _score(lead: MarketingLead) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if lead.phone:
        score += 10
        reasons.append("telefonos elérhetőség +10")
    budget = Decimal(str(lead.estimated_budget_huf or 0))
    if budget >= 100_000_000:
        score += 30
        reasons.append("100M+ becsült keret +30")
    elif budget >= 50_000_000:
        score += 25
        reasons.append("50M+ becsült keret +25")
    elif budget >= 20_000_000:
        score += 15
        reasons.append("20M+ becsült keret +15")
    months = lead.timeframe_months
    if months is not None and months <= 3:
        score += 25
        reasons.append("0–3 hónapos időtáv +25")
    elif months is not None and months <= 6:
        score += 20
        reasons.append("4–6 hónapos időtáv +20")
    elif months is not None and months <= 12:
        score += 10
        reasons.append("7–12 hónapos időtáv +10")
    if lead.project_location:
        score += 15
        reasons.append("azonosított helyszín +15")
    if lead.intent_summary and len(lead.intent_summary.strip()) >= 30:
        score += 15
        reasons.append("részletes projektigény +15")
    if lead.lead_type == "b2b" and lead.company:
        score += 15
        reasons.append("azonosított B2B vállalat +15")
    return min(score, 100), reasons


def capture_lead(
    db: Session,
    user: object,
    *,
    campaign_id: str,
    source: str,
    channel: str,
    landing_page_url: str,
    utm_source: str,
    utm_medium: str,
    utm_campaign: str,
    utm_content: str,
    full_name: str,
    email: str,
    phone: str,
    company: str,
    lead_type: str,
    project_location: str,
    estimated_budget_huf: object,
    timeframe_months: int | None,
    intent_summary: str,
    privacy_notice_accepted: bool,
    privacy_notice_version: str,
    marketing_consent: bool,
) -> MarketingLead:
    _role, actor = _require(user, LEAD_ROLES)
    if not privacy_notice_accepted or not privacy_notice_version.strip():
        raise ValueError("Az adatkezelési tájékoztató elfogadása és verziója kötelező.")
    if lead_type not in {"b2c", "b2b"}:
        raise ValueError("A lead típusa b2c vagy b2b lehet.")
    if not full_name.strip() or not source.strip() or not channel.strip():
        raise ValueError("A név, forrás és csatorna kötelező.")
    if timeframe_months is not None and timeframe_months < 0:
        raise ValueError("Az időtáv nem lehet negatív.")
    campaign = None
    if campaign_id.strip():
        campaign = _campaign(db, campaign_id.strip())
        if campaign.status != "active":
            raise ValueError("Lead csak aktív kampányhoz attribuálható.")
        supplied_attribution = {
            "utm_source": utm_source.strip().lower(),
            "utm_medium": utm_medium.strip().lower(),
            "utm_campaign": utm_campaign.strip().lower(),
        }
        canonical_attribution = {
            "utm_source": campaign.utm_source,
            "utm_medium": campaign.utm_medium,
            "utm_campaign": campaign.utm_campaign,
        }
        conflicts = [
            key
            for key, value in supplied_attribution.items()
            if value and value != canonical_attribution[key]
        ]
        if conflicts:
            raise ValueError(
                "A kampányazonosító és az UTM-attribúció ellentmondásos: " + ", ".join(conflicts)
            )
        utm_source = campaign.utm_source
        utm_medium = campaign.utm_medium
        utm_campaign = campaign.utm_campaign
        landing_page_url = landing_page_url.strip() or campaign.landing_page_url or ""
    key = _dedupe_key(email, phone)
    normalized_email = email.strip().lower()
    active_suppression = (
        db.scalar(
            select(MailSuppression).where(
                MailSuppression.email == normalized_email,
                MailSuppression.active.is_(True),
            )
        )
        if normalized_email
        else None
    )
    existing = db.scalar(select(MarketingLead).where(MarketingLead.dedupe_key == key))
    if existing:
        existing.signal_count += 1
        existing.last_captured_at = datetime.now(UTC)
        consent_ignored = bool(
            marketing_consent
            and (existing.marketing_consent_withdrawn_at or active_suppression)
        )
        if (
            marketing_consent
            and not existing.marketing_consent_withdrawn_at
            and not active_suppression
        ):
            existing.marketing_consent = True
            existing.marketing_consent_updated_at = datetime.now(UTC)
            existing.marketing_consent_source = source.strip()
            existing.marketing_consent_evidence = "Ismételt, elfogadott leadűrlap-jel."
        existing.campaign_id = existing.campaign_id or (campaign.campaign_id if campaign else None)
        existing.utm_source = existing.utm_source or utm_source.strip() or None
        existing.utm_medium = existing.utm_medium or utm_medium.strip() or None
        existing.utm_campaign = existing.utm_campaign or utm_campaign.strip() or None
        existing.utm_content = existing.utm_content or utm_content.strip() or None
        existing.score, reasons = _score(existing)
        existing.score_reasons_json = json.dumps(reasons, ensure_ascii=False)
        _activity(
            db,
            existing.lead_id,
            "duplicate_signal_merged",
            actor=actor,
            detail={
                "signal_count": existing.signal_count,
                "source": source,
                "consent_signal_ignored_after_withdrawal": consent_ignored,
            },
        )
        db.commit()
        db.refresh(existing)
        return existing
    effective_marketing_consent = bool(marketing_consent and not active_suppression)
    row = MarketingLead(
        lead_id=f"LEAD-{uuid4().hex[:14].upper()}",
        dedupe_key=key,
        campaign_id=campaign.campaign_id if campaign else None,
        source=source.strip(),
        channel=channel.strip().lower(),
        landing_page_url=landing_page_url.strip() or None,
        utm_source=utm_source.strip().lower() or None,
        utm_medium=utm_medium.strip().lower() or None,
        utm_campaign=utm_campaign.strip().lower() or None,
        utm_content=utm_content.strip() or None,
        full_name=full_name.strip(),
        email=normalized_email or None,
        phone=phone.strip() or None,
        company=company.strip() or None,
        lead_type=lead_type,
        project_location=project_location.strip() or None,
        estimated_budget_huf=_money(estimated_budget_huf),
        timeframe_months=timeframe_months,
        intent_summary=intent_summary.strip() or None,
        privacy_notice_accepted=True,
        privacy_notice_version=privacy_notice_version.strip(),
        marketing_consent=effective_marketing_consent,
        marketing_consent_updated_at=(
            datetime.now(UTC) if effective_marketing_consent else None
        ),
        marketing_consent_source=(
            source.strip() if effective_marketing_consent else None
        ),
        marketing_consent_evidence=(
            "Elsődleges, elfogadott leadűrlap-jel."
            if effective_marketing_consent
            else None
        ),
        consent_management_token=token_urlsafe(32),
        status="scored",
    )
    row.score, reasons = _score(row)
    row.score_reasons_json = json.dumps(reasons, ensure_ascii=False)
    db.add(row)
    _activity(
        db,
        row.lead_id,
        "captured_and_scored",
        actor=actor,
        detail={
            "score": row.score,
            "campaign_id": row.campaign_id,
            "source": row.source,
            "consent_signal_ignored_by_suppression": bool(
                marketing_consent and active_suppression
            ),
        },
    )
    audit(
        db,
        actor=actor,
        action="marketing_lead_captured",
        entity_type="marketing_lead",
        entity_id=row.lead_id,
        after={"score": row.score, "campaign_id": row.campaign_id},
    )
    db.commit()
    db.refresh(row)
    return row


def qualify_lead(
    db: Session, lead_id: str, user: object, *, note: str, override_reason: str
) -> MarketingLead:
    _role, email = _require(user, CAMPAIGN_ROLES)
    row = _lead(db, lead_id)
    if row.status not in {"scored", "sales_rejected"}:
        raise ValueError("Csak pontozott vagy értékesítésről visszaadott lead minősíthető.")
    if len(note.strip()) < 10:
        raise ValueError("A minősítési megjegyzés kötelező.")
    if row.score < 60 and len(override_reason.strip()) < 20:
        raise ValueError("60 pont alatt legalább 20 karakteres MQL-kivételindoklás kell.")
    row.status = "marketing_qualified"
    row.qualification_note = note.strip()
    row.qualified_at = datetime.now(UTC)
    _activity(
        db,
        lead_id,
        "marketing_qualified",
        actor=email,
        detail={"score": row.score, "note": note, "override_reason": override_reason},
    )
    audit(
        db,
        actor=email,
        action="marketing_lead_qualified",
        entity_type="marketing_lead",
        entity_id=lead_id,
        after={"score": row.score, "override_reason": override_reason.strip()},
    )
    db.commit()
    db.refresh(row)
    return row


def handoff_lead_to_crm(
    db: Session, lead_id: str, user: object, *, assigned_sales_email: str
) -> MarketingLead:
    _role, email = _require(user, CAMPAIGN_ROLES)
    row = _lead(db, lead_id)
    if row.status != "marketing_qualified":
        raise ValueError("Csak marketing qualified lead adható át a CRM-nek.")
    assignee = assigned_sales_email.strip().lower()
    if "@" not in assignee:
        raise ValueError("Érvényes értékesítői e-mail-cím kötelező.")
    canonical_id = f"CAN-{row.lead_id}"
    payload = {
        "id": row.lead_id,
        "name": row.full_name,
        "email": row.email,
        "phone": row.phone,
        "company": row.company,
        "stage": "marketing_qualified",
        "source": row.source,
        "campaignId": row.campaign_id,
        "score": row.score,
        "estimatedBudgetHuf": str(row.estimated_budget_huf),
        "timeframeMonths": row.timeframe_months,
        "projectLocation": row.project_location,
        "marketingConsent": row.marketing_consent,
        "assignedSalesEmail": assignee,
    }
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.domain == "customer",
            EnterpriseCanonicalRecord.entity_type == "lead",
            EnterpriseCanonicalRecord.external_key == row.lead_id,
        )
    )
    if not canonical:
        canonical = EnterpriseCanonicalRecord(
            record_id=canonical_id,
            domain="customer",
            entity_type="lead",
            external_key=row.lead_id,
            canonical_name=row.full_name,
            target_module="crm",
        )
        db.add(canonical)
    canonical.status = "active"
    canonical.data_json = json.dumps(payload, ensure_ascii=False, default=str)
    canonical.provenance_json = json.dumps(
        {
            "source": "marketing-automation",
            "leadId": row.lead_id,
            "capturedAt": row.captured_at.isoformat(),
        },
        ensure_ascii=False,
    )
    crm_record_id = f"CRM-{row.lead_id}"
    crm_record = db.scalar(
        select(ModuleBusinessRecord).where(ModuleBusinessRecord.record_id == crm_record_id)
    )
    if not crm_record:
        crm_record = ModuleBusinessRecord(
            record_id=crm_record_id,
            module_key="crm",
            record_type="Lead",
            title=row.full_name,
            description=row.intent_summary,
            status="qualified",
            customer_reference=row.lead_id,
            assignee=assignee,
            priority="high" if row.score >= 80 else "normal",
            amount_huf=row.estimated_budget_huf,
            data_json=json.dumps(payload, ensure_ascii=False, default=str),
            created_by=email,
            updated_by=email,
        )
        db.add(crm_record)
    _ensure_commercial_pipeline(db, assignee)
    db.add(
        TaskRecord(
            task_id=f"TASK-LEAD-{uuid4().hex[:12].upper()}",
            project_id="COMMERCIAL-PIPELINE",
            source_event_id=row.lead_id,
            title=f"Új minősített lead feldolgozása: {row.full_name}",
            description=row.intent_summary,
            assignee=assignee,
            priority="high" if row.score >= 80 else "normal",
            status="open",
        )
    )
    row.status = "crm_handoff"
    row.assigned_sales_email = assignee
    row.crm_record_id = crm_record_id
    row.handed_off_at = datetime.now(UTC)
    _activity(
        db,
        lead_id,
        "crm_handoff",
        actor=email,
        detail={"crm_record_id": crm_record_id, "assigned_sales_email": assignee},
    )
    audit(
        db,
        actor=email,
        action="marketing_lead_crm_handoff",
        entity_type="marketing_lead",
        entity_id=lead_id,
        after={"crm_record_id": crm_record_id, "canonical_record_id": canonical_id},
    )
    db.commit()
    db.refresh(row)
    return row


def decide_sales_lead(
    db: Session, lead_id: str, user: object, *, decision: str, note: str
) -> MarketingLead:
    _role, email = _require(user, SALES_ROLES)
    row = _lead(db, lead_id)
    if row.status != "crm_handoff":
        raise ValueError("Csak CRM-nek átadott leadről hozható értékesítői döntés.")
    if row.assigned_sales_email and _role == "sales" and row.assigned_sales_email != email:
        raise PermissionError("A lead másik értékesítőhöz van rendelve.")
    if decision not in {"accept", "reject"}:
        raise ValueError("Az értékesítői döntés accept vagy reject lehet.")
    if len(note.strip()) < 10:
        raise ValueError("Az értékesítői döntés indoklása kötelező.")
    row.status = "sales_accepted" if decision == "accept" else "sales_rejected"
    if decision == "accept":
        row.accepted_at = datetime.now(UTC)
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.source_event_id == row.lead_id,
            TaskRecord.assignee == email,
            TaskRecord.status != "done",
        )
    ).all():
        task.status = "done"
    if row.crm_record_id:
        crm_record = db.scalar(
            select(ModuleBusinessRecord).where(ModuleBusinessRecord.record_id == row.crm_record_id)
        )
        if crm_record:
            crm_record.status = "active" if decision == "accept" else "on_hold"
            crm_record.updated_by = email
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.domain == "customer",
            EnterpriseCanonicalRecord.entity_type == "lead",
            EnterpriseCanonicalRecord.external_key == row.lead_id,
        )
    )
    if canonical:
        payload = json.loads(canonical.data_json or "{}")
        payload["stage"] = row.status
        payload["salesDecisionNote"] = note.strip()
        canonical.data_json = json.dumps(payload, ensure_ascii=False, default=str)
    _activity(
        db,
        lead_id,
        f"sales_{decision}",
        actor=email,
        detail={"note": note.strip()},
    )
    audit(
        db,
        actor=email,
        action=f"marketing_lead_sales_{decision}",
        entity_type="marketing_lead",
        entity_id=lead_id,
        after={"status": row.status, "note": note.strip()},
    )
    db.commit()
    db.refresh(row)
    return row
