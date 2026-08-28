from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..growth_ops.models import GrowthSignal, OutreachMessage
from ..models import (
    BuildConfigCase,
    BuildConfigGate,
    BuildConfigVersion,
    HouseCatalogPlan,
    HouseCatalogVersion,
    ModuleRegistry,
    OutboxMessage,
    PlotCheckCase,
)
from .models import (
    LandAuthorityGrant,
    LandListingPackage,
    LandOpportunity,
    LandPublicationAttempt,
)
from .registry import LandRegistryError, Portal, PortalRegistry
from .schemas import (
    AuthorityGrantIn,
    DealIn,
    ListingPackageIn,
    PackageApprovalIn,
    PublicationConfirmationIn,
    PublicationRequestIn,
    SourceVerificationIn,
)

CORE_AUTHORITY_SCOPES = {"advertising", "media_use", "pricing", "withdrawal"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    content = value if isinstance(value, str) else _json(value)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:20].upper()}"


def _opportunity(db: Session, opportunity_id: str) -> LandOpportunity:
    row = db.scalar(select(LandOpportunity).where(LandOpportunity.opportunity_id == opportunity_id))
    if not row:
        raise KeyError(opportunity_id)
    return row


def _grant(db: Session, grant_id: str) -> LandAuthorityGrant:
    row = db.scalar(select(LandAuthorityGrant).where(LandAuthorityGrant.grant_id == grant_id))
    if not row:
        raise KeyError(grant_id)
    return row


def _package(db: Session, package_id: str) -> LandListingPackage:
    row = db.scalar(select(LandListingPackage).where(LandListingPackage.package_id == package_id))
    if not row:
        raise KeyError(package_id)
    return row


def _active_grant(grant: LandAuthorityGrant, *, now: datetime | None = None) -> bool:
    current = now or utcnow()
    return grant.status == "ACTIVE" and _aware(grant.valid_from) <= current < _aware(
        grant.valid_until
    )


def _scopes(grant: LandAuthorityGrant) -> set[str]:
    value = json.loads(grant.scopes_json)
    return {str(item) for item in value} if isinstance(value, list) else set()


def opportunity_payload(row: LandOpportunity) -> dict[str, Any]:
    return {
        "opportunity_id": row.opportunity_id,
        "source_signal_id": row.source_signal_id,
        "source_code": row.source_code,
        "external_key": row.external_key,
        "source_content_sha256": row.source_content_sha256,
        "source_url": row.source_url,
        "title": row.title,
        "location": row.location,
        "state": row.state,
        "listing_active": row.listing_active,
        "version": row.version,
        "updated_at": row.updated_at,
    }


def package_payload(row: LandListingPackage) -> dict[str, Any]:
    return {
        "package_id": row.package_id,
        "opportunity_id": row.opportunity_id,
        "authority_grant_id": row.authority_grant_id,
        "plotcheck_case_id": row.plotcheck_case_id,
        "house_id": row.house_id,
        "catalog_version_id": row.catalog_version_id,
        "buildconfig_case_id": row.buildconfig_case_id,
        "buildconfig_version_id": row.buildconfig_version_id,
        "version": row.version,
        "payload": json.loads(row.payload_json),
        "payload_sha256": row.payload_sha256,
        "status": row.status,
        "created_by": row.created_by,
        "reviewed_by": row.reviewed_by,
        "approved_at": row.approved_at,
    }


def attempt_payload(row: LandPublicationAttempt) -> dict[str, Any]:
    return {
        "attempt_id": row.attempt_id,
        "opportunity_id": row.opportunity_id,
        "package_id": row.package_id,
        "channel": row.channel,
        "action": row.action,
        "status": row.status,
        "blocked_reason": row.blocked_reason,
        "outbox_message_id": row.outbox_message_id,
        "external_id": row.external_id,
        "public_url": row.public_url,
        "proof_sha256": row.proof_sha256,
    }


