from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_RE = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class GrowthSignalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=2, max_length=120)
    external_key: str = Field(min_length=2, max_length=255)
    motor_key: Literal["construction", "distress", "ivs"]
    source_bucket: str = Field(min_length=2, max_length=100)
    signal_type: str = Field(min_length=2, max_length=120)
    detected_at: datetime
    company_name: str | None = Field(default=None, max_length=500)
    company_registration_id: str | None = Field(default=None, max_length=120)
    recipient_organization_name: str | None = Field(default=None, max_length=500)
    recipient_office_name: str | None = Field(default=None, max_length=500)
    subject_type: Literal["organization", "natural_person"]
    recipient_role: Literal["listing_agent", "property_owner", "unknown"] = "unknown"
    recipient_type: Literal[
        "architect_office",
        "land_owner",
        "real_estate_agent",
        "referral_partner",
        "unknown",
    ] = "unknown"
    recipient_name: str | None = Field(default=None, max_length=500)
    sender_company_name: str | None = Field(default=None, max_length=500)
    reference_names: list[str] = Field(default_factory=list, max_length=3)
    reference_names_verified: bool = False
    business_context: str | None = Field(default=None, max_length=500)
    business_context_verified: bool = False
    business_context_evidence_url: str | None = Field(default=None, max_length=1500)
    recipient_classification_verified: bool = False
    exclusion_screening_verified: bool = False
    recipient_email: str | None = Field(default=None, max_length=320)
    recipient_email_type: Literal["role", "named", "unknown", "none"] = "none"
    contact_basis: Literal[
        "public_business_contact",
        "public_property_listing",
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

    @field_validator("recipient_name", "sender_company_name", "business_context")
    @classmethod
    def optional_names_are_clean(cls, value: str | None) -> str | None:
        normalized = " ".join(str(value or "").split())
        return normalized or None

    @field_validator("reference_names")
    @classmethod
    def reference_names_are_clean(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(str(value or "").split()) for value in values]
        if any(not value for value in normalized):
            raise ValueError("Reference names cannot be empty")
        if len(set(value.casefold() for value in normalized)) != len(normalized):
            raise ValueError("Reference names must be unique")
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
        if self.contact_basis == "public_property_listing":
            if self.signal_type != "residential_building_plot":
                raise ValueError(
                    "Public property listing basis is restricted to building-plot signals"
                )
            if self.recipient_role == "unknown":
                raise ValueError("Building-plot recipient role is required")
            if not self.public_contact_url:
                raise ValueError("Public property listing URL is required")
        if (
            self.signal_type == "residential_building_plot"
            and self.recipient_email
            and self.recipient_role == "unknown"
        ):
            raise ValueError("Building-plot recipient role is required")
        if not self.evidence_url.startswith("https://"):
            raise ValueError("Evidence URL must use HTTPS")
        if self.recipient_type == "architect_office" and len(self.reference_names) not in {
            0,
            2,
            3,
        }:
            raise ValueError("Architect references must contain zero, two or three items")
        if self.reference_names and not self.reference_names_verified:
            raise ValueError("Architect references must be explicitly verified")
        if self.recipient_type != "architect_office" and self.reference_names:
            raise ValueError("References are only allowed for architect-office outreach")
        if self.business_context_evidence_url and not self.business_context_evidence_url.startswith(
            "https://"
        ):
            raise ValueError("Business-context evidence URL must use HTTPS")
        if self.recipient_type != "referral_partner" and (
            self.business_context
            or self.business_context_verified
            or self.business_context_evidence_url
        ):
            raise ValueError("Business context is only allowed for referral-partner outreach")
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


class OutreachReleaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=3, max_length=255)
    inspected_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_note: str = Field(min_length=10, max_length=2000)


class CanonicalFirstContactRenderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_type: Literal[
        "architect_office",
        "land_owner",
        "real_estate_agent",
        "referral_partner",
        "unknown",
    ]
    recipient_name: str | None = Field(default=None, max_length=500)
    sender_company_name: str | None = Field(default=None, max_length=500)
    reference_names: list[str] = Field(default_factory=list, max_length=3)
    reference_names_verified: bool = False
    business_context: str | None = Field(default=None, max_length=500)
    business_context_verified: bool = False
    business_context_evidence_url: str | None = Field(default=None, max_length=1500)
    unsubscribe_url: str | None = Field(default=None, max_length=2000)
    recipient_classification_verified: bool
    exclusion_screening_verified: bool
    screening_values: list[str] = Field(default_factory=list, max_length=50)
