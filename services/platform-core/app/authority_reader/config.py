from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


def _secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    path = os.getenv(f"{name}_FILE", "").strip()
    return Path(path).read_text(encoding="utf-8").strip() if path else ""


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() == "true"


def _policy_evidence() -> tuple[bool, str]:
    path_text = os.getenv("AUTHORITY_READER_POLICY_EVIDENCE_FILE", "").strip()
    if not path_text:
        return False, ""
    path = Path(path_text)
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
        valid_until = datetime.fromisoformat(str(payload["valid_until"]).replace("Z", "+00:00"))
        valid_until = valid_until if valid_until.tzinfo else valid_until.replace(tzinfo=UTC)
        required = ("authorization_reference", "approved_by", "scope", "valid_until")
        valid = (
            all(isinstance(payload.get(key), str) and payload[key].strip() for key in required)
            and "bulk" in payload["scope"].casefold()
            and valid_until > datetime.now(UTC)
        )
        return valid, hashlib.sha256(raw).hexdigest()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False, ""


@dataclass(frozen=True)
class ReaderSettings:
    enabled: bool
    policy_authorized: bool
    policy_evidence_valid: bool
    policy_evidence_sha256: str
    etdr_base_url: str
    etdr_public_url: str
    oeny_base_url: str
    oeny_enabled: bool
    internal_token: str
    hmac_key: str
    worker_id: str
    poll_seconds: int
    interval_hours: int
    overlap_days: int
    page_size: int
    request_delay_seconds: float
    request_timeout_seconds: float
    max_response_bytes: int
    max_pages_per_run: int
    lease_seconds: int
    detail_enabled: bool = False
    lead_export_enabled: bool = False
    detail_batch_size: int = 100
    schedule_enabled: bool = False

    @classmethod
    def from_env(cls) -> ReaderSettings:
        evidence_valid, evidence_sha256 = _policy_evidence()
        return cls(
            enabled=_bool("AUTHORITY_READER_ENABLED"),
            policy_authorized=_bool("AUTHORITY_READER_POLICY_AUTHORIZED"),
            policy_evidence_valid=evidence_valid,
            policy_evidence_sha256=evidence_sha256,
            etdr_base_url=os.getenv(
                "AUTHORITY_READER_ETDR_BASE_URL", "https://alk.etdr.gov.hu"
            ).rstrip("/"),
            etdr_public_url=os.getenv(
                "AUTHORITY_READER_ETDR_PUBLIC_URL", "https://www.etdr.gov.hu"
            ).rstrip("/"),
            oeny_base_url=os.getenv("AUTHORITY_READER_OENY_BASE_URL", "https://www.oeny.hu").rstrip(
                "/"
            ),
            oeny_enabled=_bool("AUTHORITY_READER_OENY_ENABLED"),
            internal_token=_secret("INTERNAL_JOB_TOKEN"),
            hmac_key=_secret("AUTHORITY_READER_HMAC_KEY"),
            worker_id=os.getenv("AUTHORITY_READER_WORKER_ID", "etdr-reader-1"),
            poll_seconds=max(15, min(3600, int(os.getenv("AUTHORITY_READER_POLL_SECONDS", "60")))),
            interval_hours=max(
                1, min(168, int(os.getenv("AUTHORITY_READER_INTERVAL_HOURS", "24")))
            ),
            overlap_days=max(1, min(30, int(os.getenv("AUTHORITY_READER_OVERLAP_DAYS", "7")))),
            page_size=max(1, min(100, int(os.getenv("AUTHORITY_READER_PAGE_SIZE", "100")))),
            request_delay_seconds=max(
                1.0,
                min(30.0, float(os.getenv("AUTHORITY_READER_REQUEST_DELAY_SECONDS", "2"))),
            ),
            request_timeout_seconds=max(
                3.0,
                min(60.0, float(os.getenv("AUTHORITY_READER_REQUEST_TIMEOUT_SECONDS", "20"))),
            ),
            max_response_bytes=max(
                64_000,
                min(
                    5_000_000,
                    int(os.getenv("AUTHORITY_READER_MAX_RESPONSE_BYTES", "1000000")),
                ),
            ),
            max_pages_per_run=max(
                1, min(20_000, int(os.getenv("AUTHORITY_READER_MAX_PAGES_PER_RUN", "10000")))
            ),
            lease_seconds=max(
                60, min(7200, int(os.getenv("AUTHORITY_READER_LEASE_SECONDS", "600")))
            ),
            detail_enabled=_bool("AUTHORITY_READER_DETAIL_ENABLED"),
            lead_export_enabled=_bool("AUTHORITY_READER_LEAD_EXPORT_ENABLED"),
            detail_batch_size=max(
                1, min(1000, int(os.getenv("AUTHORITY_READER_DETAIL_BATCH_SIZE", "100")))
            ),
            schedule_enabled=_bool("AUTHORITY_READER_SCHEDULE_ENABLED"),
        )

    def errors(self) -> list[str]:
        errors: list[str] = []
        for label, url in {
            "ETDR": self.etdr_base_url,
            "ETDR public": self.etdr_public_url,
            "OENY": self.oeny_base_url,
        }.items():
            if not url.startswith("https://"):
                errors.append(f"{label} origin must use HTTPS")
        if self.enabled and not self.policy_authorized:
            errors.append("policy_authorization_required")
        if self.enabled and self.policy_authorized and not self.policy_evidence_valid:
            errors.append("policy_evidence_invalid_or_expired")
        if self.enabled and len(self.internal_token) < 32:
            errors.append("internal_token_too_short")
        if self.enabled and len(self.hmac_key) < 32:
            errors.append("hmac_key_too_short")
        if self.lead_export_enabled and not self.detail_enabled:
            errors.append("lead_export_requires_detail_reader")
        return errors
