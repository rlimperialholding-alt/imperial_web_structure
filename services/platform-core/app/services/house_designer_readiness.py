from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    BookingExperienceVersion,
    HouseDesignerAdapterRegistration,
    HouseDesignerEntitlement,
    HousePlanRecord,
    ModuleRegistry,
    RegulatoryRuleSet,
    ReleaseRecord,
    ReservationOfferVersion,
)
from .house_designer import HouseDesignerError
from .house_designer_privacy import site_encryption_ready
from .house_designer_submission import (
    HOUSE_DESIGN_NOTICE_VERSION,
    HOUSE_DESIGN_TERMS_VERSION,
)
from .regulatory_compliance import _binding_issue, _ruleset_binding_state
from .regulatory_rule_schema import (
    RULE_CATEGORIES,
    RULE_SCHEMA_VERSION,
    RegulatoryRuleSchemaError,
    normalize_declarative_rules,
)

REQUIRED_ADAPTERS = ("pricing", "capacity", "render")
REQUIRED_INTEGRATIONS = ("crm", "my-imperial", "smart-calendar")
ACTIVATION_AUTHORS = frozenset({"designer", "technical-prep", "managing-director", "owner"})
ACTIVATION_REVIEWERS = frozenset({"managing-director", "owner"})
SANDBOX_MANAGERS = ACTIVATION_REVIEWERS
ADAPTER_HEALTH_MAX_AGE = timedelta(minutes=15)


