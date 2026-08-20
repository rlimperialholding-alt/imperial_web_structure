from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CanonicalLLMUsage
from .registry import GrowthRegistryError, settings


@dataclass(frozen=True)
class DeepSeekResult:
    request_id: str
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    response_sha256: str


def _api_key() -> str:
    path = Path(settings().deepseek_api_key_file)
    if not path.is_file():
        raise GrowthRegistryError("DeepSeek API key file is missing")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise GrowthRegistryError("DeepSeek API key file permissions are too broad")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 20:
        raise GrowthRegistryError("DeepSeek API key file is invalid")
    return value


def _month_spend(db: Session) -> float:
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    return float(
        db.scalar(
            select(func.coalesce(func.sum(CanonicalLLMUsage.estimated_cost_usd), 0)).where(
                CanonicalLLMUsage.created_at >= month_start,
                CanonicalLLMUsage.provider == "deepseek",
            )
        )
        or 0
    )


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    cfg = settings()
    return round(
        prompt_tokens * cfg.deepseek_input_usd_per_million / 1_000_000
        + completion_tokens * cfg.deepseek_output_usd_per_million / 1_000_000,
        8,
    )


def complete_json(
    db: Session,
    *,
    system_prompt: str,
    user_prompt: str,
    purpose: str,
    run_id: str | None,
    high_stakes: bool = False,
    max_tokens: int = 2_000,
) -> DeepSeekResult:
    cfg = settings()
    if cfg.deepseek_monthly_budget_usd <= 0:
        raise GrowthRegistryError("DeepSeek monthly budget is not configured")
    if cfg.deepseek_input_usd_per_million <= 0 or cfg.deepseek_output_usd_per_million <= 0:
        raise GrowthRegistryError("DeepSeek token pricing is not configured")
    if _month_spend(db) >= cfg.deepseek_monthly_budget_usd:
        raise GrowthRegistryError("DeepSeek monthly budget exhausted")
    model = cfg.deepseek_high_stakes_model if high_stakes else cfg.deepseek_routine_model
    request_id = f"DS-{uuid4().hex[:20].upper()}"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
                + "\nKizárólag érvényes JSON-t adj vissza. Ne találj ki tényt vagy forrást.",
            },
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": max(1, min(max_tokens, 8_000)),
    }
    try:
        response = httpx.post(
            f"{cfg.deepseek_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        raw: dict[str, Any] = response.json()
        content = str(raw["choices"][0]["message"]["content"])
        json.loads(content)
        usage = raw.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        response_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        cost = _estimate_cost(prompt_tokens, completion_tokens)
        status = "completed"
    except (
        httpx.HTTPError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        db.add(
            CanonicalLLMUsage(
                request_id=request_id,
                run_id=run_id,
                provider="deepseek",
                model=model,
                purpose=purpose,
                status=f"failed:{type(exc).__name__}"[:30],
            )
        )
        db.commit()
        raise GrowthRegistryError(f"DeepSeek request failed: {type(exc).__name__}") from exc
    db.add(
        CanonicalLLMUsage(
            request_id=request_id,
            run_id=run_id,
            provider="deepseek",
            model=model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=cost,
            response_sha256=response_hash,
            status=status,
        )
    )
    db.commit()
    return DeepSeekResult(
        request_id=request_id,
        model=model,
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
        response_sha256=response_hash,
    )
