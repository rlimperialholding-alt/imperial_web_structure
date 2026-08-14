from __future__ import annotations

import hmac
import json
import secrets
from datetime import UTC, date, datetime, time
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import require_role
from app.services.regulatory_admin import (
    RegulatoryActor,
    RegulatoryAdminError,
    approve_source,
    create_interpretation,
    create_ruleset,
    create_source,
    regulatory_dashboard,
    revoke_source,
    transition_interpretation,
    transition_ruleset,
    verify_design_site,
)

REGULATORY_ROLES = (
    "technical-prep",
    "designer",
    "legal",
    "managing-director",
    "owner",
    "platform-admin",
)
DatabaseSession = Annotated[Session, Depends(get_db)]
RegulatoryUser = Annotated[User, Depends(require_role(*REGULATORY_ROLES))]


def _csrf_token(request: Request) -> str:
    token = str(request.session.get("regulatory_admin_csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["regulatory_admin_csrf"] = token
    return token


def _require_csrf(request: Request, form: Any) -> None:
    expected = str(request.session.get("regulatory_admin_csrf") or "")
    supplied = str(form.get("csrf_token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Érvénytelen munkamenet-védelmi token.")
    origin = str(request.headers.get("origin") or "")
    if origin and not origin.rstrip("/").endswith(f"//{request.url.netloc}"):
        raise HTTPException(status_code=403, detail="Eltérő Origin fejléc.")


def _actor(user: User) -> RegulatoryActor:
    subject = str(user.itep_subject_id or user.email)
    return RegulatoryActor(
        subject_id=subject,
        can_author=user.role in {"technical-prep", "designer", "legal"},
        can_review=user.role in {"legal", "managing-director", "owner"},
    )


def _day(value: Any, *, optional: bool = False) -> datetime | None:
    raw = str(value or "").strip()
    if not raw and optional:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as error:
        raise RegulatoryAdminError("date_invalid", "A hatály dátuma hibás.") from error
    return datetime.combine(parsed, time.min, tzinfo=ZoneInfo("Europe/Budapest")).astimezone(UTC)


def _redirect(error: RegulatoryAdminError) -> RedirectResponse:
    return RedirectResponse(f"/house-designer/regulatory-admin?error={error.code}", status_code=303)


def build_regulatory_admin_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/house-designer/regulatory-admin", response_class=HTMLResponse)
    def workspace(request: Request, db: DatabaseSession, user: RegulatoryUser):
        return templates.TemplateResponse(
            request,
            "regulatory_admin.html",
            {
                "active": "house-designer",
                "user": user,
                "reg": regulatory_dashboard(db, actor_subject_id=_actor(user).subject_id),
                "csrf_token": _csrf_token(request),
                "actor": _actor(user),
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
            },
        )

    @router.post("/house-designer/regulatory-admin/sources")
    async def source_create(request: Request, db: DatabaseSession, user: RegulatoryUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_source(
                db,
                actor=_actor(user),
                source_key=str(form.get("source_key") or ""),
                source_type=str(form.get("source_type") or "HESZ"),
                issuer=str(form.get("issuer") or ""),
                scope_key=str(form.get("scope_key") or ""),
                source_url=str(form.get("source_url") or ""),
                effective_from=_day(form.get("effective_from")),
                effective_to=_day(form.get("effective_to"), optional=True),
                content_sha256=str(form.get("content_sha256") or ""),
                normalized_text_sha256=str(form.get("normalized_text_sha256") or ""),
                storage_ref=str(form.get("storage_ref") or ""),
            )
        except (RegulatoryAdminError, TypeError, ValueError) as error:
            if isinstance(error, RegulatoryAdminError):
                return _redirect(error)
            return _redirect(RegulatoryAdminError("source_input_invalid", "Hibás forrásadat."))
        return RedirectResponse(
            "/house-designer/regulatory-admin?ok=source_created#sources", status_code=303
        )

    @router.post("/house-designer/regulatory-admin/sources/{source_id}/approve")
    async def source_approve(
        source_id: str, request: Request, db: DatabaseSession, user: RegulatoryUser
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            approve_source(
                db,
                actor=_actor(user),
                source_snapshot_id=source_id,
                row_version=int(form.get("row_version") or 0),
            )
        except RegulatoryAdminError as error:
            return _redirect(error)
        return RedirectResponse(
            "/house-designer/regulatory-admin?ok=source_approved#sources", status_code=303
        )

    @router.post("/house-designer/regulatory-admin/sources/{source_id}/revoke")
    async def source_revoke(
        source_id: str, request: Request, db: DatabaseSession, user: RegulatoryUser
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            revoke_source(
                db,
                actor=_actor(user),
                source_snapshot_id=source_id,
                row_version=int(form.get("row_version") or 0),
            )
        except RegulatoryAdminError as error:
            return _redirect(error)
        return RedirectResponse(
            "/house-designer/regulatory-admin?ok=source_revoked#sources", status_code=303
        )

    @router.post("/house-designer/regulatory-admin/interpretations")
    async def interpretation_create(request: Request, db: DatabaseSession, user: RegulatoryUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            roofs = [item for item in str(form.get("allowed_roof_types") or "").split(",") if item]
            vectors = json.loads(str(form.get("test_vectors_json") or "[]"))
            if not isinstance(vectors, list):
                raise RegulatoryAdminError("test_vector_invalid", "A tesztvektor lista legyen.")
            create_interpretation(
                db,
                actor=_actor(user),
                source_snapshot_id=str(form.get("source_snapshot_id") or ""),
                source_span=str(form.get("source_span") or ""),
                rules={
                    "maxStoreys": form.get("max_storeys"),
                    "maxGrossAreaM2": form.get("max_gross_area_m2"),
                    "allowedRoofTypes": roofs,
                },
                test_vectors=vectors,
            )
        except (RegulatoryAdminError, json.JSONDecodeError, TypeError, ValueError) as error:
            if isinstance(error, RegulatoryAdminError):
                return _redirect(error)
            return _redirect(
                RegulatoryAdminError("interpretation_input_invalid", "Hibás értelmezés.")
            )
        return RedirectResponse(
            "/house-designer/regulatory-admin?ok=interpretation_created#interpretations",
            status_code=303,
        )

    @router.post("/house-designer/regulatory-admin/interpretations/{interpretation_id}/{action}")
    async def interpretation_transition(
        interpretation_id: str,
        action: str,
        request: Request,
        db: DatabaseSession,
        user: RegulatoryUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            transition_interpretation(
                db,
                actor=_actor(user),
                interpretation_id=interpretation_id,
                row_version=int(form.get("row_version") or 0),
                action=action,
            )
        except RegulatoryAdminError as error:
            return _redirect(error)
        return RedirectResponse(
            f"/house-designer/regulatory-admin?ok=interpretation_{action}#interpretations",
            status_code=303,
        )

    @router.post("/house-designer/regulatory-admin/rulesets")
    async def ruleset_create(request: Request, db: DatabaseSession, user: RegulatoryUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_ruleset(
                db,
                actor=_actor(user),
                scope_key=str(form.get("scope_key") or ""),
                national_basis=str(form.get("national_basis") or "TÉKA"),
                local_plan_basis=str(form.get("local_plan_basis") or ""),
                effective_from=_day(form.get("effective_from")),
                effective_to=_day(form.get("effective_to"), optional=True),
                interpretation_ids=[str(item) for item in form.getlist("interpretation_ids")],
            )
        except (RegulatoryAdminError, TypeError, ValueError) as error:
            if isinstance(error, RegulatoryAdminError):
                return _redirect(error)
            return _redirect(RegulatoryAdminError("ruleset_input_invalid", "Hibás szabálykészlet."))
        return RedirectResponse(
            "/house-designer/regulatory-admin?ok=ruleset_created#rulesets", status_code=303
        )

    @router.post("/house-designer/regulatory-admin/rulesets/{ruleset_id}/{action}")
    async def ruleset_transition(
        ruleset_id: str,
        action: str,
        request: Request,
        db: DatabaseSession,
        user: RegulatoryUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            transition_ruleset(
                db,
                actor=_actor(user),
                ruleset_id=ruleset_id,
                row_version=int(form.get("row_version") or 0),
                action=action,
            )
        except RegulatoryAdminError as error:
            return _redirect(error)
        return RedirectResponse(
            f"/house-designer/regulatory-admin?ok=ruleset_{action}#rulesets", status_code=303
        )

    @router.post("/house-designer/regulatory-admin/site-verifications")
    async def site_verify(request: Request, db: DatabaseSession, user: RegulatoryUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            verify_design_site(
                db,
                actor=_actor(user),
                tenant_id="imperial-holding",
                session_id=str(form.get("session_id") or ""),
                proof_ref=str(form.get("proof_ref") or ""),
                proof_sha256=str(form.get("proof_sha256") or ""),
                verification_method=str(form.get("verification_method") or ""),
                command_id=str(form.get("command_id") or ""),
            )
        except RegulatoryAdminError as error:
            return _redirect(error)
        return RedirectResponse(
            "/house-designer/regulatory-admin?ok=site_verified#site-verifications",
            status_code=303,
        )

    return router
