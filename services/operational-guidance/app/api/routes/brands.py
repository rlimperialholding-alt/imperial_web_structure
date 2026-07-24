from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.brand_registry import registry_status
from app.config import Settings, get_settings
from app.security import require_admin_token

router = APIRouter(
    prefix="/brands",
    tags=["brand registry"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("")
def list_brands(settings: Settings = Depends(get_settings)) -> list[dict[str, Any]]:
    return registry_status(settings)


@router.get("/{brand_key}")
def get_brand(
    brand_key: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    for brand in registry_status(settings):
        if brand["key"] == brand_key:
            return brand
    raise HTTPException(status_code=404, detail="Brand not found")
