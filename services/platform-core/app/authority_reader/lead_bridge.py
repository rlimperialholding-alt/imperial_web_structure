from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import URL, Engine, create_engine, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..database import SessionLocal
from ..growth_ops.models import GrowthSignal
from .config import ReaderSettings
from .models import AuthoritySignalOutbox
from .service import canonical_json, sha, utcnow

HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$")


def _secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    path = os.getenv(f"{name}_FILE", "").strip()
    return Path(path).read_text(encoding="utf-8").strip() if path else ""


@dataclass(frozen=True)
class LeadBridgeSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    poll_seconds: int
    batch_size: int

    @classmethod
    def from_env(cls) -> LeadBridgeSettings:
        return cls(
            host=os.getenv("PLATFORM_GROWTH_DB_HOST", "platform-postgres").strip(),
            port=max(1, min(65535, int(os.getenv("PLATFORM_GROWTH_DB_PORT", "5432")))),
            database=os.getenv("PLATFORM_GROWTH_DB_NAME", "imperial_platform").strip(),
            user=os.getenv("PLATFORM_GROWTH_DB_USER", "etdr_lead_bridge").strip(),
            password=_secret("PLATFORM_GROWTH_DB_PASSWORD"),
            poll_seconds=max(
                15, min(3600, int(os.getenv("AUTHORITY_LEAD_BRIDGE_POLL_SECONDS", "60")))
            ),
            batch_size=max(1, min(500, int(os.getenv("AUTHORITY_LEAD_BRIDGE_BATCH_SIZE", "100")))),
        )

    def errors(self) -> list[str]:
        errors: list[str] = []
        if not HOST_RE.fullmatch(self.host) or self.host.casefold() in {
            "metadata",
            "metadata.google.internal",
        }:
            errors.append("invalid_platform_database_host")
        if not self.database or len(self.database) > 120:
            errors.append("invalid_platform_database_name")
        if not self.user or len(self.user) > 120:
            errors.append("invalid_platform_database_user")
        if len(self.password) < 32:
            errors.append("platform_database_password_too_short")
        return errors


class ETDRLeadPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = Field(pattern=r"^etdr-lead-v1$")
    source_id: str = Field(pattern=r"^authority:etdr_public$")
    external_key: str = Field(pattern=r"^[0-9]{6,40}$")
    motor_key: str = Field(pattern=r"^construction$")
    source_bucket: str = Field(pattern=r"^etdr$")
    signal_type: Literal[
        "construction_project",
        "residential_construction",
        "renovation",
        "extension",
        "fitout",
        "hall",
    ]
    detected_at: datetime
    company_name: None = None
    subject_type: str = Field(pattern=r"^project$")
    recipient_email: None = None
    recipient_email_type: str = Field(pattern=r"^none$")
    contact_basis: str = Field(pattern=r"^unknown$")
    location: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=10, max_length=5000)
    evidence_url: str = Field(min_length=8, max_length=1500)
    brand_id: Literal["bautica", "prefab"]
    confidence: int = Field(ge=0, le=100)
    urgency: int = Field(ge=0, le=100)
    source_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: str = Field(pattern=r"^etdrd-[0-9a-f]{32}$")
    revision_no: int = Field(ge=1)
    rejection_reasons: list[str] = Field(min_length=4, max_length=10)

    @model_validator(mode="after")
    def fail_closed_contract(self):
        detected = (
            self.detected_at if self.detected_at.tzinfo else self.detected_at.replace(tzinfo=UTC)
        )
        if detected > datetime.now(UTC):
            raise ValueError("future detection time")
        expected_evidence = f"https://www.etdr.gov.hu/nyilvanos-adatok/{self.external_key}"
        if self.evidence_url != expected_evidence:
            raise ValueError("non-ETDR evidence URL")
        required = {
            "authority_source_no_outreach",
            "contact_basis_unknown",
            "internal_review_only",
            "recipient_email_missing",
        }
        if set(self.rejection_reasons) != required:
            raise ValueError("lead must remain internal-review-only")
        if (self.signal_type == "hall") != (self.brand_id == "prefab"):
            raise ValueError("lead route and brand do not match")
        return self


def platform_engine(settings: LeadBridgeSettings) -> Engine:
    errors = settings.errors()
    if errors:
        raise RuntimeError(errors[0])
    return create_engine(
        URL.create(
            "postgresql+psycopg",
            username=settings.user,
            password=settings.password,
            host=settings.host,
            port=settings.port,
            database=settings.database,
        ),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )


