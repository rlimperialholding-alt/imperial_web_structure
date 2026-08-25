from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GrowthSignalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=2, max_length=120)
    external_key: str = Field(min_length=2, max_length=255)
    motor_key: Literal["construction", "distress", "ivs"]
    source_bucket: str = Field(min_length=2, max_length=100)
    signal_type: str = Field(min_length=2, max_length=120)
    detected_at: datetime
    company_name: str | None = Field(default=None, max_length=500)
    contact_name: str | None = Field(default=None, max_length=255)
    company_registration_id: str | None = Field(default=None, max_length=120)
    organization_class: str | None = Field(default=None, max_length=120)
    contracting_authority_verified: bool = False
    contracting_authority_suspected: bool = False
    organization_affiliations: list[str] = Field(default_factory=list, max_length=50)
    office_affiliations: list[str] = Field(default_factory=list, max_length=50)
    website_url: str | None = Field(default=None, max_length=1500)
    subject_type: Literal["organization", "natural_person"]
    recipient_email: str | None = Field(default=None, max_length=320)
    recipient_email_type: Literal["role", "named", "unknown", "none"] = "none"
    contact_basis: Literal[
        "public_business_contact",
        "explicit_request",
        "documented_consent",
        "unknown",
    ]
    consent_evidence_id: str | None = Field(default=None, max_length=200)
    public_contact_url: str | None = Field(default=None, max_length=1500)
    location: str | None = Field(default=None, max_length=500)
    summary: str = Field(min_length=10, max_length=10_000)
    evidence_url: str = Field(min_length=8, max_length=1500)
    brand_id: str | None = Field(default=None, max_length=100)
    confidence: int = Field(ge=0, le=100)
    urgency: int = Field(ge=0, le=100)
    source_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("recipient_email")
    @classmethod
    def email_is_valid(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not EMAIL_RE.fullmatch(normalized):
            raise ValueError("Invalid recipient email address")
        return normalized

    @model_validator(mode="after")
    def evidence_is_consistent(self):
        detected = (
            self.detected_at if self.detected_at.tzinfo else self.detected_at.replace(tzinfo=UTC)
        )
        if detected > datetime.now(UTC):
            raise ValueError("Signal detection time cannot be in the future")
        if self.recipient_email and self.recipient_email_type == "none":
            raise ValueError("Recipient email type is required when an email is supplied")
        if not self.recipient_email and self.recipient_email_type != "none":
            raise ValueError("Recipient email type must be none without an email")
        if (
            self.contact_basis in {"explicit_request", "documented_consent"}
            and not self.consent_evidence_id
        ):
            raise ValueError("Consent/request evidence is required")
        if self.contact_basis == "public_business_contact" and not self.public_contact_url:
            raise ValueError("Public business contact URL is required")
        if not self.evidence_url.startswith("https://"):
            raise ValueError("Evidence URL must use HTTPS")
        return self


class GrowthSignalReceipt(BaseModel):
    signal_id: str
    status: str
    brand_id: str
    score: int
    idempotent: bool
    outreach_id: str | None = None
    reasons: list[str] = Field(default_factory=list)


class OutreachEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["delivered", "bounce", "complaint", "unsubscribe", "response"]
    provider_event_id: str | None = Field(default=None, max_length=500)
    occurred_at: datetime | None = None
    detail: dict = Field(default_factory=dict)


class GrowthControlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: str = Field(min_length=10, max_length=2000)
