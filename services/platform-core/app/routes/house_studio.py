from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.security import require_internal_job_token, require_role
from app.services.house_batch import HouseBatchError, dry_run_batch, parse_batch_json
from app.services.house_catalog import public_catalog
from app.services.house_plan_execution import (
    active_source_for_house,
    annotate_dry_run_duplicates,
    approve_source,
    authorize_house_studio,
    batch_retry_context,
    block_source,
    create_source_revision,
    execute_batch,
    house_studio_workspace,
    houseplan_batch_detail,
    houseplan_detail,
    ingest_signed_permission_replica,
    list_houseplan_sources,
    review_plan,
    revoke_source,
)

HOUSE_STUDIO_READ_ROLES = (
    "technical-prep",
    "designer",
    "platform-admin",
    "legal",
    "managing-director",
)
HOUSE_STUDIO_CREATE_ROLES = ("technical-prep", "platform-admin")
HOUSE_SOURCE_APPROVE_ROLES = ("legal", "managing-director", "platform-admin")
DatabaseSession = Annotated[Session, Depends(get_db)]
HouseStudioReader = Annotated[User, Depends(require_role(*HOUSE_STUDIO_READ_ROLES))]
HouseStudioCreator = Annotated[User, Depends(require_role(*HOUSE_STUDIO_CREATE_ROLES))]
HouseSourceApprover = Annotated[User, Depends(require_role(*HOUSE_SOURCE_APPROVE_ROLES))]


def _sample_rows() -> list[dict[str, Any]]:
    return [
        {
            "brand": "Imperial",
            "technology": "timber-frame",
            "gross_area_m2": "126",
            "floors": 1,
            "layout": "compact",
            "roof": "gable",
            "style": "kortárs",
            "rooms": [
                {"type": "entrance", "name": "Előtér", "target_area_m2": "16.32", "level": 1},
                {"type": "living", "name": "Nappali", "target_area_m2": "19.72", "level": 1},
                {"type": "kitchen", "name": "Konyha", "target_area_m2": "15.60", "level": 1},
                {"type": "bathroom", "name": "Fürdő", "target_area_m2": "11.60", "level": 1},
                {"type": "bedroom", "name": "Háló 1", "target_area_m2": "10.54", "level": 1},
                {"type": "bedroom", "name": "Háló 2", "target_area_m2": "10.54", "level": 1},
            ],
        }
    ]


