from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourceVerificationIn(BaseModel):
    expected_source_sha256: str = Field(min_length=64, max_length=64)
    note: str = Field(min_length=10, max_length=2000)
    actor: str = Field(min_length=3, max_length=255)


class DealIn(BaseModel):
    evidence_ref: str = Field(min_length=8, max_length=1500)
    evidence_sha256: str = Field(min_length=64, max_length=64)
    actor: str = Field(min_length=3, max_length=255)


class AuthorityGrantIn(BaseModel):
    grantor_reference: str = Field(min_length=3, max_length=500)
    scopes: list[
        Literal["advertising", "media_use", "pricing", "withdrawal", "website", "portals"]
    ] = Field(min_length=1, max_length=6)
    evidence_ref: str = Field(min_length=8, max_length=1500)
    evidence_sha256: str = Field(min_length=64, max_length=64)
    valid_from: datetime
    valid_until: datetime
    created_by: str = Field(min_length=3, max_length=255)
    approved_by: str = Field(min_length=3, max_length=255)

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate authority scope")
        return value


class ListingPackageIn(BaseModel):
    authority_grant_id: str = Field(min_length=3, max_length=120)
    plotcheck_case_id: str = Field(min_length=3, max_length=140)
    house_id: str = Field(min_length=3, max_length=120)
    catalog_version_id: str = Field(min_length=3, max_length=150)
    buildconfig_case_id: str = Field(min_length=3, max_length=140)
    buildconfig_version_id: str = Field(min_length=3, max_length=140)
    plot_price_huf: int = Field(gt=0)
    media_asset_ids: list[str] = Field(min_length=1, max_length=30)
    contact_route: str = Field(min_length=3, max_length=500)
    actor: str = Field(min_length=3, max_length=255)

    @field_validator("media_asset_ids")
    @classmethod
    def valid_assets(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned or len(cleaned) != len(value) or len(cleaned) != len(set(cleaned)):
            raise ValueError("media assets must be unique non-empty internal identifiers")
        return cleaned


class PackageApprovalIn(BaseModel):
    expected_payload_sha256: str = Field(min_length=64, max_length=64)
    note: str = Field(min_length=10, max_length=2000)
    actor: str = Field(min_length=3, max_length=255)


class PublicationRequestIn(BaseModel):
    channels: list[str] = Field(min_length=1, max_length=20)
    actor: str = Field(min_length=3, max_length=255)

    @field_validator("channels")
    @classmethod
    def unique_channels(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned or len(cleaned) != len(value) or len(cleaned) != len(set(cleaned)):
            raise ValueError("channels must be unique and non-empty")
        return cleaned


class PublicationConfirmationIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=500)
    public_url: str = Field(min_length=8, max_length=1500)
    proof: dict
    actor: str = Field(min_length=3, max_length=255)


class AuthorityRevokeIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)
    actor: str = Field(min_length=3, max_length=255)


class ListingStateIn(BaseModel):
    active: bool
    evidence_ref: str = Field(min_length=8, max_length=1500)
    actor: str = Field(min_length=3, max_length=255)
