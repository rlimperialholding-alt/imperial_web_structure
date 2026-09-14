from __future__ import annotations

import csv
import html
import io
import json
import secrets
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import (
    TypehouseArtifactIn,
    TypehouseJobIn,
    TypehouseQARunIn,
    TypehouseSourceImportIn,
)
from app.security import current_user, require_api_token, require_internal_job_token
from app.services.typehouse_factory import (
    TypehouseError,
    create_job,
    create_source_import,
    get_job,
    import_status,
    record_qa_run,
    register_artifact,
    retry_job,
    serialize_job,
    set_stream_paused,
    workspace,
)

FACTORY_ROLES = {
    "owner",
    "managing-director",
    "marketing",
    "creative-director",
    "technical-prep",
    "designer",
    "legal",
    "platform-admin",
}
MAX_IMPORT_BYTES = 1024 * 1024
DatabaseSession = Annotated[Session, Depends(get_db)]
SourceFile = Annotated[UploadFile, File(...)]


def _api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TypehouseError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": str(exc)},
        )
    if isinstance(exc, ValidationError):
        return HTTPException(
            status_code=422,
            detail={"error": "SCHEMA_VALIDATION_FAIL", "issues": exc.errors()},
        )
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"error": "NOT_FOUND"})
    return HTTPException(
        status_code=409, detail={"error": "FACTORY_OPERATION_FAILED", "message": str(exc)}
    )


def _ui_user(request: Request, db: Session) -> RedirectResponse | None:
    """UI-határ: belépéshez és gyári szerepkörhöz kötés.

    Hiteles felhasználó esetén ``None`` (a hívó maga kérdezi le a felhasználót),
    egyébként konstans login-redirect. Fail-closed XSS-határ: felhasználói
    adat (útvonal, query, session-érték) soha nem kerül a Location fejlécbe,
    és a felhasználó-objektum nem kerül közvetlenül a route válaszába.
    """
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.active or user.must_change_password or user.role not in FACTORY_ROLES:
        raise HTTPException(
            status_code=403, detail="Nincs jogosultság a Typehouse Factory használatához."
        )
    return None


