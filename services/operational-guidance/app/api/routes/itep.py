from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.connectors.itep import ItepConnector
from app.security import require_admin_token

router = APIRouter(
    prefix="/itep",
    tags=["ITEP"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/ready")
async def itep_ready(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return await ItepConnector(settings).readiness()


@router.get("/integration-control-room")
async def integration_control_room(
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return await ItepConnector(settings).dashboard()


@router.post("/crm/sync")
async def sync_live_crm(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return await ItepConnector(settings).sync_live_crm()