def _parse_budapest_datetime_local(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("A lejárat helyi, Europe/Budapest időpont legyen időzóna-offset nélkül.")
    zone = ZoneInfo("Europe/Budapest")
    candidates = [parsed.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [
        candidate
        for candidate in candidates
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == parsed
    ]
    if not valid:
        raise ValueError("A megadott helyi időpont a tavaszi óraátállítás miatt nem létezik.")
    if len(valid) == 2 and valid[0].utcoffset() != valid[1].utcoffset():
        raise ValueError(
            "A megadott helyi időpont az őszi óraátállítás miatt kétértelmű; "
            "válasszon egyértelmű időpontot."
        )
    return valid[0].astimezone(UTC)


def _source(db: Session, house_id: str) -> dict[str, Any]:
    return active_source_for_house(db, house_id)


def _authorize_rows(
    db: Session, user: User, rows: list[dict[str, Any]], permission: str
) -> tuple[str, str, set[str]]:
    project_ids = {str(row.get("project_id") or "HOUSE-CATALOG-GOVERNANCE").strip() for row in rows}
    revisions: list[str] = []
    subject = ""
    for project_id in sorted(project_ids):
        subject, revision = authorize_house_studio(db, user, permission, project_id=project_id)
        revisions.append(revision)
    permission_revision = (
        "itep-batch:" + hashlib.sha256("\n".join(revisions).encode("utf-8")).hexdigest()
    )
    return subject, permission_revision, project_ids


def _can(db: Session, user: User, permission: str, project_id: str | None = None) -> bool:
    try:
        authorize_house_studio(db, user, permission, project_id=project_id)
        return True
    except PermissionError:
        return False


def _page_permissions(db: Session, user: User) -> dict[str, bool]:
    return {
        "source_create": _can(db, user, "ii.house-source.create"),
        "source_approve": _can(db, user, "ii.house-source.approve"),
        "source_revoke": _can(db, user, "ii.house-source.revoke"),
    }


def _csrf_token(request: Request) -> str:
    token = str(request.session.get("house_studio_csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["house_studio_csrf"] = token
    return token


def _require_csrf(request: Request, form: Any) -> None:
    expected = str(request.session.get("house_studio_csrf") or "")
    supplied = str(form.get("csrf_token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Érvénytelen CSRF token.")
    origin = str(request.headers.get("origin") or "")
    if origin and not origin.rstrip("/").endswith(f"//{request.url.netloc}"):
        raise HTTPException(status_code=403, detail="Eltérő Origin fejléc.")


def _require_api_csrf(request: Request) -> None:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="API writes require application/json.")
    expected = str(request.session.get("house_studio_csrf") or "")
    supplied = str(request.headers.get("x-csrf-token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Invalid API CSRF token.")
    origin = str(request.headers.get("origin") or "")
    if origin and not origin.rstrip("/").endswith(f"//{request.url.netloc}"):
        raise HTTPException(status_code=403, detail="Cross-origin API write is forbidden.")


def build_house_studio_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/internal/house-studio/permission-replica",
        dependencies=[Depends(require_internal_job_token)],
    )
    async def house_studio_permission_replica(request: Request, db: DatabaseSession):
        if not settings.internal_job_token or not settings.itep_identity_shared_secret:
            raise HTTPException(
                status_code=503,
                detail="ITEP permission replica ingestion is not configured.",
            )
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Permission replica root must be a JSON object.")
            inserted = ingest_signed_permission_replica(
                db,
                payload=payload,
                signature=request.headers.get("x-itep-signature", ""),
                secret=settings.itep_identity_shared_secret,
            )
            return {
                "accepted": True,
                "inserted": inserted,
                "revision": payload["revision"],
            }
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/house-studio", response_class=HTMLResponse)
    def house_studio_page(
        request: Request,
        db: DatabaseSession,
        user: HouseStudioReader,
    ):
        project_id = str(request.query_params.get("project_id") or "").strip()
        batch_status = str(request.query_params.get("batch_status") or "").strip()
        plan_status = str(request.query_params.get("plan_status") or "").strip()
        try:
            authorize_house_studio(
                db,
                user,
                "ii.houseplan.read",
                project_id=project_id or None,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request,
            "house_studio.html",
            {
                "active": "house-studio",
                "batch_json": json.dumps(_sample_rows(), ensure_ascii=False, indent=2),
                "csrf_token": _csrf_token(request),
                "error": None,
                "execution_result": None,
                "houses": public_catalog(db),
                "house_permissions": _page_permissions(db, user),
                "house_workspace": house_studio_workspace(
                    db,
                    batch_status=batch_status,
                    plan_status=plan_status,
                    project_id=project_id,
                ),
                "result": None,
                "selected_house_id": "",
                "sources": list_houseplan_sources(db),
                "user": user,
            },
        )

    @router.get("/house-studio/batches/{batch_id}", response_class=HTMLResponse)
    def house_studio_batch_detail(
        batch_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseStudioReader,
    ):
        try:
            detail = houseplan_batch_detail(db, batch_id)
            project_ids = {
                str(row.get("project_id") or "HOUSE-CATALOG-GOVERNANCE") for row in detail["rows"]
            }
            for project_id in project_ids:
                authorize_house_studio(
                    db,
                    user,
                    "ii.houseplan.read",
                    project_id=project_id,
                )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=batch_id) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request,
            "house_batch_detail.html",
            {
                "active": "house-studio",
                "csrf_token": _csrf_token(request),
                "detail": detail,
                "user": user,
            },
        )

    @router.post("/house-studio/dry-run", response_class=HTMLResponse)
    async def house_studio_dry_run(
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        form = await request.form()
        _require_csrf(request, form)
        selected_house_id = str(form.get("source_house_id") or "").strip()
        batch_json = str(form.get("batch_json") or "")
        result = None
        error = None
        try:
            rows = parse_batch_json(batch_json)
            source = _source(db, selected_house_id)
            actor_subject, permission_revision, _projects = _authorize_rows(
                db, user, rows, "ii.houseplan.generate"
            )
            result = annotate_dry_run_duplicates(
                db,
                dry_run_batch(
                    rows,
                    source=source,
                    actor_subject=actor_subject,
                    permission_revision=permission_revision,
                    pricing_revision="preview:no-pricing:v1",
                    secret=settings.session_secret,
                    execution_allowed=True,
                ),
            )
        except (HouseBatchError, PermissionError) as exc:
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "house_studio.html",
            {
                "active": "house-studio",
                "batch_json": batch_json,
                "csrf_token": _csrf_token(request),
                "error": error,
                "execution_result": None,
                "houses": public_catalog(db),
                "house_permissions": _page_permissions(db, user),
                "house_workspace": house_studio_workspace(db),
                "result": result,
                "selected_house_id": selected_house_id,
                "sources": list_houseplan_sources(db),
                "user": user,
            },
            status_code=422 if error else 200,
        )

    @router.post("/api/house-studio/dry-run")
    async def house_studio_dry_run_api(
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise HouseBatchError("A kérés gyökéreleme JSON-objektum legyen.")
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise HouseBatchError("A rows mezőnek listának kell lennie.")
            source = _source(db, str(payload.get("source_house_id") or ""))
            actor_subject, permission_revision, _projects = _authorize_rows(
                db, user, rows, "ii.houseplan.generate"
            )
            return annotate_dry_run_duplicates(
                db,
                dry_run_batch(
                    rows,
                    source=source,
                    actor_subject=actor_subject,
                    permission_revision=permission_revision,
                    pricing_revision=str(
                        payload.get("pricing_revision") or "preview:no-pricing:v1"
                    ),
                    secret=settings.session_secret,
                    include_svg=bool(payload.get("include_svg", False)),
                    execution_allowed=True,
                ),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (HouseBatchError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/house-studio/execute", response_class=HTMLResponse)
    async def house_studio_execute(
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        form = await request.form()
        _require_csrf(request, form)
        selected_house_id = str(form.get("source_house_id") or "").strip()
        batch_json = str(form.get("batch_json") or "")
        error = None
        execution_result = None
        try:
            rows = parse_batch_json(batch_json)
            source = _source(db, selected_house_id)
            actor_subject, permission_revision, projects = _authorize_rows(
                db, user, rows, "ii.houseplan.generate"
            )
            execution_result = execute_batch(
                db,
                rows=rows,
                source=source,
                actor_subject=actor_subject,
                permission_revision=permission_revision,
                pricing_revision=str(form.get("pricing_revision") or "preview:no-pricing:v1"),
                dry_run_token=str(form.get("dry_run_token") or ""),
                idempotency_key=str(form.get("idempotency_key") or ""),
                secret=settings.session_secret,
                authorized_project_ids=projects,
            )
        except (HouseBatchError, PermissionError) as exc:
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "house_studio.html",
            {
                "active": "house-studio",
                "batch_json": batch_json,
                "csrf_token": _csrf_token(request),
                "error": error,
                "execution_result": execution_result,
                "houses": public_catalog(db),
                "house_permissions": _page_permissions(db, user),
                "house_workspace": house_studio_workspace(db),
                "result": None,
                "selected_house_id": selected_house_id,
                "sources": list_houseplan_sources(db),
                "user": user,
            },
            status_code=422 if error else 200,
        )

    @router.post("/api/house-studio/execute")
    async def house_studio_execute_api(
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        _require_api_csrf(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise HouseBatchError("A kérés gyökéreleme JSON-objektum legyen.")
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise HouseBatchError("A rows mezőnek listának kell lennie.")
            source = _source(db, str(payload.get("source_house_id") or ""))
            actor_subject, permission_revision, projects = _authorize_rows(
                db, user, rows, "ii.houseplan.generate"
            )
            return execute_batch(
                db,
                rows=rows,
                source=source,
                actor_subject=actor_subject,
                permission_revision=permission_revision,
                pricing_revision=str(payload.get("pricing_revision") or "preview:no-pricing:v1"),
                dry_run_token=str(payload.get("dry_run_token") or ""),
                idempotency_key=str(payload.get("idempotency_key") or ""),
                secret=settings.session_secret,
                authorized_project_ids=projects,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (HouseBatchError, json.JSONDecodeError) as exc:
            status = (
                409
                if str(exc)
                in {
                    "stale_dry_run",
                    "idempotency_conflict",
                    "idempotency_in_progress",
                }
                else 422
            )
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @router.post("/house-studio/batches/{batch_id}/retry")
    async def house_studio_batch_retry(
        batch_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            previous, rows, source = batch_retry_context(db, batch_id)
            actor_subject, permission_revision, projects = _authorize_rows(
                db, user, rows, "ii.house-batch.retry"
            )
            preview = dry_run_batch(
                rows,
                source=source,
                actor_subject=actor_subject,
                permission_revision=permission_revision,
                pricing_revision=previous.pricing_revision,
                secret=settings.session_secret,
                include_svg=False,
                execution_allowed=True,
            )
            execute_batch(
                db,
                rows=rows,
                source=source,
                actor_subject=actor_subject,
                permission_revision=permission_revision,
                pricing_revision=previous.pricing_revision,
                dry_run_token=preview["dryRunToken"],
                idempotency_key=f"retry-{batch_id}-{secrets.token_hex(8)}",
                secret=settings.session_secret,
                authorized_project_ids=projects,
            )
            return RedirectResponse("/house-studio", status_code=303)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=batch_id) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, HouseBatchError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/house-studio/plans/{plan_id}/review")
    async def house_studio_review_api(
        plan_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        _require_api_csrf(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="A kérés gyökéreleme JSON-objektum legyen.")
        try:
            detail = houseplan_detail(db, plan_id)
            actor_subject, _permission_revision = authorize_house_studio(
                db,
                user,
                "ii.houseplan.review",
                project_id=detail["plan"].project_id,
            )
            if not request.headers.get("if-match"):
                raise HTTPException(status_code=428, detail="If-Match fejléc kötelező.")
            expected = int(
                str(request.headers.get("if-match") or "").removeprefix('W/"').removesuffix('"')
            )
            plan = review_plan(
                db,
                plan_id=plan_id,
                reviewer_subject=actor_subject,
                decision=str(payload.get("decision") or ""),
                expected_version=expected,
                reason=str(payload.get("reason") or ""),
            )
            return {
                "planId": plan.plan_id,
                "status": plan.status,
                "rowVersion": plan.row_version,
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            status = 409 if "saját" in str(exc) else 403
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc).startswith("version_conflict:"):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=plan_id) from exc

    @router.get("/house-studio/plans/{plan_id}", response_class=HTMLResponse)
    def house_studio_plan_detail(
        plan_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseStudioReader,
    ):
        try:
            detail = houseplan_detail(db, plan_id)
            authorize_house_studio(
                db,
                user,
                "ii.houseplan.read",
                project_id=detail["plan"].project_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=plan_id) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request,
            "house_plan_detail.html",
            {
                "active": "house-studio",
                "csrf_token": _csrf_token(request),
                "can_review": _can(
                    db,
                    user,
                    "ii.houseplan.review",
                    project_id=detail["plan"].project_id,
                ),
                "detail": detail,
                "user": user,
            },
        )

    @router.post("/house-studio/plans/{plan_id}/review", response_class=HTMLResponse)
    async def house_studio_plan_review_form(
        plan_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            detail = houseplan_detail(db, plan_id)
            actor_subject, _revision = authorize_house_studio(
                db,
                user,
                "ii.houseplan.review",
                project_id=detail["plan"].project_id,
            )
            review_plan(
                db,
                plan_id=plan_id,
                reviewer_subject=actor_subject,
                decision=str(form.get("decision") or ""),
                expected_version=int(str(form.get("row_version") or "0")),
                reason=str(form.get("reason") or ""),
            )
            return RedirectResponse(f"/house-studio/plans/{plan_id}", status_code=303)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=plan_id) from exc
        except PermissionError as exc:
            status = 409 if "saját" in str(exc) else 403
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/house-studio/sources", response_class=HTMLResponse)
    async def house_studio_source_create(
        request: Request,
        db: DatabaseSession,
        user: HouseStudioCreator,
    ):
        form = await request.form()
        _require_csrf(request, form)
        evidence_text = str(form.get("evidence_text") or "").strip()
        try:
            actor_subject, _permission_revision = authorize_house_studio(
                db, user, "ii.house-source.create"
            )
            if not evidence_text:
                raise ValueError("A jogi bizonyíték leírása kötelező.")
            expires_raw = str(form.get("expires_at") or "").strip()
            create_source_revision(
                db,
                catalog_version_id=str(form.get("catalog_version_id") or "").strip(),
                legal_basis=str(form.get("legal_basis") or "unknown").strip(),
                licence_scope=str(form.get("licence_scope") or "").strip(),
                evidence_ref=str(form.get("evidence_ref") or "").strip(),
                evidence_sha256=hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
                actor_subject=actor_subject,
                expires_at=(
                    _parse_budapest_datetime_local(expires_raw)
                    if expires_raw
                    else None
                ),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request,
            "house_studio.html",
            {
                "active": "house-studio",
                "batch_json": json.dumps(_sample_rows(), ensure_ascii=False, indent=2),
                "csrf_token": _csrf_token(request),
                "error": None,
                "execution_result": None,
                "houses": public_catalog(db),
                "house_permissions": _page_permissions(db, user),
                "house_workspace": house_studio_workspace(db),
                "result": None,
                "selected_house_id": "",
                "sources": list_houseplan_sources(db),
                "source_notice": "A forrásrevízió jogi ellenőrzésre elküldve.",
                "user": user,
            },
        )

    @router.post("/house-studio/sources/{source_id}/approve")
    async def house_studio_source_approve(
        source_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseSourceApprover,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            actor_subject, _permission_revision = authorize_house_studio(
                db, user, "ii.house-source.approve"
            )
            row = approve_source(db, source_id, actor_subject)
            if row.status != "approved":
                raise ValueError("A forrás jóváhagyása nem zárult le.")
            return RedirectResponse("/house-studio", status_code=303)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=source_id) from exc
        except PermissionError as exc:
            status = 409 if "saját" in str(exc) else 403
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/house-studio/sources/{source_id}/revoke")
    async def house_studio_source_revoke(
        source_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseSourceApprover,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            actor_subject, _permission_revision = authorize_house_studio(
                db, user, "ii.house-source.revoke"
            )
            row = revoke_source(db, source_id, actor_subject, str(form.get("reason") or ""))
            if row.status != "revoked":
                raise ValueError("A forrás visszavonása nem zárult le.")
            return RedirectResponse("/house-studio", status_code=303)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=source_id) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/house-studio/sources/{source_id}/block")
    async def house_studio_source_block(
        source_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseSourceApprover,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            actor_subject, _permission_revision = authorize_house_studio(
                db, user, "ii.house-source.approve"
            )
            block_source(db, source_id, actor_subject, str(form.get("reason") or ""))
            return RedirectResponse("/house-studio", status_code=303)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=source_id) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
