from __future__ import annotations

import html
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from ..database import SessionLocal, engine
from . import models as authority_models  # noqa: F401
from .config import ReaderSettings
from .routes import dashboard_data, router
from .service import readiness


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="Imperial ÉTDR–OÉNY Reader", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health/live")
def live():
    return {"status": "live"}


@app.get("/health/ready")
def ready():
    settings = ReaderSettings.from_env()
    with SessionLocal() as db:
        try:
            db.execute(text("SELECT 1"))
            is_ready, detail = readiness(db, settings)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail={"database": "unavailable"}) from exc
    # A deliberately disabled policy gate is an operationally healthy, fail-closed state.
    if not is_ready and settings.enabled:
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ready", **detail}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    settings = ReaderSettings.from_env()
    with SessionLocal() as db:
        data = dashboard_data(db)
    latest = data["latest"]
    latest_text = "Még nem futott tesztkör."
    if isinstance(latest, dict):
        latest_text = (
            f"{html.escape(str(latest['mode']))} / {html.escape(str(latest['status']))} — "
            f"{latest['records_seen']} rekord"
        )
    gate = (
        "ENGEDÉLYEZVE"
        if settings.policy_authorized and settings.policy_evidence_valid
        else "ZÁRVA – érvényes írásos engedély szükséges"
    )
    return HTMLResponse(
        "<!doctype html><html lang='hu'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>ÉTDR–OÉNY olvasó</title><style>body{font:16px system-ui;background:#f4f5f7;"
        "color:#182230;margin:0}.card{max-width:760px;margin:8vh auto;background:white;"
        "padding:32px;"
        "border-radius:18px;box-shadow:0 8px 30px #0001}h1{margin-top:0}.ok{color:#087443}"
        ".stop{color:#a33b17}dl{display:grid;grid-template-columns:180px 1fr;gap:12px}"
        "</style></head><body><main class='card'><h1>ÉTDR–OÉNY olvasó</h1>"
        "<p class='ok'>A szolgáltatás működik és az adatbázis elérhető.</p><dl>"
        f"<dt>Tárolt rekordok</dt><dd>{data['records']}</dd>"
        f"<dt>Mélyített rekordok</dt><dd>{data['deep_records']}</dd>"
        f"<dt>Leadre vár</dt><dd>{data['lead_pending']}</dd>"
        f"<dt>Lead-generátorba átadva</dt><dd>{data['lead_delivered']}</dd>"
        f"<dt>Legutóbbi futás</dt><dd>{latest_text}</dd>"
        f"<dt>Automatizálási kapu</dt><dd class='stop'>{html.escape(gate)}</dd>"
        "<dt>Adatvédelmi mód</dt><dd>Kapcsolati és természetes személyi adat nem kerül be.</dd>"
        "</dl></main></body></html>"
    )
