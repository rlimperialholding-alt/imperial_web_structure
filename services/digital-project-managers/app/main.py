from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app import __version__
from app.api import router
from app.config import get_settings
from app.db import database_ready


def create_app() -> FastAPI:
    app = FastAPI(
        title="Imperial Intelligence Digital Project Managers",
        version=__version__,
        docs_url="/docs" if get_settings().app_env != "production" else None,
        redoc_url=None,
    )
    app.include_router(router)

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready", tags=["health"])
    def ready() -> dict[str, str]:
        if not database_ready():
            raise HTTPException(status_code=503, detail="Database unavailable")
        return {"status": "ready"}

    return app


app = create_app()