def house_designer_release_readiness(
    db: Session, *, tenant_id: str, brand_id: str
) -> dict[str, Any]:
    template_count = int(
        db.scalar(
            select(func.count(HousePlanRecord.id)).where(
                HousePlanRecord.status.in_(("approved", "catalog_ready", "published"))
            )
        )
        or 0
    )
    now = datetime.now(UTC)
    approved_rulesets = db.scalars(
        select(RegulatoryRuleSet).where(
            RegulatoryRuleSet.status == "APPROVED",
            RegulatoryRuleSet.effective_from <= now,
            or_(
                RegulatoryRuleSet.effective_to.is_(None),
                RegulatoryRuleSet.effective_to >= now,
            ),
        )
    ).all()
    binding_valid_rulesets = [
        row
        for row in approved_rulesets
        if _binding_issue(_ruleset_binding_state(db, row, now)) is None
    ]
    ruleset_count = len(binding_valid_rulesets)
    ruleset_coverage = {
        row.ruleset_id: sorted(_ruleset_categories(row)) for row in binding_valid_rulesets
    }
    production_ruleset_count = sum(
        set(categories) == set(RULE_CATEGORIES) for categories in ruleset_coverage.values()
    )
    terms = db.scalar(
        select(ReservationOfferVersion)
        .where(
            ReservationOfferVersion.brand_id == brand_id,
            ReservationOfferVersion.terms_version_id == HOUSE_DESIGN_TERMS_VERSION,
            ReservationOfferVersion.active.is_(True),
            ReservationOfferVersion.legal_approved.is_(True),
            ReservationOfferVersion.finance_approved.is_(True),
            ReservationOfferVersion.pricing_approved.is_(True),
            ReservationOfferVersion.valid_from <= now,
            ReservationOfferVersion.valid_to >= now,
        )
        .order_by(ReservationOfferVersion.created_at.desc())
    )
    booking = db.scalar(
        select(BookingExperienceVersion).where(
            BookingExperienceVersion.brand_id == brand_id,
            BookingExperienceVersion.active.is_(True),
        )
    )
    adapter_rows = db.scalars(
        select(HouseDesignerAdapterRegistration).where(
            HouseDesignerAdapterRegistration.tenant_id == tenant_id,
            HouseDesignerAdapterRegistration.brand_id == brand_id,
            HouseDesignerAdapterRegistration.status == "ACTIVE",
        )
    ).all()
    adapter_by_type = {row.adapter_type: row for row in adapter_rows}
    adapter_details = {
        adapter_type: {
            "active": adapter_type in adapter_by_type,
            "healthy": bool(
                adapter_by_type.get(adapter_type)
                and adapter_by_type[adapter_type].health_status == "HEALTHY"
                and adapter_by_type[adapter_type].last_health_at is not None
                and _aware(adapter_by_type[adapter_type].last_health_at)
                >= now - ADAPTER_HEALTH_MAX_AGE
            ),
            "adapterId": (
                adapter_by_type[adapter_type].adapter_id
                if adapter_type in adapter_by_type
                else None
            ),
        }
        for adapter_type in REQUIRED_ADAPTERS
    }
    module_rows = db.scalars(
        select(ModuleRegistry).where(ModuleRegistry.module_key.in_(REQUIRED_INTEGRATIONS))
    ).all()
    module_by_key = {row.module_key: row for row in module_rows}
    integration_details = {
        module_key: {
            "registered": module_key in module_by_key,
            "integrationStatus": (
                module_by_key[module_key].integration_status
                if module_key in module_by_key
                else None
            ),
            "lastTestStatus": (
                module_by_key[module_key].last_integration_test_status
                if module_key in module_by_key
                else None
            ),
        }
        for module_key in REQUIRED_INTEGRATIONS
    }
    release = db.scalar(
        select(ReleaseRecord)
        .where(ReleaseRecord.module_key == "house-designer")
        .order_by(ReleaseRecord.created_at.desc())
    )
    runtime_secrets = (
        settings.house_designer_pricing_hmac_secret,
        settings.house_designer_capacity_hmac_secret,
        settings.house_designer_render_hmac_secret,
    )
    site_encryption_configured = site_encryption_ready()
    checks = [
        _check("approved_template", template_count > 0, f"{template_count} jóváhagyott típusterv"),
        _check(
            "approved_ruleset", ruleset_count > 0, f"{ruleset_count} jóváhagyott szabálykészlet"
        ),
        _check(
            "regulatory_rule_coverage",
            production_ruleset_count > 0,
            (
                f"{production_ruleset_count} teljes v2 szabálykészlet; "
                f"kötelező kategóriák: {len(RULE_CATEGORIES)}."
                if production_ruleset_count > 0
                else "Nincs mind a 14 kötelező kategóriát lefedő validált v2 szabálykészlet."
            ),
        ),
        _check(
            "approved_terms",
            terms is not None,
            (
                f"{HOUSE_DESIGN_TERMS_VERSION} · privacy {HOUSE_DESIGN_NOTICE_VERSION}"
                if terms is not None
                else "Nincs aktív, jogi+pénzügyi+árazási jóváhagyású feltételverzió."
            ),
        ),
        _check(
            "booking_experience",
            booking is not None,
            booking.experience_id if booking is not None else "Nincs aktív foglalási élmény.",
        ),
        _check(
            "production_adapters",
            all(item["active"] and item["healthy"] for item in adapter_details.values()),
            json.dumps(adapter_details, ensure_ascii=False, sort_keys=True),
        ),
        _check(
            "canonical_integrations",
            all(
                item["integrationStatus"] == "healthy" and item["lastTestStatus"] == "passed"
                for item in integration_details.values()
            ),
            json.dumps(integration_details, ensure_ascii=False, sort_keys=True),
        ),
        _check(
            "production_release",
            release is not None and release.status == "production_ready",
            (
                f"{release.release_id} · {release.status}"
                if release is not None
                else "Nincs Háztervező release-bizonyíték."
            ),
        ),
        _check(
            "site_data_encryption",
            site_encryption_configured,
            (
                f"Külön House Designer site KEK: {settings.house_designer_site_key_id}."
                if site_encryption_configured
                else "A külön House Designer site KEK hiányzik vagy nem független."
            ),
        ),
        _check(
            "runtime_security",
            settings.house_designer_adapters_enabled
            and settings.house_design_order_intake_enabled
            and settings.house_designer_callback_base_url.startswith("https://")
            and all(len(secret) >= 32 for secret in runtime_secrets)
            and len(set(runtime_secrets)) == 3,
            (
                "Külön adapter- és order-intake flag, publikus HTTPS callback és "
                "három különálló HMAC-kulcs."
            ),
        ),
    ]
    entitlement = db.scalar(
        select(HouseDesignerEntitlement).where(
            HouseDesignerEntitlement.tenant_id == tenant_id,
            HouseDesignerEntitlement.brand_id == brand_id,
        )
    )
    manifest = {
        "schemaVersion": "house-designer-release-readiness-v1",
        "tenantId": tenant_id,
        "brandId": brand_id,
        "checks": checks,
    }
    return {
        **manifest,
        "readinessSha256": _sha(manifest),
        "readyForActivation": all(item["passed"] for item in checks),
        "entitlement": _entitlement_result(entitlement),
        "adapterDetails": adapter_details,
        "integrationDetails": integration_details,
    }


