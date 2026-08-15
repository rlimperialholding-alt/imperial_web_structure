from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import HouseStudioPermissionGrant, User
from app.security import current_user, require_role
from app.services.house_designer import (
    ActorScope,
    HouseDesignerError,
    apply_session_command,
    audit_site_read,
    create_session,
    list_sessions,
    list_template_plans,
    session_detail,
)
from app.services.house_designer_adapters import (
    accept_signed_result,
    list_adapters,
    list_session_jobs,
    queue_adapter_job,
    register_adapter,
    review_adapter,
    suspend_adapter,
)
from app.services.house_designer_estimation import (
    create_sandbox_estimate,
    latest_estimate_bundle,
)
from app.services.house_designer_guest import (
    GUEST_CLAIM_COOKIE,
    GUEST_SESSION_COOKIE,
    consume_guest_creation_quota,
    create_guest_design,
    resolve_guest_actor,
    standalone_access_status,
)
from app.services.house_designer_readiness import (
    house_designer_release_readiness,
    request_entitlement_activation,
    review_entitlement_activation,
    set_sandbox_entitlement,
    suspend_entitlement,
)
from app.services.house_designer_rendering import (
    create_sandbox_render,
    list_current_renders,
    revise_sandbox_render,
    sandbox_render_svg,
)
from app.services.house_designer_submission import (
    approval_panel,
    approve_current_design,
    book_consultation,
    list_submission_queue,
    submission_detail,
    submission_review_detail,
    submit_order_request,
    transition_submission_review,
)
from app.services.regulatory_compliance import latest_compliance_result, run_compliance

HOUSE_DESIGNER_ROLES = (
    "customer",
    "sales",
    "designer",
    "technical-prep",
    "project-manager",
    "legal",
    "finance",
    "managing-director",
    "owner",
    "platform-admin",
)
DatabaseSession = Annotated[Session, Depends(get_db)]
HouseDesignerUser = Annotated[User, Depends(require_role(*HOUSE_DESIGNER_ROLES))]
SUBMISSION_REVIEW_ROLES = (
    "sales",
    "designer",
    "technical-prep",
    "project-manager",
    "legal",
    "finance",
    "managing-director",
    "owner",
    "platform-admin",
)
SubmissionReviewer = Annotated[User, Depends(require_role(*SUBMISSION_REVIEW_ROLES))]


def _optional_house_designer_user(request: Request, db: DatabaseSession) -> User | None:
    user = current_user(request, db)
    if user is None:
        return None
    if not user.active or user.must_change_password or user.role not in HOUSE_DESIGNER_ROLES:
        raise HTTPException(status_code=403, detail="Nincs jogosultság.")
    return user


OptionalHouseDesignerUser = Annotated[User | None, Depends(_optional_house_designer_user)]


