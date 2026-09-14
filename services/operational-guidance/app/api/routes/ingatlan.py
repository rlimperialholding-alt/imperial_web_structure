from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.connectors.ingatlan import IngatlanConnector
from app.db import get_db
from app.schemas import PhotoOrderRequest
from app.security import require_admin_token
from app.services.ingatlan_service import sync_listing_ids, upsert_listing

router = APIRouter(
    prefix="/ingatlan",
    tags=["ingatlan.com"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/ads/ids")
def list_ad_ids(settings: Settings = Depends(get_settings)) -> list[dict[str, Any]]:
    with IngatlanConnector(settings) as connector:
        return connector.list_ad_ids()


@router.post("/ads/ids/sync")
def sync_ad_ids(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    return sync_listing_ids(db, settings)


@router.get("/ads")
def list_ads(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    with IngatlanConnector(settings) as connector:
        return connector.list_ads(offset=offset, limit=limit)


@router.get("/ads/{own_id}")
def get_ad(own_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    with IngatlanConnector(settings) as connector:
        return connector.get_ad(own_id)


@router.put("/ads/{own_id}")
def put_ad(
    own_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    payload["ownId"] = own_id
    return upsert_listing(db, settings, payload)


@router.delete("/ads/{own_id}")
def delete_ad(own_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    with IngatlanConnector(settings) as connector:
        return connector.delete_ad(own_id)


@router.get("/ads/{own_id}/photos")
def list_photos(
    own_id: str,
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    with IngatlanConnector(settings) as connector:
        return connector.list_photos(own_id)


@router.put("/ads/{own_id}/photos/{photo_own_id}")
async def put_photo(
    own_id: str,
    photo_own_id: str,
    image: UploadFile = File(...),
    order: int = Form(..., ge=1, le=30),
    title: str = Form("", max_length=100),
    label_id: int | None = Form(default=None),
    subtype: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    image_bytes = await image.read()
    with IngatlanConnector(settings) as connector:
        return connector.upsert_photo(
            own_id,
            photo_own_id,
            image=image_bytes,
            order=order,
            title=title,
            label_id=label_id,
            subtype=subtype,
        )


@router.delete("/ads/{own_id}/photos/{photo_own_id}", status_code=204)
def delete_photo(
    own_id: str,
    photo_own_id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    with IngatlanConnector(settings) as connector:
        connector.delete_photo(own_id, photo_own_id)


@router.put("/ads/{own_id}/photo-order")
def set_photo_order(
    own_id: str,
    request: PhotoOrderRequest,
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    with IngatlanConnector(settings) as connector:
        return connector.set_photo_order(own_id, request.photo_own_ids)
