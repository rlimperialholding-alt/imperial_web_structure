from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.connectors.base import MetricsConnector
from app.connectors.ga4 import GA4Connector
from app.connectors.google_business import GoogleBusinessProfileConnector
from app.connectors.search_console import SearchConsoleConnector
from app.db import get_db
from app.schemas import ReviewReplyRequest, SyncRequest, SyncResult
from app.security import require_admin_token
from app.services.business_profile_service import sync_business_profile_directory
from app.services.sync_service import sync_metrics

router = APIRouter(prefix="/sync", tags=["sync"], dependencies=[Depends(require_admin_token)])


def _resolve_targets(
    configured: list[dict[str, str]], request: SyncRequest, key_name: str
) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for item in configured:
        brand = item.get("brand", "unknown")
        entity_key = item.get(key_name, "")
        if not entity_key:
            continue
        if request.brand and request.brand != brand:
            continue
        if request.entity_key and request.entity_key != entity_key:
            continue
        targets.append((brand, entity_key))
    if request.entity_key and not targets:
        targets.append((request.brand or "manual", request.entity_key))
    return targets


def _run(
    db: Session,
    settings: Settings,
    request: SyncRequest,
    configured: list[dict[str, str]],
    key_name: str,
    factory: Callable[[Settings], MetricsConnector],
) -> list[SyncResult]:
    targets = _resolve_targets(configured, request, key_name)
    if not targets:
        raise HTTPException(status_code=422, detail="No configured integration target matched")
    connector = factory(settings)
    results: list[SyncResult] = []
    for brand, entity_key in targets:
        run = sync_metrics(
            db,
            connector=connector,
            brand=brand,
            entity_key=entity_key,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        results.append(
            SyncResult(
                run_id=run.id,
                source=run.source,
                entity_key=run.entity_key,
                rows_written=run.rows_written,
                status=run.status.value,
            )
        )
    return results


@router.post("/ga4", response_model=list[SyncResult])
def sync_ga4(
    request: SyncRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[SyncResult]:
    return _run(db, settings, request, settings.ga4_properties_json, "property_id", GA4Connector)


@router.post("/search-console", response_model=list[SyncResult])
def sync_search_console(
    request: SyncRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[SyncResult]:
    return _run(
        db,
        settings,
        request,
        settings.search_console_sites_json,
        "site_url",
        SearchConsoleConnector,
    )


@router.post("/google-business", response_model=list[SyncResult])
def sync_google_business(
    request: SyncRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[SyncResult]:
    return _run(
        db,
        settings,
        request,
        settings.gbp_locations_json,
        "location_id",
        GoogleBusinessProfileConnector,
    )


@router.post("/google-business/directory")
def sync_google_business_directory_route(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    return sync_business_profile_directory(db, settings)


@router.get("/google-business/accounts")
def get_google_business_accounts(
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    return GoogleBusinessProfileConnector(settings).list_accounts()


@router.get("/google-business/{account_id}/locations")
def get_google_business_locations(
    account_id: str,
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    return GoogleBusinessProfileConnector(settings).list_locations(account_id)


@router.get("/google-business/{account_id}/{location_id}/reviews")
def get_google_business_reviews(
    account_id: str,
    location_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return GoogleBusinessProfileConnector(settings).list_reviews(account_id, location_id)


@router.put("/google-business/{account_id}/{location_id}/reviews/{review_id}/reply")
def reply_to_google_business_review(
    account_id: str,
    location_id: str,
    review_id: str,
    request: ReviewReplyRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return GoogleBusinessProfileConnector(settings).reply_to_review(
        account_id, location_id, review_id, request.comment
    )


@router.post("/google-business/{account_id}/{location_id}/posts")
def create_google_business_post(
    account_id: str,
    location_id: str,
    payload: dict[str, Any],
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return GoogleBusinessProfileConnector(settings).create_local_post(
        account_id, location_id, payload
    )