def request_entitlement_activation(
    db: Session,
    *,
    tenant_id: str,
    brand_id: str,
    actor_subject_id: str,
    actor_role: str,
    expected_row_version: int | None,
) -> dict[str, Any]:
    if actor_role not in ACTIVATION_AUTHORS:
        raise HouseDesignerError(
            "entitlement_request_forbidden",
            "Nincs Háztervező-aktiválás előkészítési joga.",
            status_code=403,
        )
    readiness = house_designer_release_readiness(db, tenant_id=tenant_id, brand_id=brand_id)
    if not readiness["readyForActivation"]:
        blocked = [item["key"] for item in readiness["checks"] if not item["passed"]]
        raise HouseDesignerError(
            "release_readiness_blocked",
            "Az aktiválás kiadási kapui hiányosak: " + ", ".join(blocked),
            status_code=409,
        )
    row = db.scalar(
        select(HouseDesignerEntitlement)
        .where(
            HouseDesignerEntitlement.tenant_id == tenant_id,
            HouseDesignerEntitlement.brand_id == brand_id,
        )
        .with_for_update()
    )
    if row is not None and row.status == "active":
        raise HouseDesignerError(
            "entitlement_already_active", "A Háztervező már aktív.", status_code=409
        )
    if row is not None and row.status == "pending_review":
        raise HouseDesignerError(
            "entitlement_request_pending",
            "Már van jóváhagyásra váró Háztervező-aktiválás.",
            status_code=409,
        )
    _require_expected_version(row, expected_row_version)
    now = datetime.now(UTC)
    if row is None:
        row = HouseDesignerEntitlement(
            entitlement_id=f"HDENT-{uuid4().hex}",
            tenant_id=tenant_id,
            brand_id=brand_id,
            created_by=actor_subject_id,
        )
        db.add(row)
    row.status = "pending_review"
    row.standalone_enabled = True
    row.order_intake_enabled = True
    row.production_render_enabled = True
    row.production_pricing_enabled = True
    row.production_capacity_enabled = True
    row.policy_json = json.dumps(
        {
            "schemaVersion": readiness["schemaVersion"],
            "readinessSha256": readiness["readinessSha256"],
            "checks": readiness["checks"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    row.valid_from = now
    row.valid_until = None
    row.activation_requested_at = now
    row.readiness_sha256 = readiness["readinessSha256"]
    row.created_by = actor_subject_id
    row.reviewed_by = None
    row.reviewed_at = None
    row.row_version = int(row.row_version or 0) + 1
    audit(
        db,
        actor=actor_subject_id,
        action="house_designer.entitlement.request_activation",
        entity_type="HouseDesignerEntitlement",
        entity_id=row.entitlement_id,
        after={
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "readiness_sha256": readiness["readinessSha256"],
        },
    )
    db.commit()
    return _entitlement_result(row) or {}


def set_sandbox_entitlement(
    db: Session,
    *,
    tenant_id: str,
    brand_id: str,
    actor_subject_id: str,
    actor_role: str,
    enabled: bool,
    expected_row_version: int | None,
) -> dict[str, Any]:
    """Open or close customer UAT without enabling any production adapter."""

    if actor_role not in SANDBOX_MANAGERS:
        raise HouseDesignerError(
            "sandbox_entitlement_forbidden",
            "Nincs Háztervező sandbox-kezelési joga.",
            status_code=403,
        )
    row = db.scalar(
        select(HouseDesignerEntitlement)
        .where(
            HouseDesignerEntitlement.tenant_id == tenant_id,
            HouseDesignerEntitlement.brand_id == brand_id,
        )
        .with_for_update()
    )
    if row is not None and row.status in {"active", "pending_review"}:
        raise HouseDesignerError(
            "sandbox_transition_blocked",
            "Aktív vagy jóváhagyásra váró éles jogosultság sandbox művelettel nem írható felül.",
            status_code=409,
        )
    _require_expected_version(row, expected_row_version)
    now = datetime.now(UTC)
    if row is None:
        row = HouseDesignerEntitlement(
            entitlement_id=f"HDENT-{uuid4().hex}",
            tenant_id=tenant_id,
            brand_id=brand_id,
            created_by=actor_subject_id,
        )
        db.add(row)
    row.status = "sandbox" if enabled else "suspended"
    row.standalone_enabled = enabled
    row.order_intake_enabled = False
    row.production_render_enabled = False
    row.production_pricing_enabled = False
    row.production_capacity_enabled = False
    row.valid_from = now
    row.valid_until = None if enabled else now
    row.activation_requested_at = None
    row.readiness_sha256 = None
    row.reviewed_by = actor_subject_id
    row.reviewed_at = now
    row.policy_json = json.dumps(
        {
            "mode": "sandbox" if enabled else "suspended",
            "productionExternalWrites": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    row.row_version = int(row.row_version or 0) + 1
    audit(
        db,
        actor=actor_subject_id,
        action=(
            "house_designer.entitlement.enable_sandbox"
            if enabled
            else "house_designer.entitlement.disable_sandbox"
        ),
        entity_type="HouseDesignerEntitlement",
        entity_id=row.entitlement_id,
        after={
            "status": row.status,
            "standalone_enabled": row.standalone_enabled,
            "order_intake_enabled": False,
            "production_adapters_enabled": False,
        },
    )
    db.commit()
    return _entitlement_result(row) or {}


def review_entitlement_activation(
    db: Session,
    *,
    tenant_id: str,
    brand_id: str,
    actor_subject_id: str,
    actor_role: str,
    approve: bool,
    expected_row_version: int,
    expected_readiness_sha256: str,
) -> dict[str, Any]:
    if actor_role not in ACTIVATION_REVIEWERS:
        raise HouseDesignerError(
            "entitlement_review_forbidden",
            "Nincs Háztervező-aktiválás jóváhagyási joga.",
            status_code=403,
        )
    row = db.scalar(
        select(HouseDesignerEntitlement)
        .where(
            HouseDesignerEntitlement.tenant_id == tenant_id,
            HouseDesignerEntitlement.brand_id == brand_id,
        )
        .with_for_update()
    )
    if row is None or row.status != "pending_review":
        raise HouseDesignerError(
            "entitlement_not_reviewable", "Nincs jóváhagyásra váró aktiválás.", status_code=409
        )
    _require_expected_version(row, expected_row_version)
    if not expected_readiness_sha256 or expected_readiness_sha256 != row.readiness_sha256:
        raise HouseDesignerError(
            "entitlement_precondition_failed",
            "Az aktiválási kérelem bizonyítékverziója megváltozott. Töltse újra az oldalt.",
            status_code=409,
        )
    if row.created_by == actor_subject_id:
        raise HouseDesignerError(
            "four_eyes_required",
            "Az aktiválás előkészítője nem hagyhatja jóvá a saját kérelmét.",
            status_code=409,
        )
    readiness = house_designer_release_readiness(db, tenant_id=tenant_id, brand_id=brand_id)
    if approve and (
        not readiness["readyForActivation"] or readiness["readinessSha256"] != row.readiness_sha256
    ):
        raise HouseDesignerError(
            "release_readiness_changed",
            "A kiadási bizonyíték megváltozott vagy már nem teljes; új kérelem szükséges.",
            status_code=409,
        )
    row.status = "active" if approve else "sandbox"
    if not approve:
        row.order_intake_enabled = False
        row.production_render_enabled = False
        row.production_pricing_enabled = False
        row.production_capacity_enabled = False
    row.reviewed_by = actor_subject_id
    row.reviewed_at = datetime.now(UTC)
    row.row_version += 1
    audit(
        db,
        actor=actor_subject_id,
        action=(
            "house_designer.entitlement.activate"
            if approve
            else "house_designer.entitlement.reject"
        ),
        entity_type="HouseDesignerEntitlement",
        entity_id=row.entitlement_id,
        after={"status": row.status, "readiness_sha256": row.readiness_sha256},
    )
    db.commit()
    return _entitlement_result(row) or {}


def suspend_entitlement(
    db: Session,
    *,
    tenant_id: str,
    brand_id: str,
    actor_subject_id: str,
    actor_role: str,
    expected_row_version: int,
) -> dict[str, Any]:
    if actor_role not in ACTIVATION_REVIEWERS:
        raise HouseDesignerError(
            "entitlement_suspend_forbidden",
            "Nincs Háztervező-felfüggesztési joga.",
            status_code=403,
        )
    row = db.scalar(
        select(HouseDesignerEntitlement)
        .where(
            HouseDesignerEntitlement.tenant_id == tenant_id,
            HouseDesignerEntitlement.brand_id == brand_id,
        )
        .with_for_update()
    )
    if row is None or row.status != "active":
        raise HouseDesignerError(
            "entitlement_not_active", "A Háztervező nem aktív.", status_code=409
        )
    _require_expected_version(row, expected_row_version)
    row.status = "suspended"
    row.standalone_enabled = False
    row.order_intake_enabled = False
    row.production_render_enabled = False
    row.production_pricing_enabled = False
    row.production_capacity_enabled = False
    row.valid_until = datetime.now(UTC)
    row.reviewed_by = actor_subject_id
    row.reviewed_at = datetime.now(UTC)
    row.row_version += 1
    audit(
        db,
        actor=actor_subject_id,
        action="house_designer.entitlement.suspend",
        entity_type="HouseDesignerEntitlement",
        entity_id=row.entitlement_id,
    )
    db.commit()
    return _entitlement_result(row) or {}


def _check(key: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"key": key, "passed": bool(passed), "detail": detail}


def _ruleset_categories(row: RegulatoryRuleSet) -> set[str]:
    try:
        rules = json.loads(row.rules_json)
        if rules.get("schemaVersion") != RULE_SCHEMA_VERSION:
            return set()
        checks = normalize_declarative_rules(rules.get("checks"))
    except (json.JSONDecodeError, AttributeError, RegulatoryRuleSchemaError):
        return set()
    return {
        item["category"]
        for item in checks
        if item["severity"] in {"BLOCKER", "ERROR"}
    }


def _require_expected_version(
    row: HouseDesignerEntitlement | None, expected_row_version: int | None
) -> None:
    if row is None:
        if expected_row_version is not None:
            raise HouseDesignerError(
                "entitlement_precondition_failed",
                "A jogosultság időközben megváltozott. Töltse újra az oldalt.",
                status_code=409,
            )
        return
    if expected_row_version is None or row.row_version != expected_row_version:
        raise HouseDesignerError(
            "entitlement_precondition_failed",
            "A jogosultság időközben megváltozott. Töltse újra az oldalt.",
            status_code=409,
        )


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _entitlement_result(row: HouseDesignerEntitlement | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "entitlementId": row.entitlement_id,
        "status": row.status,
        "standaloneEnabled": row.standalone_enabled,
        "orderIntakeEnabled": row.order_intake_enabled,
        "productionRenderEnabled": row.production_render_enabled,
        "productionPricingEnabled": row.production_pricing_enabled,
        "productionCapacityEnabled": row.production_capacity_enabled,
        "validFrom": row.valid_from,
        "validUntil": row.valid_until,
        "activationRequestedAt": row.activation_requested_at,
        "readinessSha256": row.readiness_sha256,
        "createdBy": row.created_by,
        "reviewedBy": row.reviewed_by,
        "reviewedAt": row.reviewed_at,
        "rowVersion": row.row_version,
    }