def _csrf_token(request: Request) -> str:
    token = str(request.session.get("house_designer_csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["house_designer_csrf"] = token
    return token


def _design_etag(detail: dict[str, Any]) -> str:
    """Return the strong validator shared by every session representation."""
    return f'"{detail["revision"]["canonicalSha256"]}"'


def _require_csrf(request: Request, form: Any) -> None:
    expected = str(request.session.get("house_designer_csrf") or "")
    supplied = str(form.get("csrf_token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Érvénytelen munkamenet-védelmi token.")
    origin = str(request.headers.get("origin") or "")
    if origin and not origin.rstrip("/").endswith(f"//{request.url.netloc}"):
        raise HTTPException(status_code=403, detail="Eltérő Origin fejléc.")


def _require_json_write(request: Request) -> None:
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="Csak application/json kérés engedélyezett.")
    expected = str(request.session.get("house_designer_csrf") or "")
    supplied = str(request.headers.get("x-csrf-token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Érvénytelen munkamenet-védelmi token.")
    origin = str(request.headers.get("origin") or "")
    if not origin or not origin.rstrip("/").endswith(f"//{request.url.netloc}"):
        raise HTTPException(status_code=403, detail="Hiányzó vagy eltérő Origin fejléc.")


def _idempotency_key(request: Request) -> str:
    value = str(request.headers.get("idempotency-key") or "").strip()
    if not value:
        raise HTTPException(status_code=428, detail="Idempotency-Key fejléc szükséges.")
    return value


def _optional_row_version(form: Any) -> int | None:
    value = str(form.get("row_version") or "").strip()
    if not value:
        return None
    try:
        result = int(value)
    except ValueError as error:
        raise HouseDesignerError(
            "row_version_invalid", "Érvénytelen jogosultságverzió.", status_code=422
        ) from error
    if result < 1:
        raise HouseDesignerError(
            "row_version_invalid", "Érvénytelen jogosultságverzió.", status_code=422
        )
    return result


def _required_row_version(form: Any) -> int:
    value = _optional_row_version(form)
    if value is None:
        raise HouseDesignerError(
            "row_version_required", "A jogosultságverzió kötelező.", status_code=428
        )
    return value


def _raise_api_error(error: HouseDesignerError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    ) from error


def _scope(user: User, db: Session) -> ActorScope:
    subject = str(user.itep_subject_id or user.email)
    now = datetime.now(UTC)
    grants = db.scalars(
        select(HouseStudioPermissionGrant).where(
            HouseStudioPermissionGrant.subject_id == subject,
            HouseStudioPermissionGrant.permission == "ii.house-designer.read",
            HouseStudioPermissionGrant.status == "active",
            HouseStudioPermissionGrant.valid_from <= now,
            HouseStudioPermissionGrant.expires_at > now,
        )
    ).all()
    global_deny = any(row.effect == "deny" and row.scope_type == "global" for row in grants)
    global_allow = any(row.effect == "allow" and row.scope_type == "global" for row in grants)
    denied_projects = frozenset(
        str(row.project_id)
        for row in grants
        if row.effect == "deny" and row.scope_type == "project" and row.project_id
    )
    allowed_projects = frozenset(
        str(row.project_id)
        for row in grants
        if row.effect == "allow"
        and row.scope_type == "project"
        and row.project_id
        and row.project_id not in denied_projects
    )
    return ActorScope(
        subject_id=subject,
        tenant_id="imperial-holding",
        brand_ids=frozenset({"imperial"}),
        can_read_all_owned=(
            not global_deny and (user.role in {"owner", "managing-director"} or global_allow)
        ),
        project_ids=frozenset() if global_deny else allowed_projects,
        denied_project_ids=denied_projects,
    )


def _guest_scope(request: Request, db: Session, session_id: str | None = None) -> ActorScope:
    token = str(request.cookies.get(GUEST_SESSION_COOKIE) or "")
    try:
        return resolve_guest_actor(
            db,
            guest_session_token=token,
            expected_session_id=session_id,
        )
    except HouseDesignerError as error:
        raise HTTPException(error.status_code, str(error)) from error


def _html_scope(
    request: Request,
    db: Session,
    user: User | None,
    session_id: str | None = None,
) -> ActorScope:
    return _scope(user, db) if user is not None else _guest_scope(request, db, session_id)


def _offline_scope_key(actor: ActorScope, session_id: str) -> str:
    """Bind browser-pending commands to the current actor without exposing its identifier."""
    value = f"{actor.tenant_id}\0{actor.subject_id}\0{session_id}".encode()
    return hashlib.sha256(value).hexdigest()


def _set_guest_cookies(response: Response, access: Any) -> None:
    max_age = settings.house_designer_guest_ttl_hours * 3600
    response.set_cookie(
        GUEST_SESSION_COOKIE,
        access.guest_session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        GUEST_CLAIM_COOKIE,
        access.claim_token,
        max_age=max_age,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


def _payload(form: Any, command_type: str) -> dict[str, Any]:
    integer_fields = {
        "widthMm",
        "depthMm",
        "xMm",
        "yMm",
        "x1Mm",
        "y1Mm",
        "x2Mm",
        "y2Mm",
        "thicknessMm",
        "offsetMm",
        "heightMm",
        "sillHeightMm",
        "clearWidthMm",
        "riserMm",
        "treadMm",
        "headroomMm",
        "landingDepthMm",
        "pitchDeg",
        "northAngleDeg",
        "rotationDeg",
    }
    fields_by_command = {
        "set_footprint": {"levelId", "widthMm", "depthMm"},
        "set_footprint_polygon": {"levelId", "points"},
        "add_level": {"levelType"},
        "clone_level": {"sourceLevelId", "levelType"},
        "remove_level": {"levelId"},
        "add_wall": {
            "levelId",
            "wallId",
            "x1Mm",
            "y1Mm",
            "x2Mm",
            "y2Mm",
            "thicknessMm",
            "wallKind",
        },
        "move_wall": {"levelId", "wallId", "x1Mm", "y1Mm", "x2Mm", "y2Mm"},
        "split_wall": {"levelId", "wallId", "xMm", "yMm"},
        "remove_wall": {"levelId", "wallId"},
        "add_opening": {
            "levelId",
            "openingId",
            "wallId",
            "openingKind",
            "offsetMm",
            "widthMm",
            "heightMm",
            "sillHeightMm",
        },
        "move_opening": {"levelId", "openingId", "wallId", "offsetMm"},
        "resize_opening": {
            "levelId",
            "openingId",
            "widthMm",
            "heightMm",
            "sillHeightMm",
        },
        "remove_opening": {"levelId", "openingId"},
        "add_connection": {
            "levelId",
            "connectionId",
            "roomA",
            "roomB",
            "openingId",
        },
        "remove_connection": {"levelId", "connectionId"},
        "set_stair_geometry": {
            "coreId",
            "clearWidthMm",
            "riserMm",
            "treadMm",
            "headroomMm",
            "landingDepthMm",
        },
        "add_furniture": {
            "levelId",
            "furnitureId",
            "furnitureKind",
            "label",
            "xMm",
            "yMm",
            "widthMm",
            "depthMm",
            "rotationDeg",
        },
        "move_furniture": {
            "levelId",
            "furnitureId",
            "xMm",
            "yMm",
            "rotationDeg",
        },
        "resize_furniture": {"levelId", "furnitureId", "widthMm", "depthMm"},
        "remove_furniture": {"levelId", "furnitureId"},
        "add_room": {
            "levelId",
            "roomId",
            "name",
            "function",
            "xMm",
            "yMm",
            "widthMm",
            "depthMm",
        },
        "move_room": {"levelId", "roomId", "xMm", "yMm"},
        "resize_room": {"levelId", "roomId", "widthMm", "depthMm"},
        "remove_room": {"levelId", "roomId"},
        "set_room_function": {"levelId", "roomId", "name", "function"},
        "set_room_polygon": {"levelId", "roomId", "points"},
        "set_roof": {"levelId", "roofType", "pitchDeg"},
        "set_north": {"northAngleDeg"},
        "set_site": {
            "municipalityCode",
            "postalCode",
            "city",
            "address",
            "parcelNumber",
        },
        "set_configuration": {
            "constructionTechnology",
            "completionLevel",
            "roofType",
            "foundationType",
            "slabType",
            "stairType",
            "technicalPackage",
        },
        "undo_revision": set(),
        "redo_revision": set(),
        "restore_revision": {"targetRevisionId"},
    }
    allowed = fields_by_command.get(command_type)
    if allowed is None:
        raise HouseDesignerError("unknown_command", "Ismeretlen szerkesztési művelet.")
    result: dict[str, Any] = {}
    for key in allowed:
        value = form.get(key)
        if value in {None, ""}:
            continue
        result[key] = int(value) if key in integer_fields else str(value).strip()
    return result


def build_house_designer_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/house-designer/standalone", response_class=HTMLResponse)
    def standalone_workspace(request: Request, db: DatabaseSession):
        current = None
        token = str(request.cookies.get(GUEST_SESSION_COOKIE) or "")
        if token:
            try:
                actor = resolve_guest_actor(db, guest_session_token=token)
                rows = list_sessions(db, actor)
                current = rows[0] if rows else None
            except HouseDesignerError:
                current = None
        return templates.TemplateResponse(
            request,
            "house_designer_standalone.html",
            {
                "user": None,
                "active": "house-designer",
                "access": standalone_access_status(db, brand_id="imperial"),
                "current": current,
                "templates": list_template_plans(db),
                "csrf_token": _csrf_token(request),
                "error": request.query_params.get("error"),
            },
        )

    @router.post("/house-designer/standalone/sessions")
    async def standalone_create(request: Request, db: DatabaseSession):
        form = await request.form()
        _require_csrf(request, form)
        try:
            consume_guest_creation_quota(
                db,
                brand_id="imperial",
                fingerprint_source=(
                    f"{request.client.host if request.client else 'unknown'}|"
                    f"{str(request.headers.get('user-agent') or '')[:256]}"
                ),
            )
            access = create_guest_design(
                db,
                brand_id="imperial",
                title=str(form.get("title") or "Saját házterv"),
                command_id=str(form.get("command_id") or ""),
                origin=str(form.get("origin") or "blank"),
                template_plan_id=str(form.get("template_plan_id") or "") or None,
                width_mm=int(form.get("width_mm") or 10_000),
                depth_mm=int(form.get("depth_mm") or 8_000),
            )
        except (HouseDesignerError, TypeError, ValueError) as error:
            code = getattr(error, "code", "invalid_input")
            if getattr(error, "status_code", 422) == 429:
                raise HTTPException(
                    status_code=429,
                    detail=str(error),
                    headers={"Retry-After": str(settings.house_designer_guest_block_seconds)},
                ) from error
            return RedirectResponse(f"/house-designer/standalone?error={code}", status_code=303)
        response = RedirectResponse(
            f"/house-designer/sessions/{access.design['sessionId']}", status_code=303
        )
        _set_guest_cookies(response, access)
        return response

    @router.get("/house-designer/standalone/sessions/{session_id}", response_class=HTMLResponse)
    def standalone_detail(
        session_id: str,
        request: Request,
        db: DatabaseSession,
    ):
        actor = _guest_scope(request, db, session_id)
        detail = session_detail(db, session_id, actor)
        audit_site_read(
            db,
            actor=actor,
            session_id=session_id,
            revision_id=detail["revision"]["revisionId"],
            site=detail["revision"]["site"],
            channel="standalone-html",
        )
        approval = approval_panel(db, session_id=session_id, actor=actor)
        approval["canAct"] = False
        response = templates.TemplateResponse(
            request,
            "house_designer_detail.html",
            {
                "active": "house-designer",
                "user": SimpleNamespace(name="Vendég tervező", role="customer", email=""),
                "standalone": True,
                "design": detail,
                "estimate": latest_estimate_bundle(
                    db, session_id, detail["revision"]["revisionId"]
                ),
                "compliance": latest_compliance_result(
                    db, session_id=session_id, revision_id=detail["revision"]["revisionId"]
                ),
                "renders": list_current_renders(
                    db,
                    session_id=session_id,
                    revision_id=detail["revision"]["revisionId"],
                    actor=actor,
                ),
                "approval": approval,
                "production_jobs": [],
                "production_adapters_enabled": False,
                "csrf_token": _csrf_token(request),
                "offline_scope_key": _offline_scope_key(actor, session_id),
                "error": request.query_params.get("error"),
                "check_outcome": request.query_params.get("check"),
            },
        )
        response.headers["ETag"] = _design_etag(detail)
        response.headers["Cache-Control"] = "private, no-cache"
        return response

    @router.post("/house-designer/standalone/sessions/{session_id}/commands")
    async def standalone_command(
        session_id: str,
        request: Request,
        db: DatabaseSession,
    ):
        form = await request.form()
        _require_csrf(request, form)
        command_type = str(form.get("command_type") or "")
        try:
            apply_session_command(
                db,
                session_id=session_id,
                actor=_guest_scope(request, db, session_id),
                base_revision_id=str(form.get("base_revision_id") or ""),
                base_canonical_sha256=str(form.get("base_canonical_sha256") or ""),
                command_id=str(form.get("command_id") or ""),
                command_type=command_type,
                payload=_payload(form, command_type),
                change_summary=str(form.get("change_summary") or ""),
            )
        except (HouseDesignerError, ValueError) as error:
            code = getattr(error, "code", "invalid_input")
            return RedirectResponse(
                f"/house-designer/standalone/sessions/{session_id}?error={code}", 303
            )
        return RedirectResponse(f"/house-designer/standalone/sessions/{session_id}", 303)

    @router.post("/house-designer/standalone/sessions/{session_id}/estimate")
    async def standalone_estimate(session_id: str, request: Request, db: DatabaseSession):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_sandbox_estimate(
                db, session_id=session_id, actor=_guest_scope(request, db, session_id)
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/standalone/sessions/{session_id}?error={error.code}", 303
            )
        return RedirectResponse(f"/house-designer/standalone/sessions/{session_id}#estimate", 303)

    @router.post("/house-designer/standalone/sessions/{session_id}/renders")
    async def standalone_render(session_id: str, request: Request, db: DatabaseSession):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_sandbox_render(
                db,
                session_id=session_id,
                actor=_guest_scope(request, db, session_id),
                prompt=str(form.get("prompt") or ""),
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/standalone/sessions/{session_id}?error={error.code}", 303
            )
        return RedirectResponse(f"/house-designer/standalone/sessions/{session_id}#renders", 303)

    @router.get("/house-designer/standalone/renders/{render_id}.svg")
    def standalone_render_asset(render_id: str, request: Request, db: DatabaseSession):
        try:
            svg = sandbox_render_svg(db, render_id=render_id, actor=_guest_scope(request, db))
        except HouseDesignerError as error:
            raise HTTPException(error.status_code, str(error)) from error
        return Response(
            svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.post("/house-designer/standalone/sessions/{session_id}/check")
    async def standalone_check(session_id: str, request: Request, db: DatabaseSession):
        form = await request.form()
        _require_csrf(request, form)
        scope = _guest_scope(request, db, session_id)
        try:
            session_detail(db, session_id, scope)
            result = run_compliance(
                db,
                session_id=session_id,
                tenant_id=scope.tenant_id,
                actor_subject_id=scope.subject_id,
            )
        except (HouseDesignerError, KeyError, ValueError) as error:
            code = getattr(error, "code", "compliance_failed")
            return RedirectResponse(
                f"/house-designer/standalone/sessions/{session_id}?error={code}", 303
            )
        return RedirectResponse(
            f"/house-designer/standalone/sessions/{session_id}?check={result['outcome']}",
            303,
        )

    @router.get("/house-designer", response_class=HTMLResponse)
    def workspace(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        return templates.TemplateResponse(
            request,
            "house_designer.html",
            {
                "active": "house-designer",
                "user": user,
                "sessions": list_sessions(db, _scope(user, db)),
                "templates": list_template_plans(db),
                "csrf_token": _csrf_token(request),
                "error": request.query_params.get("error"),
            },
        )

    @router.get("/api/v1/house-designer/sessions/{session_id}")
    def api_session_detail(
        session_id: str,
        response: Response,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        try:
            actor = _scope(user, db)
            detail = session_detail(db, session_id, actor)
            audit_site_read(
                db,
                actor=actor,
                session_id=session_id,
                revision_id=detail["revision"]["revisionId"],
                site=detail["revision"]["site"],
                channel="api-v1",
            )
            response.headers["ETag"] = _design_etag(detail)
            response.headers["Cache-Control"] = "private, no-cache"
            return detail
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/sessions")
    async def api_create_session(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            return create_session(
                db,
                actor=_scope(user, db),
                brand_id=str(body.get("brandId") or "imperial"),
                title=str(body.get("title") or "Saját házterv"),
                command_id=_idempotency_key(request),
                origin=str(body.get("origin") or "blank"),
                template_plan_id=str(body.get("templatePlanId") or "") or None,
                width_mm=int(body.get("widthMm") or 10_000),
                depth_mm=int(body.get("depthMm") or 8_000),
            )
        except (HouseDesignerError, TypeError, ValueError) as error:
            if isinstance(error, HouseDesignerError):
                _raise_api_error(error)
            raise HTTPException(status_code=422, detail="Hibás méret vagy mezőérték.") from error

    @router.post("/api/v1/house-designer/sessions/{session_id}/commands")
    async def api_command(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: OptionalHouseDesignerUser,
    ):
        _require_json_write(request)
        if_match = str(request.headers.get("if-match") or "").strip().strip('"')
        if not if_match:
            raise HTTPException(status_code=428, detail="If-Match fejléc szükséges.")
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("payload"), dict):
            raise HTTPException(status_code=422, detail="A command envelope hibás.")
        try:
            return apply_session_command(
                db,
                session_id=session_id,
                actor=_html_scope(request, db, user, session_id),
                base_revision_id=str(body.get("baseRevisionId") or ""),
                base_canonical_sha256=if_match,
                command_id=_idempotency_key(request),
                command_type=str(body.get("commandType") or ""),
                payload=body["payload"],
                change_summary=str(body.get("changeSummary") or ""),
            )
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/sessions/{session_id}/revisions/{revision_id}/check")
    async def api_check(
        session_id: str,
        revision_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        _idempotency_key(request)
        scope = _scope(user, db)
        try:
            detail = session_detail(db, session_id, scope)
            if detail["revision"]["revisionId"] != revision_id:
                raise HouseDesignerError(
                    "stale_revision", "A tervverzió időközben módosult.", status_code=409
                )
            return run_compliance(
                db,
                session_id=session_id,
                tenant_id=scope.tenant_id,
                actor_subject_id=scope.subject_id,
            )
        except (HouseDesignerError, KeyError, ValueError) as error:
            if isinstance(error, HouseDesignerError):
                _raise_api_error(error)
            raise HTTPException(status_code=422, detail="A megfelelőségi kérés hibás.") from error

    @router.post("/api/v1/house-designer/sessions/{session_id}/estimate")
    async def api_estimate(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        _idempotency_key(request)
        try:
            return create_sandbox_estimate(db, session_id=session_id, actor=_scope(user, db))
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/sessions/{session_id}/renders")
    async def api_render(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        idempotency_key = _idempotency_key(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            return create_sandbox_render(
                db,
                session_id=session_id,
                actor=_scope(user, db),
                prompt=str(body.get("prompt") or ""),
                idempotency_key=idempotency_key,
            )
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/renders/{render_id}/revisions")
    async def api_render_revision(
        render_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            return revise_sandbox_render(
                db,
                render_id=render_id,
                actor=_scope(user, db),
                prompt=str(body.get("prompt") or ""),
                idempotency_key=_idempotency_key(request),
            )
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/sessions/{session_id}/production-jobs/{adapter_type}")
    async def api_production_job(
        session_id: str,
        adapter_type: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            return queue_adapter_job(
                db,
                session_id=session_id,
                adapter_type=adapter_type,
                actor=_scope(user, db),
                idempotency_key=_idempotency_key(request),
                prompt=str(body.get("prompt") or ""),
            )
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/adapter-results")
    async def api_adapter_result(request: Request, db: DatabaseSession):
        content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].lower()
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="Csak application/json engedélyezett.")
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            result = accept_signed_result(
                db,
                payload=body,
                key_id=str(request.headers.get("x-imperial-key-id") or ""),
                signature=str(request.headers.get("x-imperial-signature") or ""),
            )
        except HouseDesignerError as error:
            _raise_api_error(error)
        if result["job"]["status"] == "FAILED":
            raise HTTPException(status_code=422, detail=result)
        return result

    @router.post("/api/v1/house-designer/sessions/{session_id}/approve")
    async def api_approve(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        _idempotency_key(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            return approve_current_design(
                db,
                session_id=session_id,
                actor=_scope(user, db),
                selected_render_id=str(body.get("selectedRenderId") or ""),
                terms_version_id=str(body.get("termsVersionId") or ""),
                notice_version_id=str(body.get("noticeVersionId") or ""),
                terms_accepted=body.get("termsAccepted") is True,
                notice_accepted=body.get("noticeAccepted") is True,
            )
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/sessions/{session_id}/consultations")
    async def api_consultation(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            return book_consultation(
                db,
                session_id=session_id,
                actor=_scope(user, db),
                snapshot_id=str(body.get("snapshotId") or ""),
                slot_id=str(body.get("slotId") or ""),
                customer_name=str(body.get("customerName") or ""),
                customer_email=str(body.get("customerEmail") or ""),
                customer_phone=str(body.get("customerPhone") or ""),
                plot_status=str(body.get("plotStatus") or ""),
                planned_start=str(body.get("plannedStart") or ""),
                notice_version_id=str(body.get("noticeVersionId") or ""),
                notice_accepted=body.get("noticeAccepted") is True,
                idempotency_key=_idempotency_key(request),
            )
        except (HouseDesignerError, TypeError, ValueError) as error:
            if isinstance(error, HouseDesignerError):
                _raise_api_error(error)
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/api/v1/house-designer/sessions/{session_id}/submit")
    @router.post("/api/v1/house-designer/sessions/{session_id}/orders")
    async def api_order(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        _require_json_write(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="A JSON objektum kötelező.")
        try:
            return submit_order_request(
                db,
                session_id=session_id,
                actor=_scope(user, db),
                snapshot_id=str(body.get("snapshotId") or ""),
                notice_version_id=str(body.get("noticeVersionId") or ""),
                notice_accepted=body.get("noticeAccepted") is True,
                idempotency_key=_idempotency_key(request),
            )
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.get("/api/v1/house-designer/submissions/{submission_id}")
    def api_submission_detail(
        submission_id: str,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        try:
            return submission_detail(db, submission_id=submission_id, actor=_scope(user, db))
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.get("/api/v1/house-designer/submissions")
    def api_submission_queue(
        db: DatabaseSession,
        user: SubmissionReviewer,
        status: str | None = None,
        limit: int = 100,
    ):
        return {
            "items": list_submission_queue(db, actor=_scope(user, db), status=status, limit=limit)
        }

    @router.get("/api/v1/house-designer/submissions/{submission_id}/review")
    def api_submission_review_detail(
        submission_id: str,
        db: DatabaseSession,
        user: SubmissionReviewer,
    ):
        try:
            return submission_review_detail(db, submission_id=submission_id, actor=_scope(user, db))
        except HouseDesignerError as error:
            _raise_api_error(error)

    @router.post("/api/v1/house-designer/submissions/{submission_id}/transitions")
    async def api_submission_transition(
        submission_id: str,
        request: Request,
        db: DatabaseSession,
        user: SubmissionReviewer,
    ):
        _require_json_write(request)
        body = await request.json()
        try:
            return transition_submission_review(
                db,
                submission_id=submission_id,
                actor=_scope(user, db),
                actor_role=user.role,
                action=str(body.get("action") or ""),
                note=str(body.get("note") or ""),
                expected_row_version=int(body.get("expectedRowVersion") or 0),
                idempotency_key=_idempotency_key(request),
                booking_id=str(body.get("bookingId") or "") or None,
            )
        except (HouseDesignerError, TypeError, ValueError) as error:
            if isinstance(error, HouseDesignerError):
                _raise_api_error(error)
            raise HTTPException(
                status_code=422, detail="Érvénytelen transition payload."
            ) from error

    @router.get("/house-designer/submissions", response_class=HTMLResponse)
    def submission_queue_page(
        request: Request,
        db: DatabaseSession,
        user: SubmissionReviewer,
    ):
        return templates.TemplateResponse(
            request,
            "house_designer_submissions.html",
            {
                "active": "house-designer",
                "user": user,
                "items": list_submission_queue(
                    db,
                    actor=_scope(user, db),
                    status=request.query_params.get("status"),
                ),
                "csrf_token": _csrf_token(request),
                "error": request.query_params.get("error"),
            },
        )

    @router.get("/house-designer/submissions/{submission_id}/review", response_class=HTMLResponse)
    def submission_review_page(
        submission_id: str,
        request: Request,
        db: DatabaseSession,
        user: SubmissionReviewer,
    ):
        try:
            detail = submission_review_detail(
                db, submission_id=submission_id, actor=_scope(user, db)
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/submissions?error={error.code}", status_code=303
            )
        return templates.TemplateResponse(
            request,
            "house_designer_submission_review.html",
            {
                "active": "house-designer",
                "user": user,
                "submission": detail,
                "csrf_token": _csrf_token(request),
                "error": request.query_params.get("error"),
            },
        )

    @router.post("/house-designer/submissions/{submission_id}/review")
    async def submission_review_action(
        submission_id: str,
        request: Request,
        db: DatabaseSession,
        user: SubmissionReviewer,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            transition_submission_review(
                db,
                submission_id=submission_id,
                actor=_scope(user, db),
                actor_role=user.role,
                action=str(form.get("action") or ""),
                note=str(form.get("note") or ""),
                expected_row_version=int(form.get("row_version") or 0),
                idempotency_key=str(form.get("command_id") or ""),
                booking_id=str(form.get("booking_id") or "") or None,
            )
        except (HouseDesignerError, TypeError, ValueError) as error:
            code = getattr(error, "code", "transition_invalid")
            return RedirectResponse(
                f"/house-designer/submissions/{submission_id}/review?error={code}",
                status_code=303,
            )
        return RedirectResponse(
            f"/house-designer/submissions/{submission_id}/review", status_code=303
        )

    @router.post("/house-designer/submissions/{submission_id}/cancel")
    async def submission_cancel(
        submission_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            detail = transition_submission_review(
                db,
                submission_id=submission_id,
                actor=_scope(user, db),
                actor_role=user.role,
                action="cancel",
                note=str(form.get("note") or ""),
                expected_row_version=int(form.get("row_version") or 0),
                idempotency_key=str(form.get("command_id") or ""),
            )
        except (HouseDesignerError, TypeError, ValueError) as error:
            code = getattr(error, "code", "cancel_invalid")
            return RedirectResponse(f"/house-designer?error={code}", status_code=303)
        return RedirectResponse(f"/house-designer/sessions/{detail['sessionId']}", status_code=303)

    @router.post("/house-designer/sessions")
    async def create(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            detail = create_session(
                db,
                actor=_scope(user, db),
                brand_id="imperial",
                title=str(form.get("title") or "Saját házterv"),
                command_id=str(form.get("command_id") or ""),
                origin=str(form.get("origin") or "blank"),
                template_plan_id=str(form.get("template_plan_id") or "") or None,
                width_mm=int(form.get("width_mm") or 10_000),
                depth_mm=int(form.get("depth_mm") or 8_000),
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer?error={error.code}", status_code=303)
        return RedirectResponse(f"/house-designer/sessions/{detail['sessionId']}", status_code=303)

    @router.get("/house-designer/sessions/{session_id}", response_class=HTMLResponse)
    def detail_page(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: OptionalHouseDesignerUser,
    ):
        actor = _html_scope(request, db, user, session_id)
        try:
            detail = session_detail(db, session_id, actor)
        except HouseDesignerError as error:
            raise HTTPException(error.status_code, str(error)) from error
        audit_site_read(
            db,
            actor=actor,
            session_id=session_id,
            revision_id=detail["revision"]["revisionId"],
            site=detail["revision"]["site"],
            channel="embedded-html" if user is not None else "guest-html",
        )
        approval = approval_panel(db, session_id=session_id, actor=actor)
        if user is None:
            approval["canAct"] = False
        response = templates.TemplateResponse(
            request,
            "house_designer_detail.html",
            {
                "active": "house-designer",
                "user": user or SimpleNamespace(name="Vendég tervező", role="customer", email=""),
                "standalone": user is None,
                "design": detail,
                "estimate": latest_estimate_bundle(
                    db, session_id, detail["revision"]["revisionId"]
                ),
                "compliance": latest_compliance_result(
                    db, session_id=session_id, revision_id=detail["revision"]["revisionId"]
                ),
                "renders": list_current_renders(
                    db,
                    session_id=session_id,
                    revision_id=detail["revision"]["revisionId"],
                    actor=actor,
                ),
                "approval": approval,
                "production_jobs": (
                    list_session_jobs(db, session_id=session_id, actor=actor) if user else []
                ),
                "production_adapters_enabled": bool(
                    user and settings.house_designer_adapters_enabled
                ),
                "csrf_token": _csrf_token(request),
                "offline_scope_key": _offline_scope_key(actor, session_id),
                "error": request.query_params.get("error"),
                "check_outcome": request.query_params.get("check"),
            },
        )
        response.headers["ETag"] = _design_etag(detail)
        response.headers["Cache-Control"] = "private, no-cache"
        return response

    @router.post("/house-designer/sessions/{session_id}/commands")
    async def command(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: OptionalHouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        command_type = str(form.get("command_type") or "")
        try:
            apply_session_command(
                db,
                session_id=session_id,
                actor=_html_scope(request, db, user, session_id),
                base_revision_id=str(form.get("base_revision_id") or ""),
                base_canonical_sha256=str(form.get("base_canonical_sha256") or ""),
                command_id=str(form.get("command_id") or ""),
                command_type=command_type,
                payload=_payload(form, command_type),
                change_summary=str(form.get("change_summary") or ""),
            )
        except (HouseDesignerError, ValueError) as error:
            code = getattr(error, "code", "invalid_input")
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={code}",
                status_code=303,
            )
        return RedirectResponse(f"/house-designer/sessions/{session_id}", status_code=303)

    @router.post("/house-designer/sessions/{session_id}/estimate")
    async def estimate(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: OptionalHouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_sandbox_estimate(
                db,
                session_id=session_id,
                actor=_html_scope(request, db, user, session_id),
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={error.code}", status_code=303
            )
        return RedirectResponse(f"/house-designer/sessions/{session_id}#estimate", status_code=303)

    @router.post("/house-designer/sessions/{session_id}/renders")
    async def render(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: OptionalHouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_sandbox_render(
                db,
                session_id=session_id,
                actor=_html_scope(request, db, user, session_id),
                prompt=str(form.get("prompt") or ""),
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={error.code}", status_code=303
            )
        return RedirectResponse(f"/house-designer/sessions/{session_id}#renders", status_code=303)

    @router.post("/house-designer/sessions/{session_id}/production-jobs")
    async def production_job(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            queue_adapter_job(
                db,
                session_id=session_id,
                adapter_type=str(form.get("adapter_type") or ""),
                actor=_scope(user, db),
                idempotency_key=str(form.get("command_id") or ""),
                prompt=str(form.get("prompt") or ""),
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={error.code}#production-adapters",
                status_code=303,
            )
        return RedirectResponse(
            f"/house-designer/sessions/{session_id}#production-adapters", status_code=303
        )

    @router.get("/house-designer/renders/{render_id}.svg")
    def render_asset(
        render_id: str,
        request: Request,
        db: DatabaseSession,
        user: OptionalHouseDesignerUser,
    ):
        try:
            svg = sandbox_render_svg(db, render_id=render_id, actor=_html_scope(request, db, user))
        except HouseDesignerError as error:
            raise HTTPException(error.status_code, str(error)) from error
        return Response(
            svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.post("/house-designer/sessions/{session_id}/check")
    async def check(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: OptionalHouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        scope = _html_scope(request, db, user, session_id)
        try:
            session_detail(db, session_id, scope)
            result = run_compliance(
                db,
                session_id=session_id,
                tenant_id=scope.tenant_id,
                actor_subject_id=scope.subject_id,
            )
        except (HouseDesignerError, KeyError, ValueError) as error:
            code = getattr(error, "code", "compliance_failed")
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={code}", status_code=303
            )
        return RedirectResponse(
            f"/house-designer/sessions/{session_id}?check={result['outcome']}",
            status_code=303,
        )

    @router.post("/house-designer/sessions/{session_id}/approve")
    async def approve(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            approve_current_design(
                db,
                session_id=session_id,
                actor=_scope(user, db),
                selected_render_id=str(form.get("selected_render_id") or ""),
                terms_version_id=str(form.get("terms_version_id") or ""),
                notice_version_id=str(form.get("notice_version_id") or ""),
                terms_accepted=form.get("terms_accepted") == "yes",
                notice_accepted=form.get("notice_accepted") == "yes",
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={error.code}#approval",
                status_code=303,
            )
        return RedirectResponse(
            f"/house-designer/sessions/{session_id}?approved=1#approval", status_code=303
        )

    @router.post("/house-designer/sessions/{session_id}/consultations")
    async def consultation(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            book_consultation(
                db,
                session_id=session_id,
                actor=_scope(user, db),
                snapshot_id=str(form.get("snapshot_id") or ""),
                slot_id=str(form.get("slot_id") or ""),
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or ""),
                customer_phone=str(form.get("customer_phone") or ""),
                plot_status=str(form.get("plot_status") or ""),
                planned_start=str(form.get("planned_start") or ""),
                notice_version_id=str(form.get("notice_version_id") or ""),
                notice_accepted=form.get("notice_accepted") == "yes",
                idempotency_key=str(form.get("command_id") or ""),
            )
        except (HouseDesignerError, TypeError, ValueError) as error:
            code = getattr(error, "code", "consultation_input_invalid")
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={code}#consultation",
                status_code=303,
            )
        return RedirectResponse(
            f"/house-designer/sessions/{session_id}?consultation=booked#consultation",
            status_code=303,
        )

    @router.post("/house-designer/sessions/{session_id}/orders")
    async def order(
        session_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            submit_order_request(
                db,
                session_id=session_id,
                actor=_scope(user, db),
                snapshot_id=str(form.get("snapshot_id") or ""),
                notice_version_id=str(form.get("notice_version_id") or ""),
                notice_accepted=form.get("notice_accepted") == "yes",
                idempotency_key=str(form.get("command_id") or ""),
            )
        except HouseDesignerError as error:
            return RedirectResponse(
                f"/house-designer/sessions/{session_id}?error={error.code}#order",
                status_code=303,
            )
        return RedirectResponse(
            f"/house-designer/sessions/{session_id}?order=received#order", status_code=303
        )

    @router.get("/house-designer/adapters", response_class=HTMLResponse)
    def adapters_page(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        if user.role not in {"designer", "technical-prep", "managing-director", "owner"}:
            raise HTTPException(status_code=403, detail="Nincs adapter-adminisztrációs joga.")
        return templates.TemplateResponse(
            request,
            "house_designer_adapters.html",
            {
                "active": "house-designer",
                "user": user,
                "adapters": list_adapters(db, tenant_id="imperial-holding", brand_id="imperial"),
                "readiness": house_designer_release_readiness(
                    db, tenant_id="imperial-holding", brand_id="imperial"
                ),
                "adapters_enabled": settings.house_designer_adapters_enabled,
                "csrf_token": _csrf_token(request),
                "error": request.query_params.get("error"),
            },
        )

    @router.post("/house-designer/adapters")
    async def create_adapter(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            register_adapter(
                db,
                actor_subject_id=_scope(user, db).subject_id,
                actor_role=user.role,
                tenant_id="imperial-holding",
                brand_id="imperial",
                adapter_type=str(form.get("adapter_type") or ""),
                provider=str(form.get("provider") or ""),
                endpoint=str(form.get("endpoint") or ""),
                key_id=str(form.get("key_id") or ""),
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer/adapters?error={error.code}", 303)
        return RedirectResponse("/house-designer/adapters", 303)

    @router.post("/house-designer/adapters/{adapter_id}/review")
    async def adapter_review(
        adapter_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            review_adapter(
                db,
                adapter_id=adapter_id,
                actor_subject_id=_scope(user, db).subject_id,
                actor_role=user.role,
                approve=str(form.get("decision") or "") == "approve",
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer/adapters?error={error.code}", 303)
        return RedirectResponse("/house-designer/adapters", 303)

    @router.post("/house-designer/adapters/{adapter_id}/suspend")
    async def adapter_suspend(
        adapter_id: str,
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            suspend_adapter(
                db,
                adapter_id=adapter_id,
                actor_subject_id=_scope(user, db).subject_id,
                actor_role=user.role,
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer/adapters?error={error.code}", 303)
        return RedirectResponse("/house-designer/adapters", 303)

    @router.post("/house-designer/entitlement/request")
    async def entitlement_request(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            request_entitlement_activation(
                db,
                tenant_id="imperial-holding",
                brand_id="imperial",
                actor_subject_id=_scope(user, db).subject_id,
                actor_role=user.role,
                expected_row_version=_optional_row_version(form),
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer/adapters?error={error.code}", 303)
        return RedirectResponse("/house-designer/adapters", 303)

    @router.post("/house-designer/entitlement/sandbox")
    async def entitlement_sandbox(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            action = str(form.get("action") or "")
            if action not in {"enable", "disable"}:
                raise HouseDesignerError(
                    "invalid_sandbox_action",
                    "Ismeretlen sandbox művelet.",
                    status_code=422,
                )
            set_sandbox_entitlement(
                db,
                tenant_id="imperial-holding",
                brand_id="imperial",
                actor_subject_id=_scope(user, db).subject_id,
                actor_role=user.role,
                enabled=action == "enable",
                expected_row_version=_optional_row_version(form),
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer/adapters?error={error.code}", 303)
        return RedirectResponse("/house-designer/adapters", 303)

    @router.post("/house-designer/entitlement/review")
    async def entitlement_review(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            review_entitlement_activation(
                db,
                tenant_id="imperial-holding",
                brand_id="imperial",
                actor_subject_id=_scope(user, db).subject_id,
                actor_role=user.role,
                approve=str(form.get("decision") or "") == "approve",
                expected_row_version=_required_row_version(form),
                expected_readiness_sha256=str(form.get("readiness_sha256") or ""),
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer/adapters?error={error.code}", 303)
        return RedirectResponse("/house-designer/adapters", 303)

    @router.post("/house-designer/entitlement/suspend")
    async def entitlement_suspend(
        request: Request,
        db: DatabaseSession,
        user: HouseDesignerUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            suspend_entitlement(
                db,
                tenant_id="imperial-holding",
                brand_id="imperial",
                actor_subject_id=_scope(user, db).subject_id,
                actor_role=user.role,
                expected_row_version=_required_row_version(form),
            )
        except HouseDesignerError as error:
            return RedirectResponse(f"/house-designer/adapters?error={error.code}", 303)
        return RedirectResponse("/house-designer/adapters", 303)

    return router
