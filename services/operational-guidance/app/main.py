from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import (
    brands,
    checklists,
    health,
    ingatlan,
    operations,
    process_cards,
    publications,
    sync,
)
from app.config import get_settings
from app.db import Base, engine
from app.observability import RequestContextMiddleware, RequestSizeLimitMiddleware

settings = get_settings()
log_level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(log_level))


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.startup_validate_config:
        settings.validate_runtime()
    for directory in settings.runtime_directories():
        directory.mkdir(parents=True, exist_ok=True)
    if settings.auto_create_db_schema:
        Base.metadata.create_all(bind=engine)
    yield


docs_url = "/docs" if settings.docs_enabled else None
redoc_url = "/redoc" if settings.docs_enabled else None
openapi_url = "/openapi.json" if settings.docs_enabled else None
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
app.add_middleware(RequestContextMiddleware)
if settings.trusted_hosts_json and settings.trusted_hosts_json != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_json)
if settings.cors_origins_json:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_json,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Admin-Token",
            "X-Idempotency-Key",
            "X-Request-ID",
        ],
    )

app.include_router(health.router)
app.include_router(brands.router, prefix=settings.api_prefix)
app.include_router(sync.router, prefix=settings.api_prefix)
app.include_router(ingatlan.router, prefix=settings.api_prefix)
app.include_router(publications.router, prefix=settings.api_prefix)
app.include_router(process_cards.router, prefix=settings.api_prefix)
app.include_router(checklists.router, prefix=settings.api_prefix)
app.include_router(operations.router, prefix=settings.api_prefix)
