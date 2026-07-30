from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "copy_gate" / "monthly_promotions_2026_08.json"
)


class PromotionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PREPARATION_ONLY = "PREPARATION_ONLY"
    NO_PROMOTION_SOURCE = "NO_PROMOTION_SOURCE"
    NEVER_PROMOTION = "NEVER_PROMOTION"
    MISSING_REQUIRED_SOURCE = "MISSING_REQUIRED_SOURCE"


class MonthlyPromotionRecord(BaseModel):
    brand_id: str = Field(min_length=2, max_length=100)
    monthly_policy: str = Field(pattern="^(ALWAYS_REQUIRED|SOURCE_DRIVEN|NEVER_PROMOTION)$")
    status: PromotionStatus
    promotion_id: str | None = Field(default=None, max_length=160)
    campaign_message: str | None = None
    secondary_message: str | None = None
    suggested_cta: str | None = None
    promotion_copy_placement: str = Field(default="FIRST_BLOCK", pattern="^FIRST_BLOCK$")
    promotion_on_creative: str = Field(default="OPTIONAL", pattern="^OPTIONAL$")
    valid_from: date | None = None
    valid_until: date | None = None
    publication_approvals: dict[str, bool] = Field(default_factory=dict)
    models: list[dict[str, Any]] = Field(default_factory=list)
    gift: dict[str, Any] = Field(default_factory=dict)
    blocking_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_promotion_shape(self) -> MonthlyPromotionRecord:
        has_offer = self.status in {
            PromotionStatus.ACTIVE,
            PromotionStatus.PREPARATION_ONLY,
        }
        if has_offer and not all(
            [
                self.promotion_id,
                self.campaign_message,
                self.secondary_message,
                self.suggested_cta,
                self.valid_from,
                self.valid_until,
            ]
        ):
            raise ValueError("Az aktív vagy előkészítés alatt álló akció adatai hiányosak.")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("Az akció záródátuma nem előzheti meg a kezdődátumát.")
        if (
            self.status == PromotionStatus.NEVER_PROMOTION
            and self.monthly_policy != "NEVER_PROMOTION"
        ):
            raise ValueError("NEVER_PROMOTION státuszhoz azonos havi policy szükséges.")
        return self

    @property
    def publication_allowed(self) -> bool:
        return (
            self.status == PromotionStatus.ACTIVE
            and bool(self.publication_approvals)
            and all(self.publication_approvals.values())
        )


class MonthlyPromotionRegistry(BaseModel):
    schema_version: str
    registry_id: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    source: dict[str, Any]
    global_rules: dict[str, Any]
    brands: dict[str, MonthlyPromotionRecord]


class PromotionRequirement(BaseModel):
    brand_id: str
    status: PromotionStatus
    promotion_id: str | None
    copy_required: bool
    copy_position: str
    promotion_on_creative_optional: bool
    publication_allowed: bool
    campaign_message: str | None = None
    secondary_message: str | None = None
    suggested_cta: str | None = None
    blocking_reasons: list[str] = Field(default_factory=list)


def load_monthly_promotion_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> MonthlyPromotionRegistry:
    return MonthlyPromotionRegistry.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_monthly_promotion(
    brand_id: str,
    *,
    on_date: date,
    registry: MonthlyPromotionRegistry | None = None,
) -> PromotionRequirement:
    registry = registry or load_monthly_promotion_registry()
    record = registry.brands.get(brand_id)
    if record is None:
        return PromotionRequirement(
            brand_id=brand_id,
            status=PromotionStatus.NO_PROMOTION_SOURCE,
            promotion_id=None,
            copy_required=False,
            copy_position="FIRST_BLOCK",
            promotion_on_creative_optional=True,
            publication_allowed=True,
            blocking_reasons=["A márkához nincs havi akcióforrás."],
        )

    in_window = bool(
        record.valid_from
        and record.valid_until
        and record.valid_from <= on_date <= record.valid_until
    )
    copy_required = record.status in {
        PromotionStatus.ACTIVE,
        PromotionStatus.PREPARATION_ONLY,
    } and (in_window or record.status == PromotionStatus.PREPARATION_ONLY)

    blocking_reasons = list(record.blocking_reasons)
    if record.status == PromotionStatus.MISSING_REQUIRED_SOURCE:
        blocking_reasons.append(
            "A márka szabály szerint mindig akciós, de nincs hiteles havi ajánlatforrás."
        )

    return PromotionRequirement(
        brand_id=brand_id,
        status=record.status,
        promotion_id=record.promotion_id,
        copy_required=copy_required,
        copy_position=record.promotion_copy_placement,
        promotion_on_creative_optional=record.promotion_on_creative == "OPTIONAL",
        publication_allowed=record.publication_allowed and in_window,
        campaign_message=record.campaign_message,
        secondary_message=record.secondary_message,
        suggested_cta=record.suggested_cta,
        blocking_reasons=blocking_reasons,
    )