def sync_growth_plot_signals(db: Session) -> dict[str, int]:
    signals = db.scalars(
        select(GrowthSignal)
        .where(GrowthSignal.signal_type == "residential_building_plot")
        .order_by(GrowthSignal.id)
    ).all()
    created = updated = 0
    for signal in signals:
        row = db.scalar(
            select(LandOpportunity).where(LandOpportunity.source_signal_id == signal.signal_id)
        )
        if not row:
            title = (signal.company_name or signal.summary).strip()[:500]
            row = LandOpportunity(
                opportunity_id=_id("LAND"),
                source_signal_id=signal.signal_id,
                source_code=signal.source_id,
                external_key=signal.external_key,
                source_content_sha256=signal.source_payload_hash,
                source_url=signal.evidence_url,
                title=title,
                location=signal.location,
                property_fingerprint=_sha(
                    {"source": signal.source_id, "external_key": signal.external_key}
                ),
                state=(
                    "REPLIED"
                    if signal.status == "responded"
                    else "CONTACTED"
                    if signal.status == "contacted"
                    else "DISCOVERED"
                ),
            )
            db.add(row)
            created += 1
            continue
        changed = False
        if row.source_content_sha256 != signal.source_payload_hash:
            row.source_content_sha256 = signal.source_payload_hash
            row.version += 1
            row.source_verified_by = None
            row.source_verified_at = None
            row.source_verification_note = None
            if row.state not in {"WITHDRAWN", "CLOSED_NO_DEAL"}:
                row.state = "DISCOVERED"
            changed = True
        if signal.status == "responded" and row.state in {
            "DISCOVERED",
            "SOURCE_VERIFIED",
            "CONTACTED",
        }:
            row.state = "REPLIED"
            changed = True
        elif signal.status == "contacted" and row.state in {"DISCOVERED", "SOURCE_VERIFIED"}:
            row.state = "CONTACTED"
            changed = True
        updated += int(changed)
    db.commit()
    return {"seen": len(signals), "created": created, "updated": updated}


def verify_source(db: Session, opportunity_id: str, data: SourceVerificationIn) -> LandOpportunity:
    row = _opportunity(db, opportunity_id)
    if not row.listing_active:
        raise ValueError("inactive source listing")
    if row.source_content_sha256 != data.expected_source_sha256:
        raise ValueError("source snapshot changed; re-review required")
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.source_signal_id))
    if not signal or signal.evidence_url != row.source_url:
        raise ValueError("source provenance mismatch")
    if row.state not in {"DISCOVERED", "SOURCE_VERIFIED", "CONTACTED", "REPLIED"}:
        raise ValueError("source verification is not valid in the current state")
    row.source_verified_by = data.actor
    row.source_verified_at = utcnow()
    row.source_verification_note = data.note
    if row.state == "DISCOVERED":
        row.state = "SOURCE_VERIFIED"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def record_deal(db: Session, opportunity_id: str, data: DealIn) -> LandOpportunity:
    row = _opportunity(db, opportunity_id)
    if row.state not in {"SOURCE_VERIFIED", "REPLIED"} or not row.source_verified_at:
        raise ValueError("verified source and an evidenced response are required")
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.source_signal_id))
    response = db.scalar(
        select(OutreachMessage).where(
            OutreachMessage.signal_id == row.source_signal_id,
            OutreachMessage.status == "responded",
        )
    )
    if not signal or signal.status != "responded" or not response:
        raise ValueError("DEAL requires a recorded response in the common Growth Ops ledger")
    if not row.listing_active:
        raise ValueError("inactive listing cannot become a DEAL")
    row.deal_evidence_ref = data.evidence_ref
    row.deal_evidence_sha256 = data.evidence_sha256
    row.deal_recorded_by = data.actor
    row.deal_recorded_at = utcnow()
    row.state = "DEAL_VALIDATED"
    db.commit()
    db.refresh(row)
    return row