def _csrf(request: Request) -> str:
    token = str(request.session.get("typehouse_factory_csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["typehouse_factory_csrf"] = token
    return token


def _check_csrf(request: Request, submitted: object) -> None:
    expected = str(request.session.get("typehouse_factory_csrf") or "")
    if not expected or not secrets.compare_digest(expected, str(submitted or "")):
        raise HTTPException(status_code=403, detail="Érvénytelen CSRF token.")


def _parse_import_payload(name: str, payload: bytes) -> list[str]:
    if len(payload) > MAX_IMPORT_BYTES:
        raise TypehouseError("IMPORT_FILE_TOO_LARGE", "A forráslista legfeljebb 1 MiB lehet.", 413)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TypehouseError(
            "IMPORT_ENCODING_INVALID", "A fájl UTF-8 kódolása kötelező.", 422
        ) from exc
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else "txt"
    urls: list[str] = []
    if suffix == "json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TypehouseError("IMPORT_JSON_INVALID", "A JSON forráslista hibás.", 422) from exc
        if isinstance(parsed, dict):
            parsed = parsed.get("source_urls")
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise TypehouseError(
                "IMPORT_JSON_INVALID", "A JSON source_urls szöveges tömb legyen.", 422
            )
        urls = [item.strip() for item in parsed if item.strip()]
    elif suffix == "csv":
        rows = list(csv.reader(io.StringIO(text)))
        for row in rows:
            candidate = next(
                (cell.strip() for cell in row if cell.strip().lower().startswith("https://")), ""
            )
            if candidate:
                urls.append(candidate)
    elif suffix == "txt":
        urls = [line.strip() for line in text.splitlines() if line.strip()]
    else:
        raise TypehouseError(
            "IMPORT_FILE_TYPE_INVALID", "Csak .txt, .csv vagy .json forráslista fogadható.", 422
        )
    if not urls:
        raise TypehouseError("IMPORT_EMPTY", "A fájl nem tartalmaz HTTPS forrás URL-t.", 422)
    return urls


def build_typehouse_factory_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/typehouse-factory/health", dependencies=[Depends(require_api_token)])
    def factory_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "processing_enabled": settings.typehouse_factory_processing_enabled,
            "generator_concurrency": settings.typehouse_factory_concurrency,
            "required_consecutive_qa_passes": (
                settings.typehouse_factory_required_consecutive_passes
            ),
            "render_provider": settings.typehouse_factory_render_provider,
        }

    @router.post("/v1/source-imports", status_code=201, dependencies=[Depends(require_api_token)])
    def source_import(payload: TypehouseSourceImportIn, db: DatabaseSession) -> dict[str, Any]:
        try:
            row = create_source_import(
                db,
                catalog_id=payload.catalog_id,
                rights_grant_id=payload.rights_grant_id,
                source_urls=payload.source_urls,
                actor="api:typehouse-factory",
            )
            return import_status(db, row.import_id)
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.get("/v1/source-imports/{import_id}", dependencies=[Depends(require_api_token)])
    def source_import_status(import_id: str, db: DatabaseSession) -> dict[str, Any]:
        try:
            return import_status(db, import_id)
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.post("/v1/type-house-jobs", status_code=201, dependencies=[Depends(require_api_token)])
    async def type_house_job(
        request: Request,
        db: DatabaseSession,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        try:
            raw = await request.json()
            if not isinstance(raw, dict) or "source_urls" in raw or "sources" in raw:
                raise TypehouseError(
                    "SINGLE_HOUSE_REQUIRED",
                    "Egy generátorhívás pontosan egy source_url mezőt fogadhat.",
                    422,
                )
            payload = TypehouseJobIn.model_validate(raw)
            row = create_job(
                db,
                payload,
                idempotency_key=idempotency_key or "",
                actor="api:typehouse-factory",
            )
            return serialize_job(db, row)
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.get("/v1/type-house-jobs/{job_id}", dependencies=[Depends(require_api_token)])
    def type_house_job_status(job_id: str, db: DatabaseSession) -> dict[str, Any]:
        try:
            return serialize_job(db, get_job(db, job_id))
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.post("/v1/type-house-jobs/{job_id}/retry", dependencies=[Depends(require_api_token)])
    def type_house_job_retry(job_id: str, db: DatabaseSession) -> dict[str, Any]:
        try:
            return serialize_job(db, retry_job(db, job_id, "api:typehouse-factory"))
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.get("/v1/type-house-jobs/{job_id}/package", dependencies=[Depends(require_api_token)])
    def type_house_job_package(job_id: str, db: DatabaseSession) -> dict[str, str]:
        try:
            row = get_job(db, job_id)
            if row.status != "COMPLETED" or not row.package_url or not row.package_manifest_sha256:
                raise TypehouseError(
                    "PACKAGE_NOT_RELEASED", "A csomag még nem teljesítette a két független QA-kört."
                )
            return {
                "job_id": row.job_id,
                "package_url": row.package_url,
                "sha256": row.package_manifest_sha256,
            }
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.post("/v1/catalog-streams/{stream_id}/pause", dependencies=[Depends(require_api_token)])
    def pause_stream(stream_id: str, request: Request, db: DatabaseSession) -> dict[str, Any]:
        try:
            row = set_stream_paused(
                db, stream_id, True, "api:typehouse-factory", request.query_params.get("reason")
            )
            return {"stream_id": row.stream_id, "catalog_id": row.catalog_id, "paused": row.paused}
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.post(
        "/v1/catalog-streams/{stream_id}/resume", dependencies=[Depends(require_api_token)]
    )
    def resume_stream(stream_id: str, db: DatabaseSession) -> dict[str, Any]:
        try:
            row = set_stream_paused(db, stream_id, False, "api:typehouse-factory")
            return {"stream_id": row.stream_id, "catalog_id": row.catalog_id, "paused": row.paused}
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.post(
        "/v1/internal/type-house-jobs/{job_id}/artifacts",
        status_code=201,
        dependencies=[Depends(require_internal_job_token)],
    )
    def artifact(job_id: str, payload: TypehouseArtifactIn, db: DatabaseSession) -> dict[str, Any]:
        try:
            row = register_artifact(db, job_id, payload, "internal:typehouse-producer")
            return {"artifact_id": row.artifact_id, "role": row.role, "sha256": row.sha256}
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.post(
        "/v1/internal/type-house-jobs/{job_id}/qa-runs",
        status_code=201,
        dependencies=[Depends(require_internal_job_token)],
    )
    def qa_run(job_id: str, payload: TypehouseQARunIn, db: DatabaseSession) -> dict[str, Any]:
        try:
            row = record_qa_run(db, job_id, payload, "internal:typehouse-orchestrator")
            return {
                "qa_run_id": row.qa_run_id,
                "run_number": row.run_number,
                "decision": row.decision,
            }
        except Exception as exc:
            raise _api_error(exc) from exc

    @router.get("/housevision/typehouse-factory", response_class=HTMLResponse)
    def factory_page(request: Request, db: DatabaseSession):
        redirect = _ui_user(request, db)
        if redirect is not None:
            return redirect
        user = current_user(request, db)
        assert user is not None  # A _ui_user ellenőrzés után nem lehet None.
        return templates.TemplateResponse(
            request=request,
            name="housevision_typehouse_factory.html",
            context={
                "user": user,
                "active": "housevision",
                "csrf_token": _csrf(request),
                # A query param csak HTML-escape-elve kerül a válaszba;
                # a Jinja autoescape így kétszeresen védett.
                "notice": html.escape(request.query_params.get("notice") or ""),
                **workspace(db),
            },
        )

    @router.post("/housevision/typehouse-factory/jobs")
    async def factory_job_ui(request: Request, db: DatabaseSession):
        redirect = _ui_user(request, db)
        if redirect is not None:
            return redirect
        user = current_user(request, db)
        assert user is not None  # A _ui_user ellenőrzés után nem lehet None.
        form = await request.form()
        _check_csrf(request, form.get("csrf_token"))
        try:
            payload = TypehouseJobIn(
                source_url=str(form.get("source_url") or ""),
                catalog_id=str(form.get("catalog_id") or "imperial-typehouses-hu"),
                rights_grant_id=str(form.get("rights_grant_id") or "auto"),
            )
            create_job(
                db,
                payload,
                idempotency_key=f"ui:{user.email}:{secrets.token_hex(16)}",
                actor=user.email,
            )
            notice = "Az egyház-job bekerült a tartós, soros feldolgozásba."
        except Exception as exc:
            notice = f"Rögzítés blokkolva: {exc}"
        return RedirectResponse(
            f"/housevision/typehouse-factory?notice={quote(notice)}", status_code=303
        )

    @router.post("/housevision/typehouse-factory/imports")
    async def factory_import_ui(
        request: Request,
        source_file: SourceFile,
        db: DatabaseSession,
    ):
        redirect = _ui_user(request, db)
        if redirect is not None:
            return redirect
        user = current_user(request, db)
        assert user is not None  # A _ui_user ellenőrzés után nem lehet None.
        form = await request.form()
        _check_csrf(request, form.get("csrf_token"))
        try:
            data = await source_file.read(MAX_IMPORT_BYTES + 1)
            urls = _parse_import_payload(source_file.filename or "sources.txt", data)
            row = create_source_import(
                db,
                catalog_id=str(form.get("catalog_id") or "imperial-typehouses-hu"),
                rights_grant_id=str(form.get("rights_grant_id") or "auto"),
                source_urls=urls,
                actor=user.email,
                source_file_name=source_file.filename,
            )
            notice = (
                f"Import regisztrálva: {row.registered_count} új, {row.duplicate_count} duplikátum."
            )
        except Exception as exc:
            notice = f"Import blokkolva: {exc}"
        return RedirectResponse(
            f"/housevision/typehouse-factory?notice={quote(notice)}", status_code=303
        )

    @router.post("/housevision/typehouse-factory/streams/{stream_id}/{action}")
    async def stream_ui(stream_id: str, action: str, request: Request, db: DatabaseSession):
        redirect = _ui_user(request, db)
        if redirect is not None:
            return redirect
        user = current_user(request, db)
        assert user is not None  # A _ui_user ellenőrzés után nem lehet None.
        form = await request.form()
        _check_csrf(request, form.get("csrf_token"))
        if action not in {"pause", "resume"}:
            raise HTTPException(status_code=404)
        set_stream_paused(
            db, stream_id, action == "pause", user.email, str(form.get("reason") or "") or None
        )
        return RedirectResponse("/housevision/typehouse-factory", status_code=303)

    @router.post("/housevision/typehouse-factory/jobs/{job_id}/retry")
    async def factory_retry_ui(job_id: str, request: Request, db: DatabaseSession):
        redirect = _ui_user(request, db)
        if redirect is not None:
            return redirect
        user = current_user(request, db)
        assert user is not None  # A _ui_user ellenőrzés után nem lehet None.
        form = await request.form()
        _check_csrf(request, form.get("csrf_token"))
        try:
            row = retry_job(db, job_id, user.email)
            notice = f"Új feldolgozási revízió sorba állítva: {row.job_id}."
        except Exception as exc:
            notice = f"Újrafuttatás blokkolva: {exc}"
        return RedirectResponse(
            f"/housevision/typehouse-factory?notice={quote(notice)}", status_code=303
        )

    return router