def verify_target(target_db: Session) -> None:
    if target_db.get_bind().dialect.name != "postgresql":
        target_db.execute(select(func.count()).select_from(GrowthSignal)).scalar_one()
        return
    privileges = target_db.execute(
        text(
            "SELECT "
            "has_table_privilege(current_user,'public.growth_signals','SELECT'),"
            "has_table_privilege(current_user,'public.growth_signals','INSERT'),"
            "has_table_privilege(current_user,'public.growth_signals','UPDATE'),"
            "has_table_privilege(current_user,'public.growth_signals','DELETE'),"
            "has_table_privilege(current_user,'etdr_bridge.delivery_ledger','SELECT'),"
            "has_table_privilege(current_user,'etdr_bridge.delivery_ledger','INSERT'),"
            "has_table_privilege(current_user,'etdr_bridge.schema_versions','SELECT')"
        )
    ).one()
    if any(bool(value) for value in privileges):
        raise RuntimeError("platform_growth_role_not_least_privilege")
    can_execute = target_db.scalar(
        text(
            "SELECT has_function_privilege(current_user, "
            "'etdr_bridge.upsert_growth_signal(text,text,text,text,text,text,timestamp with time "
            "zone,text,text,text,integer,integer,text,text,integer,text)'::regprocedure, 'EXECUTE')"
        )
    )
    if not can_execute:
        raise RuntimeError("platform_growth_bridge_function_unavailable")
    can_check = target_db.scalar(
        text(
            "SELECT has_function_privilege(current_user, "
            "'etdr_bridge.installation_status()'::regprocedure, 'EXECUTE')"
        )
    )
    if not can_check:
        raise RuntimeError("platform_growth_bridge_status_unavailable")
    schema_privileges = target_db.execute(
        text(
            "SELECT "
            "has_schema_privilege(current_user,'etdr_bridge','USAGE'),"
            "has_schema_privilege(current_user,'etdr_bridge','CREATE'),"
            "has_schema_privilege(current_user,'public','CREATE')"
        )
    ).one()
    if not bool(schema_privileges[0]) or any(bool(value) for value in schema_privileges[1:]):
        raise RuntimeError("platform_growth_bridge_schema_privilege_invalid")
    role = target_db.execute(
        text(
            "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,"
            "rolbypassrls FROM pg_roles WHERE rolname=current_user"
        )
    ).one()
    if any(bool(value) for value in (*role[:4], *role[5:])) or not bool(role[4]):
        raise RuntimeError("platform_growth_bridge_role_attributes_invalid")
    memberships = target_db.scalar(
        text(
            "SELECT count(*) FROM pg_auth_members AS membership "
            "JOIN pg_roles AS member ON member.oid=membership.member "
            "JOIN pg_roles AS parent ON parent.oid=membership.roleid "
            "WHERE member.rolname=current_user OR parent.rolname=current_user"
        )
    )
    if memberships:
        raise RuntimeError("platform_growth_bridge_role_membership_invalid")
    installation = target_db.execute(
        text(
            "SELECT schema_version,recorded_definition_md5,actual_definition_md5,"
            "recorded_constraint_md5,actual_constraint_md5,function_owner,security_definer,"
            "function_config,owner_role_valid,schema_owner "
            "FROM etdr_bridge.installation_status()"
        )
    ).one()
    config = set(installation.function_config or [])
    if (
        installation.schema_version != "20260824_0003"
        or installation.recorded_definition_md5 != installation.actual_definition_md5
        or installation.recorded_constraint_md5 != installation.actual_constraint_md5
        or installation.function_owner != "etdr_bridge_owner"
        or not installation.security_definer
        or not installation.owner_role_valid
        or installation.schema_owner != "etdr_bridge_owner"
        or "search_path=pg_catalog, public" not in config
        or "row_security=on" not in config
    ):
        raise RuntimeError("platform_growth_bridge_installation_invalid")