def grant_authority(db: Session, opportunity_id: str, data: AuthorityGrantIn) -> LandAuthorityGrant:
    row = _opportunity(db, opportunity_id)
    if row.state != "DEAL_VALIDATED":
        raise ValueError("validated DEAL is required")
    if data.created_by.casefold() == data.approved_by.casefold():
        raise ValueError("four-eyes approval is required for advertising authority")
    if row.deal_recorded_by and data.approved_by.casefold() == row.deal_recorded_by.casefold():
        raise ValueError("DEAL recorder cannot approve advertising authority")
    if _aware(data.valid_until) <= _aware(data.valid_from) or _aware(data.valid_until) <= utcnow():
        raise ValueError("authority validity interval is invalid")
    scopes = set(data.scopes)
    if not CORE_AUTHORITY_SCOPES.issubset(scopes):
        missing = sorted(CORE_AUTHORITY_SCOPES - scopes)
        raise ValueError(f"missing authority scopes: {', '.join(missing)}")
    grant = LandAuthorityGrant(
        grant_id=_id("AUTH"),
        opportunity_id=opportunity_id,
        grantor_reference=data.grantor_reference,
        scopes_json=_json(sorted(scopes)),
        evidence_ref=data.evidence_ref,
        evidence_sha256=data.evidence_sha256,
        valid_from=_aware(data.valid_from),
        valid_until=_aware(data.valid_until),
        status="ACTIVE",
        created_by=data.created_by,
        approved_by=data.approved_by,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant


def _cash_buffer_percent(version: BuildConfigVersion) -> Decimal:
    try:
        value = json.loads(version.pricing_snapshot_json)
        return Decimal(str(value.get("cash_buffer_percent")))
    except (json.JSONDecodeError, TypeError, ValueError, ArithmeticError):
        return Decimal("-1")


def create_listing_package(
    db: Session, opportunity_id: str, data: ListingPackageIn
) -> LandListingPackage:
    opportunity = _opportunity(db, opportunity_id)
    if opportunity.state not in {"DEAL_VALIDATED", "PACKAGE_READY"}:
        raise ValueError("validated DEAL is required")
    if not opportunity.listing_active:
        raise ValueError("inactive source listing")
    grant = _grant(db, data.authority_grant_id)
    if grant.opportunity_id != opportunity_id or not _active_grant(grant):
        raise ValueError("active authority for this opportunity is required")
    if not CORE_AUTHORITY_SCOPES.issubset(_scopes(grant)):
        raise ValueError("authority scope is incomplete")

    plot = db.scalar(select(PlotCheckCase).where(PlotCheckCase.case_id == data.plotcheck_case_id))
    if (
        not plot
        or plot.status not in {"fit", "fit_with_conditions"}
        or not plot.finalized_at
        or plot.house_id != data.house_id
    ):
        raise ValueError("finalized FIT PlotCheck bound to the selected house is required")
    house = db.scalar(select(HouseCatalogPlan).where(HouseCatalogPlan.house_id == data.house_id))
    catalog = db.scalar(
        select(HouseCatalogVersion).where(
            HouseCatalogVersion.catalog_version_id == data.catalog_version_id
        )
    )
    if (
        not house
        or house.lifecycle_status != "active"
        or not catalog
        or catalog.house_id != house.house_id
        or catalog.status != "released"
    ):
        raise ValueError("released active house-catalog version is required")
    config_case = db.scalar(
        select(BuildConfigCase).where(BuildConfigCase.case_id == data.buildconfig_case_id)
    )
    config_version = db.scalar(
        select(BuildConfigVersion).where(
            BuildConfigVersion.version_id == data.buildconfig_version_id
        )
    )
    if (
        not config_case
        or config_case.status != "approved"
        or config_case.current_version_id != data.buildconfig_version_id
        or not config_version
        or config_version.case_id != config_case.case_id
        or config_version.status != "approved"
    ):
        raise ValueError("approved current BuildConfig version is required")
    gates = {
        gate.gate_key: gate.decision
        for gate in db.scalars(
            select(BuildConfigGate).where(
                BuildConfigGate.version_id == data.buildconfig_version_id,
                BuildConfigGate.gate_key.in_(["pricing", "margin", "cashflow"]),
            )
        ).all()
    }
    if any(gates.get(key) != "approved" for key in ("pricing", "margin", "cashflow")):
        raise ValueError("approved pricing, margin and cashflow gates are required")
    if Decimal(config_version.margin_percent) < Decimal("35"):
        raise ValueError("minimum 35% margin gate failed")
    if _cash_buffer_percent(config_version) < Decimal("20"):
        raise ValueError("minimum 20% cash buffer gate failed")

    version = (
        int(
            db.scalar(
                select(func.coalesce(func.max(LandListingPackage.version), 0)).where(
                    LandListingPackage.opportunity_id == opportunity_id
                )
            )
            or 0
        )
        + 1
    )
    total_price = int(data.plot_price_huf + int(Decimal(config_version.gross_price_huf)))
    payload = {
        "schema_version": "land-listing/1.0",
        "opportunity_id": opportunity_id,
        "source": {
            "url": opportunity.source_url,
            "sha256": opportunity.source_content_sha256,
            "listing_active": opportunity.listing_active,
        },
        "plot": {
            "location": opportunity.location,
            "plotcheck_case_id": plot.case_id,
            "plot_price_huf": data.plot_price_huf,
        },
        "house": {
            "house_id": house.house_id,
            "catalog_version_id": catalog.catalog_version_id,
            "name": house.canonical_name,
            "gross_area_m2": str(catalog.gross_area_m2),
            "rooms": catalog.rooms,
            "buildconfig_version_id": config_version.version_id,
            "house_gross_price_huf": int(Decimal(config_version.gross_price_huf)),
        },
        "advertisement": {
            "headline": (
                f"Építési telek {opportunity.location or ''} – {house.canonical_name} típusházzal"
            ).strip(),
            "description": (
                f"Ellenőrzött építési telek és a {house.canonical_name} típusház összeállítása. "
                "A megjelölt ár a telek és a jóváhagyott műszaki konfiguráció pillanatfelvétele; "
                "a végleges műszaki tartalom és szerződés külön egyeztetés tárgya."
            ),
            "total_indicative_price_huf": total_price,
            "media_asset_ids": data.media_asset_ids,
            "contact_route": data.contact_route,
        },
        "authority": {
            "grant_id": grant.grant_id,
            "evidence_sha256": grant.evidence_sha256,
            "valid_until": _aware(grant.valid_until).isoformat(),
            "scopes": sorted(_scopes(grant)),
        },
        "commercial_gates": {
            "margin_percent": str(config_version.margin_percent),
            "cash_buffer_percent": str(_cash_buffer_percent(config_version)),
        },
    }
    serialized = _json(payload)
    package = LandListingPackage(
        package_id=_id("LPKG"),
        opportunity_id=opportunity_id,
        authority_grant_id=grant.grant_id,
        plotcheck_case_id=plot.case_id,
        house_id=house.house_id,
        catalog_version_id=catalog.catalog_version_id,
        buildconfig_case_id=config_case.case_id,
        buildconfig_version_id=config_version.version_id,
        version=version,
        payload_json=serialized,
        payload_sha256=_sha(serialized),
        status="READY",
        created_by=data.actor,
    )
    db.add(package)
    opportunity.state = "PACKAGE_READY"
    db.commit()
    db.refresh(package)
    return package


def approve_package(db: Session, package_id: str, data: PackageApprovalIn) -> LandListingPackage:
    package = _package(db, package_id)
    opportunity = _opportunity(db, package.opportunity_id)
    grant = _grant(db, package.authority_grant_id)
    if package.status != "READY" or opportunity.state != "PACKAGE_READY":
        raise ValueError("ready package is required")
    if package.created_by.casefold() == data.actor.casefold():
        raise ValueError("package creator cannot approve publication")
    if package.payload_sha256 != data.expected_payload_sha256:
        raise ValueError("package payload changed; re-review required")
    if not opportunity.listing_active or not _active_grant(grant):
        raise ValueError("listing or advertising authority is no longer active")
    package.status = "APPROVED"
    package.reviewed_by = data.actor
    package.review_note = data.note
    package.approved_at = utcnow()
    opportunity.state = "PUBLISH_APPROVED"
    db.commit()
    db.refresh(package)
    return package


def _channel_scope(portal: Portal) -> str:
    return "website" if portal.key == "imperial_plot_finder" else "portals"


def _adapter_ready(db: Session, portal: Portal) -> bool:
    if not portal.adapter_module:
        return False
    module = db.scalar(
        select(ModuleRegistry).where(ModuleRegistry.module_key == portal.adapter_module)
    )
    return bool(
        module
        and module.integration_status == "healthy"
        and module.last_integration_test_status == "passed"
    )


def _queue_publication(
    db: Session,
    *,
    portal: Portal,
    attempt: LandPublicationAttempt,
    package: LandListingPackage,
) -> None:
    message = OutboxMessage(
        message_id=_id("MSG-LAND"),
        destination_module=portal.adapter_module or "blocked",
        endpoint="/land-listings/publish",
        payload_json=_json(
            {
                "action": "PUBLISH",
                "attempt_id": attempt.attempt_id,
                "idempotency_key": attempt.idempotency_key,
                "channel": attempt.channel,
                "payload": json.loads(package.payload_json),
                "payload_sha256": package.payload_sha256,
            }
        ),
        status="pending",
        max_retries=5,
        next_attempt_at=utcnow(),
    )
    db.add(message)
    attempt.status = "QUEUED"
    attempt.blocked_reason = None
    attempt.outbox_message_id = message.message_id


def request_publication(
    db: Session, package_id: str, data: PublicationRequestIn
) -> list[LandPublicationAttempt]:
    package = _package(db, package_id)
    opportunity = _opportunity(db, package.opportunity_id)
    grant = _grant(db, package.authority_grant_id)
    if package.status != "APPROVED" or opportunity.state != "PUBLISH_APPROVED":
        raise ValueError("approved package is required")
    if not opportunity.listing_active or not _active_grant(grant):
        raise ValueError("listing or advertising authority is no longer active")
    registry = PortalRegistry.load()
    result: list[LandPublicationAttempt] = []
    for channel in data.channels:
        portal = registry.portal(channel)
        idempotency = _sha(
            {"package_sha256": package.payload_sha256, "channel": channel, "action": "PUBLISH"}
        )
        allowed = (
            portal.permits("publish")
            and _channel_scope(portal) in _scopes(grant)
            and _adapter_ready(db, portal)
        )
        existing = db.scalar(
            select(LandPublicationAttempt).where(
                LandPublicationAttempt.idempotency_key == idempotency
            )
        )
        if existing:
            if existing.status == "BLOCKED" and allowed:
                _queue_publication(
                    db,
                    portal=portal,
                    attempt=existing,
                    package=package,
                )
            result.append(existing)
            continue
        attempt = LandPublicationAttempt(
            attempt_id=_id("LPUB"),
            opportunity_id=opportunity.opportunity_id,
            package_id=package.package_id,
            channel=channel,
            action="PUBLISH",
            idempotency_key=idempotency,
            payload_sha256=package.payload_sha256,
            status="QUEUED" if allowed else "BLOCKED",
            blocked_reason=(
                None if allowed else "licensed_adapter_or_channel_authority_not_enabled"
            ),
            created_by=data.actor,
        )
        db.add(attempt)
        db.flush()
        if allowed:
            _queue_publication(
                db,
                portal=portal,
                attempt=attempt,
                package=package,
            )
        result.append(attempt)
    db.commit()
    return result


def _validate_proof_url(portal: Portal, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("publication proof requires an HTTPS public URL")
    host = parsed.hostname.casefold().rstrip(".")
    if not any(host == domain or host.endswith(f".{domain}") for domain in portal.domains):
        raise ValueError("publication proof URL does not belong to the target channel")


def confirm_publication(
    db: Session, attempt_id: str, data: PublicationConfirmationIn
) -> LandPublicationAttempt:
    attempt = db.scalar(
        select(LandPublicationAttempt).where(LandPublicationAttempt.attempt_id == attempt_id)
    )
    if not attempt:
        raise KeyError(attempt_id)
    if attempt.status not in {"QUEUED", "EXPORTED", "UNKNOWN", "WITHDRAWAL_REQUIRED"}:
        raise ValueError("attempt is not awaiting a verifiable result")
    portal = PortalRegistry.load().portal(attempt.channel)
    _validate_proof_url(portal, data.public_url)
    proof = {
        "actor": data.actor,
        "external_id": data.external_id,
        "public_url": data.public_url,
        "readback": data.proof,
        "confirmed_at": utcnow().isoformat(),
    }
    attempt.external_id = data.external_id
    attempt.public_url = data.public_url
    attempt.proof_json = _json(proof)
    attempt.proof_sha256 = _sha(proof)
    attempt.status = "SUCCEEDED" if attempt.action == "PUBLISH" else "WITHDRAWN"
    attempt.completed_at = utcnow()
    opportunity = _opportunity(db, attempt.opportunity_id)
    if attempt.action == "PUBLISH":
        all_attempts = db.scalars(
            select(LandPublicationAttempt).where(
                LandPublicationAttempt.package_id == attempt.package_id,
                LandPublicationAttempt.action == "PUBLISH",
            )
        ).all()
        statuses = {row.status for row in all_attempts}
        opportunity.state = "PUBLISHED" if statuses == {"SUCCEEDED"} else "PARTIAL_PUBLISH"
    else:
        live_channels = db.scalars(
            select(LandPublicationAttempt).where(
                LandPublicationAttempt.opportunity_id == attempt.opportunity_id,
                LandPublicationAttempt.action == "WITHDRAW",
            )
        ).all()
        if live_channels and all(row.status == "WITHDRAWN" for row in live_channels):
            opportunity.state = "WITHDRAWN"
    db.commit()
    db.refresh(attempt)
    return attempt


def _withdrawal_attempt(
    db: Session,
    *,
    opportunity: LandOpportunity,
    publication: LandPublicationAttempt,
    reason: str,
    registry: PortalRegistry,
) -> LandPublicationAttempt:
    idempotency = _sha(
        {
            "publication_attempt": publication.attempt_id,
            "channel": publication.channel,
            "action": "WITHDRAW",
        }
    )
    existing = db.scalar(
        select(LandPublicationAttempt).where(LandPublicationAttempt.idempotency_key == idempotency)
    )
    if existing:
        return existing
    portal = registry.portal(publication.channel)
    allowed = portal.permits("withdraw") and _adapter_ready(db, portal)
    attempt = LandPublicationAttempt(
        attempt_id=_id("LWD"),
        opportunity_id=opportunity.opportunity_id,
        package_id=publication.package_id,
        channel=publication.channel,
        action="WITHDRAW",
        idempotency_key=idempotency,
        payload_sha256=publication.payload_sha256,
        status="QUEUED" if allowed else "WITHDRAWAL_REQUIRED",
        blocked_reason=None if allowed else reason,
        external_id=publication.external_id,
        public_url=publication.public_url,
        created_by="land-authority-scanner",
    )
    db.add(attempt)
    db.flush()
    if allowed:
        message = OutboxMessage(
            message_id=_id("MSG-LAND"),
            destination_module=portal.adapter_module or "blocked",
            endpoint="/land-listings/withdraw",
            payload_json=_json(
                {
                    "action": "WITHDRAW",
                    "attempt_id": attempt.attempt_id,
                    "publication_attempt_id": publication.attempt_id,
                    "idempotency_key": idempotency,
                    "channel": publication.channel,
                    "external_id": publication.external_id,
                    "public_url": publication.public_url,
                    "reason": reason,
                }
            ),
            status="pending",
            max_retries=10,
            next_attempt_at=utcnow(),
        )
        db.add(message)
        attempt.outbox_message_id = message.message_id
    return attempt


def scan_authority_expiry(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    current = now or utcnow()
    expired = 0
    for grant in db.scalars(
        select(LandAuthorityGrant).where(LandAuthorityGrant.status == "ACTIVE")
    ).all():
        if _aware(grant.valid_until) <= current:
            grant.status = "EXPIRED"
            expired += 1
    registry = PortalRegistry.load()
    affected = attempts = 0
    opportunities = db.scalars(select(LandOpportunity)).all()
    for opportunity in opportunities:
        active = any(
            _active_grant(grant, now=current)
            for grant in db.scalars(
                select(LandAuthorityGrant).where(
                    LandAuthorityGrant.opportunity_id == opportunity.opportunity_id
                )
            ).all()
        )
        if opportunity.listing_active and active:
            continue
        publications = db.scalars(
            select(LandPublicationAttempt).where(
                LandPublicationAttempt.opportunity_id == opportunity.opportunity_id,
                LandPublicationAttempt.action == "PUBLISH",
                LandPublicationAttempt.status == "SUCCEEDED",
            )
        ).all()
        if not publications:
            continue
        opportunity.state = "TAKEDOWN_REQUIRED"
        affected += 1
        reason = (
            "source_listing_inactive" if not opportunity.listing_active else "authority_inactive"
        )
        for publication in publications:
            before = db.scalar(
                select(LandPublicationAttempt.id).where(
                    LandPublicationAttempt.idempotency_key
                    == _sha(
                        {
                            "publication_attempt": publication.attempt_id,
                            "channel": publication.channel,
                            "action": "WITHDRAW",
                        }
                    )
                )
            )
            _withdrawal_attempt(
                db,
                opportunity=opportunity,
                publication=publication,
                reason=reason,
                registry=registry,
            )
            attempts += int(before is None)
    db.commit()
    return {"expired_grants": expired, "affected_opportunities": affected, "withdrawals": attempts}


def revoke_authority(db: Session, grant_id: str, *, actor: str, reason: str) -> LandAuthorityGrant:
    grant = _grant(db, grant_id)
    if grant.status != "ACTIVE":
        raise ValueError("only active authority can be revoked")
    grant.status = "REVOKED"
    grant.revoked_by = actor
    grant.revoked_at = utcnow()
    grant.revocation_reason = reason
    db.commit()
    scan_authority_expiry(db)
    db.refresh(grant)
    return grant


def set_listing_active(
    db: Session, opportunity_id: str, *, active: bool, evidence_ref: str, actor: str
) -> LandOpportunity:
    opportunity = _opportunity(db, opportunity_id)
    opportunity.listing_active = active
    opportunity.source_status_evidence_ref = evidence_ref
    opportunity.source_status_changed_by = actor
    opportunity.source_status_changed_at = utcnow()
    db.commit()
    if not active:
        scan_authority_expiry(db)
    db.refresh(opportunity)
    return opportunity


def readiness(db: Session) -> tuple[bool, dict[str, Any]]:
    try:
        db.execute(select(func.count()).select_from(LandOpportunity))
        database = "ok"
    except Exception:
        db.rollback()
        database = "failed"
    try:
        loaded_registry = PortalRegistry.load()
        registry = loaded_registry.readiness()
        adapters = {
            portal.key: {
                "module": portal.adapter_module,
                "ready": _adapter_ready(db, portal),
            }
            for portal in loaded_registry.portals.values()
            if portal.discovery_enabled or portal.publish_enabled
        }
        registry_state: dict[str, Any] = {
            "status": "ok",
            **registry,
            "adapters": adapters,
        }
    except LandRegistryError as exc:
        registry_state = {"status": "failed", "error": str(exc)}
    adapters_ready = all(
        bool(value.get("ready")) for value in registry_state.get("adapters", {}).values()
    )
    live_discovery = bool(registry_state.get("discovery_enabled"))
    ready = (
        database == "ok"
        and registry_state.get("status") == "ok"
        and adapters_ready
        and live_discovery
    )
    return ready, {
        "database": database,
        "registry": registry_state,
        "live_external_writes": bool(registry_state.get("publishing_enabled")),
        "live_discovery": live_discovery,
        "blocking_reasons": (
            [] if live_discovery else ["no_licensed_land_discovery_adapter_enabled"]
        ),
        "safety": {
            "generic_portal_scraping": "blocked",
            "natural_person_email_without_consent": "blocked_by_growth_ops",
            "four_eyes_package_release": "required",
            "publication_readback_proof": "required",
            "automatic_takedown_scan": "enabled",
        },
    }
