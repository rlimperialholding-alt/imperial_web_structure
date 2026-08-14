"""Fail-closed Gate 1 copy excellence and four-gate publication controls."""

from .engine import evaluate_content
from .models import ContentEvaluationRequest, EvaluationResult
from .promotions import (
    PromotionRequirement,
    load_monthly_promotion_registry,
    resolve_monthly_promotion,
)

__all__ = [
    "ContentEvaluationRequest",
    "EvaluationResult",
    "PromotionRequirement",
    "evaluate_content",
    "load_monthly_promotion_registry",
    "resolve_monthly_promotion",
]
