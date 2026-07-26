from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DateRangeRequest(BaseModel):
    start_date: date
    end_date: date


class SyncRequest(DateRangeRequest):
    brand: str | None = None
    entity_key: str | None = None


class SyncResult(BaseModel):
    run_id: uuid.UUID
    source: str
    entity_key: str
    rows_written: int
    status: str


class ReviewReplyRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=4096)


class PhotoOrderRequest(BaseModel):
    photo_own_ids: list[str] = Field(min_length=1, max_length=30)


class PublicationCreate(BaseModel):
    content_id: str
    website_key: str
    paths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    action: str = "publish"
    publish_at: datetime | None = None
    batch_id: uuid.UUID = Field(default_factory=uuid.uuid4)

    @field_validator("publish_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("publish_at must include a timezone")
        return value


class PublicationRead(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    content_id: str
    website_key: str
    status: str
    attempt_count: int
    error_message: str | None
    response_payload: dict[str, Any]


class DirectusWebhookEvent(BaseModel):
    event: str
    collection: str
    keys: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("keys", mode="before")
    @classmethod
    def normalize_keys(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, int, uuid.UUID)):
            return [str(value)]
        return [str(item) for item in value]