def _signal_values(payload: ETDRLeadPayload, dedupe_hash: str) -> dict[str, object]:
    now = utcnow()
    return {
        "signal_id": f"SIG-ETDR-{uuid4().hex[:15].upper()}",
        "run_id": None,
        "motor_key": payload.motor_key,
        "source_id": payload.source_id,
        "source_bucket": payload.source_bucket,
        "external_key": payload.external_key,
        "signal_type": payload.signal_type,
        "detected_at": payload.detected_at,
        "company_name": None,
        "company_registration_id": None,
        "subject_type": "project",
        "recipient_email": None,
        "recipient_email_type": "none",
        "contact_basis": "unknown",
        "consent_evidence_id": None,
        "public_contact_url": None,
        "location": payload.location,
        "summary": payload.summary,
        "evidence_url": payload.evidence_url,
        "brand_id": payload.brand_id,
        "score": payload.confidence,
        "urgency": payload.urgency,
        "confidence": payload.confidence,
        "dedupe_hash": dedupe_hash,
        "source_payload_hash": payload.source_payload_hash,
        "status": "blocked",
        "rejection_reasons_json": canonical_json(payload.rejection_reasons),
        "first_seen_at": now,
        "last_seen_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _assert_safe_existing(existing: GrowthSignal, payload: ETDRLeadPayload) -> None:
    expected_rejections = canonical_json(payload.rejection_reasons)
    if (
        existing.motor_key != "construction"
        or existing.source_bucket != "etdr"
        or existing.subject_type != "project"
        or existing.company_name is not None
        or existing.company_registration_id is not None
        or existing.recipient_email is not None
        or existing.recipient_email_type != "none"
        or existing.contact_basis != "unknown"
        or existing.consent_evidence_id is not None
        or existing.public_contact_url is not None
        or existing.status not in {"blocked", "rejected"}
        or existing.rejection_reasons_json != expected_rejections
    ):
        raise RuntimeError("etdr_existing_signal_invariant_violation")


def _upsert_platform_signal(
    target_db: Session,
    payload: ETDRLeadPayload,
    delivery_payload_hash: str,
) -> tuple[str, bool]:
    dedupe_hash = sha({"source_id": payload.source_id, "external_key": payload.external_key})
    if target_db.get_bind().dialect.name == "postgresql":
        result = target_db.execute(
            text(
                "SELECT signal_id, idempotent FROM etdr_bridge.upsert_growth_signal("
                ":signal_id,:source_id,:external_key,:signal_type,:location,:summary,"
                ":detected_at,:evidence_url,:brand_id,:source_payload_hash,:confidence,"
                ":urgency,:dedupe_hash,:revision_id,:revision_no,:delivery_payload_hash)"
            ),
            {
                "signal_id": f"SIG-ETDR-{uuid4().hex[:15].upper()}",
                "source_id": payload.source_id,
                "external_key": payload.external_key,
                "signal_type": payload.signal_type,
                "location": payload.location,
                "summary": payload.summary,
                "detected_at": payload.detected_at,
                "evidence_url": payload.evidence_url,
                "brand_id": payload.brand_id,
                "source_payload_hash": payload.source_payload_hash,
                "confidence": payload.confidence,
                "urgency": payload.urgency,
                "dedupe_hash": dedupe_hash,
                "revision_id": payload.revision_id,
                "revision_no": payload.revision_no,
                "delivery_payload_hash": delivery_payload_hash,
            },
        ).one()
        target_db.commit()
        return str(result.signal_id), bool(result.idempotent)
    existing = target_db.scalar(
        select(GrowthSignal).where(
            GrowthSignal.source_id == payload.source_id,
            GrowthSignal.external_key == payload.external_key,
        )
    )
    if existing:
        _assert_safe_existing(existing, payload)
        existing.last_seen_at = utcnow()
        existing.updated_at = utcnow()
        if existing.status in {"blocked", "rejected"}:
            existing.signal_type = payload.signal_type
            existing.location = payload.location
            existing.summary = payload.summary
            existing.evidence_url = payload.evidence_url
            existing.brand_id = payload.brand_id
            existing.score = payload.confidence
            existing.urgency = payload.urgency
            existing.confidence = payload.confidence
            existing.source_payload_hash = payload.source_payload_hash
            existing.rejection_reasons_json = canonical_json(payload.rejection_reasons)
        target_db.commit()
        return existing.signal_id, True
    row = GrowthSignal(**_signal_values(payload, dedupe_hash))
    target_db.add(row)
    try:
        target_db.commit()
    except IntegrityError:
        target_db.rollback()
        concurrent = target_db.scalar(
            select(GrowthSignal).where(
                GrowthSignal.source_id == payload.source_id,
                GrowthSignal.external_key == payload.external_key,
            )
        )
        if not concurrent:
            raise
        return concurrent.signal_id, True
    return row.signal_id, False


def bridge_once(
    reader_db: Session,
    target_db: Session,
    reader_settings: ReaderSettings,
    *,
    limit: int,
) -> dict[str, int]:
    if (
        not reader_settings.enabled
        or not reader_settings.policy_authorized
        or not reader_settings.policy_evidence_valid
        or not reader_settings.detail_enabled
        or not reader_settings.lead_export_enabled
    ):
        return {"delivered": 0, "idempotent": 0, "blocked": 0, "failed": 0}
    now = utcnow()
    reader_db.execute(
        update(AuthoritySignalOutbox)
        .where(
            AuthoritySignalOutbox.status == "claimed",
            AuthoritySignalOutbox.lease_expires_at < now,
        )
        .values(
            status="pending",
            reason_code="platform_delivery_lease_expired",
            lease_owner=None,
            lease_expires_at=None,
        )
    )
    reader_db.commit()
    candidate_ids = reader_db.scalars(
        select(AuthoritySignalOutbox.id)
        .where(AuthoritySignalOutbox.status == "pending")
        .order_by(AuthoritySignalOutbox.id)
        .limit(max(1, min(limit, 500)))
    ).all()
    claim_owner = f"{reader_settings.worker_id[:80]}:bridge:{uuid4().hex}"
    counts = {"delivered": 0, "idempotent": 0, "blocked": 0, "failed": 0}
    for row_id in candidate_ids:
        claimed = reader_db.execute(
            update(AuthoritySignalOutbox)
            .where(
                AuthoritySignalOutbox.id == row_id,
                AuthoritySignalOutbox.status == "pending",
            )
            .values(
                status="claimed",
                reason_code="platform_delivery_claimed",
                lease_owner=claim_owner,
                lease_expires_at=utcnow() + timedelta(seconds=reader_settings.lease_seconds),
            )
        )
        reader_db.commit()
        if getattr(claimed, "rowcount", 0) != 1:
            continue
        row = reader_db.scalar(
            select(AuthoritySignalOutbox).where(
                AuthoritySignalOutbox.id == row_id,
                AuthoritySignalOutbox.status == "claimed",
                AuthoritySignalOutbox.lease_owner == claim_owner,
            )
        )
        if not row:
            continue
        try:
            raw = json.loads(row.payload_json)
            if not isinstance(raw, dict) or sha(raw) != row.payload_sha256:
                raise ValueError("payload_integrity_mismatch")
            payload = ETDRLeadPayload.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            row.status = "blocked"
            row.reason_code = "payload_contract_blocked"
            row.last_error = type(exc).__name__
            row.attempt_count += 1
            row.lease_owner = None
            row.lease_expires_at = None
            reader_db.commit()
            counts["blocked"] += 1
            continue
        try:
            delivery_ref, idempotent = _upsert_platform_signal(
                target_db, payload, row.payload_sha256
            )
            row.status = "delivered"
            row.reason_code = "daily_lead_generator_imported"
            row.delivery_ref = delivery_ref
            row.delivered_at = utcnow()
            row.last_error = None
            row.attempt_count += 1
            row.lease_owner = None
            row.lease_expires_at = None
            reader_db.commit()
            counts["idempotent" if idempotent else "delivered"] += 1
        except Exception as exc:  # noqa: BLE001 - type only, no secret-bearing detail persisted
            target_db.rollback()
            reader_db.rollback()
            failed = reader_db.get(AuthoritySignalOutbox, row_id)
            if failed is None or failed.status != "claimed" or failed.lease_owner != claim_owner:
                continue
            failed.attempt_count += 1
            failed.last_error = type(exc).__name__
            failed.status = "dead_letter" if failed.attempt_count >= 5 else "pending"
            failed.reason_code = "platform_delivery_failed"
            failed.lease_owner = None
            failed.lease_expires_at = None
            reader_db.commit()
            counts["failed"] += 1
    return counts


stopping = False


def request_stop(_signum, _frame) -> None:
    global stopping
    stopping = True


def main() -> None:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    bridge_settings = LeadBridgeSettings.from_env()
    target_engine = platform_engine(bridge_settings)
    TargetSession = sessionmaker(bind=target_engine, expire_on_commit=False)
    try:
        with TargetSession() as target_db:
            verify_target(target_db)
        if sys.argv[1:] == ["--check"]:
            with SessionLocal() as reader_db:
                reader_db.execute(text("SELECT 1"))
            return
        while not stopping:
            reader_settings = ReaderSettings.from_env()
            with SessionLocal() as reader_db, TargetSession() as target_db:
                bridge_once(
                    reader_db,
                    target_db,
                    reader_settings,
                    limit=bridge_settings.batch_size,
                )
            deadline = time.monotonic() + bridge_settings.poll_seconds
            while not stopping and time.monotonic() < deadline:
                time.sleep(0.2)
    finally:
        target_engine.dispose()


if __name__ == "__main__":
    main()
