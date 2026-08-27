from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_metrics_access
from app.config import get_settings
from app.db import get_db
from app.observability import metrics_response
from app.readiness import build_readiness_report

router = APIRouter(tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    settings = get_settings()
    return {"status": "alive", "version": settings.app_version}


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response, db: Session = Depends(get_db)):
    report = build_readiness_report(db, get_settings())
    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report.to_dict()


@router.get("/metrics", dependencies=[Depends(require_metrics_access)], include_in_schema=False)
def metrics():
    return metrics_response()
