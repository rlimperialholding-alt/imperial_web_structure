"""Fail-closed Gate 1 copy excellence and four-gate publication controls."""

from .engine import evaluate_content
from .models import ContentEvaluationRequest, EvaluationResult

__all__ = ["ContentEvaluationRequest", "EvaluationResult", "evaluate_content"]
