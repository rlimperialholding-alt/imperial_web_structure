from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Channel = Literal[
    "nim_cms",
    "wordpress",
    "facebook",
    "instagram",
    "linkedin",
    "analytics",
    "crm",
    "forum",
]
Decision = Literal["PASS", "BLOCK", "REVIEW"]

MANDATORY_GATES = {
    "brand_voice",
    "natural_hungarian",
    "brand_anchor",
    "claim_coverage",
    "claim_freshness",
    "legal_template",
    "conversion",
    "seo",
    "duplicate_cannibalization",
    "visual_rights_privacy",
    "visual_quality",
    "technical_render",
    "security_privacy",
    "channel_policy",
}


class GateResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: str = Field(min_length=2, max_length=100)
    decision: Decision
    evidence_id: str = Field(min_length=2, max_length=160)
    checked_at: datetime
    valid_until: datetime
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_window(self):
        checked = self.checked_at if self.checked_at.tzinfo else self.checked_at.replace(tzinfo=UTC)
        valid = (
            self.valid_until if self.valid_until.tzinfo else self.valid_until.replace(tzinfo=UTC)
        )
        if valid <= checked:
            raise ValueError("Gate evidence validity must end after checked_at.")
        return self


class RollbackPolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_partial_failure: bool = True
    automatic_kill_switch_on_failure: bool = True
    restore_last_known_good: bool = True


class PublicationJobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=3, max_length=120)
    content_asset_id: str = Field(min_length=3, max_length=120)
    content_version_id: str = Field(min_length=1, max_length=120)
    brand_id: str = Field(min_length=2, max_length=100)
    visual_asset_package_id: str = Field(min_length=3, max_length=160)
    claim_ids: list[str] = Field(min_length=1, max_length=100)
    price_snapshot_id: str = Field(min_length=3, max_length=160)
    offer_version_id: str = Field(min_length=3, max_length=160)
    terms_version_id: str = Field(min_length=3, max_length=160)
    gate_results: list[GateResultIn] = Field(min_length=1, max_length=100)
    cta: dict[str, Any]
    title: str = Field(min_length=1, max_length=500)
    canonical_slug: str = Field(min_length=1, max_length=255)
    body_html: str = Field(min_length=1, max_length=5_000_000)
    excerpt: str = Field(min_length=1, max_length=5000)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    channels: list[Channel] = Field(min_length=1, max_length=8)
    channel_payloads: dict[str, dict[str, Any]]
    cms_route: Literal["NIM", "WORDPRESS"]
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    desired_publish_at: datetime | None = None
    rollback_policy: RollbackPolicyIn = Field(default_factory=RollbackPolicyIn)
    correlation_id: str = Field(min_length=3, max_length=120)
    release_token: str = Field(min_length=32, max_length=4096)
    release_token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_url: str | None = Field(default=None, max_length=1000)
    language: str = Field(default="hu", min_length=2, max_length=12)
    seo_title: str | None = Field(default=None, max_length=500)
    meta_description: str | None = Field(default=None, max_length=1000)
    categories: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    author: str | None = Field(default=None, max_length=255)

    @field_validator("canonical_slug")
    @classmethod
    def slug_is_canonical(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("canonical_slug must be lowercase kebab-case")
        return value

    @field_validator("channels")
    @classmethod
    def channels_are_unique(cls, value: list[Channel]) -> list[Channel]:
        if len(value) != len(set(value)):
            raise ValueError("channels must be unique")
        return value

    @model_validator(mode="after")
    def fail_closed_preflight(self):
        by_gate = {gate.gate: gate for gate in self.gate_results}
        if len(by_gate) != len(self.gate_results):
            raise ValueError("Duplicate gate names are not allowed")
        expected_web = "nim_cms" if self.cms_route == "NIM" else "wordpress"
        other_web = "wordpress" if expected_web == "nim_cms" else "nim_cms"
        if expected_web not in self.channels or other_web in self.channels:
            raise ValueError("CMSRoute and web channel selection conflict")
        if (
            any(channel in self.channels for channel in ("facebook", "instagram", "linkedin"))
            and expected_web not in self.channels
        ):
            raise ValueError("Social publication requires its canonical web channel")
        if not self.cta.get("url") or not self.cta.get("label"):
            raise ValueError("Approved CTA label and URL are required")
        if (
            any(
                channel in self.channels
                for channel in ("nim_cms", "wordpress", "facebook", "instagram", "linkedin")
            )
            and not self.visual_asset_package_id
        ):
            raise ValueError("VisualAssetPackageID is required")
        if set(self.channel_payloads) != set(self.channels):
            raise ValueError("channel_payloads must match the selected channels exactly")
        for channel, field in (("facebook", "message"), ("instagram", "caption")):
            if channel not in self.channels:
                continue
            text = str(self.channel_payloads[channel].get(field) or "")
            hashtag_count = len(re.findall(r"(?<!\w)#\w+", text, flags=re.UNICODE))
            if not 3 <= hashtag_count <= 8:
                raise ValueError(f"{channel} copy must contain 3 to 8 hashtags")
        if "linkedin" in self.channels:
            payload = self.channel_payloads["linkedin"]
            commentary = payload.get("commentary")
            if not isinstance(commentary, str) or not commentary.strip():
                raise ValueError("linkedin commentary is required")
            if len(commentary.strip()) > 3000:
                raise ValueError("linkedin commentary exceeds 3000 characters")
            media_urn = payload.get("media_urn")
            if media_urn is not None and not re.fullmatch(
                r"urn:li:(?:image|video|document):[A-Za-z0-9_-]+", str(media_urn)
            ):
                raise ValueError("linkedin media_urn is invalid")
            media_title = payload.get("media_title")
            if media_title is not None and (
                not isinstance(media_title, str)
                or not media_title.strip()
                or len(media_title) > 400
            ):
                raise ValueError("linkedin media_title is invalid")
            disabled = payload.get("is_reshare_disabled_by_author")
            if disabled is not None and not isinstance(disabled, bool):
                raise ValueError("linkedin is_reshare_disabled_by_author must be boolean")
        if self.release_token_hash == "0" * 64:
            raise ValueError("release token hash is invalid")
        return self


class PublicationJobReceipt(BaseModel):
    job_id: str
    status: str
    idempotent: bool
    payload_sha256: str


class PublishingRetryIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)
