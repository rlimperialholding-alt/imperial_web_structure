from __future__ import annotations

import hmac
import json
import secrets
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.datastructures import FormData, UploadFile

from app.config import settings
from app.database import get_db
from app.market_service_auth import (
    MarketServicePrincipal,
    authenticate_market_service,
)
from app.market_service_auth import (
    bearer as market_service_bearer,
)
from app.models import User
from app.security import require_internal_job_token, require_role
from app.services.market_intelligence import (
    MarketActor,
    MarketIntelligenceError,
    authorize_market_intelligence,
    cancel_capture_job,
    compare_packs,
    compare_pattern_clusters,
    create_asset,
    create_hypothesis,
    create_observation,
    create_pack,
    create_pattern_cluster,
    create_target,
    create_validation,
    create_voc_signal,
    dashboard,
    erase_snapshot_content,
    handoff_pack,
    import_manual_snapshot,
    ingest_market_permission_replica,
    quarantine_snapshot,
    queue_public_capture,
    retry_capture_job,
    revise_pack,
    revise_pattern_cluster,
    revise_target,
    service_resource_list,
    transition_pack,
    transition_target,
    transition_validation,
)

MCI_ROLES = ("marketing", "owner", "managing-director", "platform-admin")
DatabaseSession = Annotated[Session, Depends(get_db)]
MarketUser = Annotated[User, Depends(require_role(*MCI_ROLES))]


def _csrf_token(request: Request) -> str:
    token = str(request.session.get("market_intelligence_csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["market_intelligence_csrf"] = token
    return token


def _require_csrf(request: Request, form: Any) -> None:
    expected = str(request.session.get("market_intelligence_csrf") or "")
    supplied = str(form.get("csrf_token") or request.headers.get("x-csrf-token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Érvénytelen munkamenet-védelmi token.")
    origin = str(request.headers.get("origin") or "")
    if origin:
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or parsed_origin.netloc.lower() != request.url.netloc.lower()
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            raise HTTPException(status_code=403, detail="Eltérő Origin fejléc.")


def _actor(db: Session, user: User) -> MarketActor:
    scope = {"tenant_id": "imperial-holding", "brand_id": "imperial", "market_id": "HU"}
    try:
        subject, revision = authorize_market_intelligence(db, user, "ii.market.read", **scope)
    except PermissionError as error:
        raise HTTPException(
            status_code=403,
            detail={"code": "itep_permission_denied", "message": str(error)},
        ) from error

    def allowed(permission: str) -> bool:
        try:
            authorize_market_intelligence(db, user, permission, **scope)
            return True
        except PermissionError:
            return False

    return MarketActor(
        subject_id=subject,
        **scope,
        can_author=allowed("ii.market.author"),
        can_review=allowed("ii.market.review"),
        can_freeze=allowed("ii.market.freeze"),
        can_handoff=allowed("ii.market.handoff"),
        can_quarantine=allowed("ii.market.quarantine"),
        permission_revision=revision,
    )


def _error_redirect(error: MarketIntelligenceError) -> RedirectResponse:
    return RedirectResponse(f"/market-intelligence?error={error.code}", status_code=303)


async def _api_payload(request: Request) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].lower()
    if content_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail={"code": "json_content_type_required", "message": "application/json kötelező."},
        )
    length = str(request.headers.get("content-length") or "0")
    if length.isdigit() and int(length) > 400_000:
        raise HTTPException(
            status_code=413,
            detail={"code": "request_too_large", "message": "A kérés túl nagy."},
        )
    _require_csrf(request, {})
    try:
        payload = json.loads(await request.body())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "json_invalid", "message": "Hibás JSON törzs."},
        ) from error
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "json_object_required", "message": "JSON objektum kötelező."},
        )
    return payload


async def _service_payload(request: Request) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].lower()
    if content_type != "application/json":
        raise HTTPException(415, detail={"code": "json_content_type_required"})
    length = str(request.headers.get("content-length") or "0")
    if length.isdigit() and int(length) > 400_000:
        raise HTTPException(413, detail={"code": "request_too_large"})
    try:
        payload = json.loads(await request.body())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(400, detail={"code": "json_invalid"}) from error
    if not isinstance(payload, dict):
        raise HTTPException(422, detail={"code": "json_object_required"})
    return payload


def _market_service_dependency(permission: str):
    def dependency(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Security(market_service_bearer)
        ],
    ) -> MarketServicePrincipal:
        return authenticate_market_service(credentials, permission)

    return dependency


MarketServiceRead = Annotated[MarketServicePrincipal, Depends(_market_service_dependency("read"))]
MarketServiceHandoff = Annotated[
    MarketServicePrincipal, Depends(_market_service_dependency("handoff"))
]


def _service_scope(principal: MarketServicePrincipal) -> dict[str, str]:
    return {
        "tenantId": principal.tenant_id,
        "brandId": principal.brand_id,
        "marketId": principal.market_id,
    }


def _if_match_int(request: Request) -> int:
    raw = str(request.headers.get("if-match") or "").strip().removeprefix("W/").strip('"')
    if not raw:
        raise HTTPException(
            status_code=428,
            detail={"code": "if_match_required", "message": "If-Match fejléc kötelező."},
        )
    try:
        return int(raw)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "if_match_invalid", "message": "Az If-Match értéke hibás."},
        ) from error


def _if_match_hash(request: Request) -> str:
    raw = str(request.headers.get("if-match") or "").strip().removeprefix("W/").strip('"')
    if len(raw) != 64 or any(character not in "0123456789abcdefABCDEF" for character in raw):
        raise HTTPException(
            status_code=428 if not raw else 400,
            detail={"code": "if_match_required" if not raw else "if_match_invalid"},
        )
    return raw.lower()


def _idempotency_key(request: Request) -> str:
    key = str(request.headers.get("idempotency-key") or "").strip()
    if not 8 <= len(key) <= 255:
        raise HTTPException(
            status_code=428 if not key else 400,
            detail={"code": "idempotency_key_required" if not key else "idempotency_key_invalid"},
        )
    return key


def _api_call(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except MarketIntelligenceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error


def _integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        raise HTTPException(status_code=422, detail={"code": "integer_required", "field": key})
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail={"code": "integer_required", "field": key}
        ) from error


def _integer_default(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail={"code": "integer_required", "field": key}
        ) from error


def _form_integer(form: Any, key: str, default: int) -> int:
    try:
        return int(form.get(key) or default)
    except (TypeError, ValueError) as error:
        raise MarketIntelligenceError("invalid_number", "Hibás számérték.") from error


def _form_scalar(form: FormData, key: str) -> str | None:
    value = form.get(key)
    if isinstance(value, UploadFile):
        # Fail-closed: fájlfeltöltés skalár mezőre nem értelmezhető; a kezelő
        # réteg ValueError-ként 400-as hibairányítással fogadja (nem 500).
        raise ValueError("scalar form field expected, received a file upload")
    return value


def _optional_integer(payload: dict[str, Any], key: str) -> int | None:
    if key not in payload or payload.get(key) in {None, ""}:
        return None
    return _integer(payload, key)


def _form_optional_integer(form: Any, key: str) -> int | None:
    value = form.get(key)
    if value in {None, ""}:
        return None
    return _form_integer(form, key, 0)


def _optional_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail={"code": "number_required", "field": key}
        ) from error


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(status_code=422, detail={"code": "string_list_required", "field": key})
    return value


def _json_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail={"code": "json_object_required", "field": key})
    return value


def build_market_intelligence_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/internal/market-intelligence/permission-replica",
        dependencies=[Depends(require_internal_job_token)],
    )
    async def market_permission_replica(request: Request, db: DatabaseSession):
        if not settings.internal_job_token or not settings.itep_identity_shared_secret:
            raise HTTPException(
                status_code=503, detail="ITEP permission replica nincs konfigurálva."
            )
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("A replica gyökere JSON objektum.")
            inserted = ingest_market_permission_replica(
                db,
                payload=payload,
                signature=str(request.headers.get("x-itep-signature") or ""),
                secret=settings.itep_identity_shared_secret,
            )
            return {"accepted": True, "inserted": inserted, "revision": payload["revision"]}
        except PermissionError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/market-intelligence", response_class=HTMLResponse)
    def workspace(
        request: Request,
        db: DatabaseSession,
        user: MarketUser,
    ):
        actor = _actor(db, user)
        cluster_compare = None
        pack_compare = None
        compare_error = None
        try:
            if request.query_params.get("cluster_left") and request.query_params.get(
                "cluster_right"
            ):
                cluster_compare = compare_pattern_clusters(
                    db,
                    actor=actor,
                    left_id=str(request.query_params["cluster_left"]),
                    right_id=str(request.query_params["cluster_right"]),
                )
            if request.query_params.get("pack_left") and request.query_params.get("pack_right"):
                pack_compare = compare_packs(
                    db,
                    actor=actor,
                    left_id=str(request.query_params["pack_left"]),
                    right_id=str(request.query_params["pack_right"]),
                )
        except MarketIntelligenceError as error:
            compare_error = error.code
        return templates.TemplateResponse(
            request,
            "market_intelligence.html",
            {
                "active": "market-intelligence",
                "user": user,
                "mci": dashboard(
                    db,
                    actor,
                    public_fetch_enabled=settings.market_public_fetch_enabled,
                ),
                "csrf_token": _csrf_token(request),
                "error": request.query_params.get("error"),
                "ok": request.query_params.get("ok"),
                "cluster_compare": cluster_compare,
                "pack_compare": pack_compare,
                "compare_error": compare_error,
            },
        )

    @router.post("/market-intelligence/targets")
    async def new_target(
        request: Request,
        db: DatabaseSession,
        user: MarketUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_target(
                db,
                actor=_actor(db, user),
                name=str(form.get("name") or ""),
                source_type=str(form.get("source_type") or "public_web"),
                origin=str(form.get("origin") or ""),
                allowed_path=str(form.get("allowed_path") or "/"),
                rights_status=str(form.get("rights_status") or ""),
                capture_mode=str(form.get("capture_mode") or "manual"),
                rate_limit_max=_form_integer(form, "rate_limit_max", 10),
                rate_limit_window_seconds=_form_integer(form, "rate_limit_window_seconds", 3600),
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse("/market-intelligence?ok=target_created#targets", status_code=303)

    @router.post("/market-intelligence/targets/{target_id}/{action}")
    async def target_transition(
        target_id: str,
        action: str,
        request: Request,
        db: DatabaseSession,
        user: MarketUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            if action == "revise":
                revise_target(
                    db,
                    actor=_actor(db, user),
                    target_id=target_id,
                    row_version=int(_form_scalar(form, "row_version") or 0),
                    name=str(form.get("name") or ""),
                    origin=str(form.get("origin") or ""),
                    allowed_path=str(form.get("allowed_path") or "/"),
                    rights_status=str(form.get("rights_status") or ""),
                    rate_limit_max=_form_optional_integer(form, "rate_limit_max"),
                    rate_limit_window_seconds=_form_optional_integer(
                        form, "rate_limit_window_seconds"
                    ),
                )
            else:
                transition_target(
                    db,
                    actor=_actor(db, user),
                    target_id=target_id,
                    row_version=int(_form_scalar(form, "row_version") or 0),
                    action=action,
                    reason=str(form.get("reason") or ""),
                )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        except ValueError:
            return _error_redirect(
                MarketIntelligenceError("invalid_number", "Hibás számérték.")
            )
        return RedirectResponse(f"/market-intelligence?ok=target_{action}#targets", status_code=303)

    @router.post("/market-intelligence/snapshots")
    async def manual_snapshot(
        request: Request,
        db: DatabaseSession,
        user: MarketUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            import_manual_snapshot(
                db,
                actor=_actor(db, user),
                target_id=str(form.get("target_id") or ""),
                resolved_url=str(form.get("resolved_url") or ""),
                mime_type=str(form.get("mime_type") or "text/plain"),
                content=str(form.get("content") or ""),
                idempotency_key=str(form.get("idempotency_key") or ""),
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse(
            "/market-intelligence?ok=snapshot_imported#evidence", status_code=303
        )

    @router.post("/market-intelligence/snapshots/{snapshot_id}/quarantine")
    async def snapshot_quarantine(
        snapshot_id: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            quarantine_snapshot(
                db,
                actor=_actor(db, user),
                snapshot_id=snapshot_id,
                legal_basis=str(form.get("legal_basis") or ""),
                reason=str(form.get("reason") or ""),
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse(
            "/market-intelligence?ok=snapshot_quarantined#capture", status_code=303
        )

    @router.post("/market-intelligence/snapshots/{snapshot_id}/erase")
    async def snapshot_erase(
        snapshot_id: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            erase_snapshot_content(
                db,
                actor=_actor(db, user),
                snapshot_id=snapshot_id,
                legal_basis=str(form.get("legal_basis") or ""),
                reason=str(form.get("reason") or ""),
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse("/market-intelligence?ok=snapshot_erased#capture", status_code=303)

    @router.post("/market-intelligence/capture-jobs")
    async def capture_job_queue(request: Request, db: DatabaseSession, user: MarketUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            queue_public_capture(
                db,
                actor=_actor(db, user),
                target_id=str(form.get("target_id") or ""),
                resolved_url=str(form.get("resolved_url") or ""),
                idempotency_key=str(form.get("idempotency_key") or ""),
                connector_enabled=settings.market_public_fetch_enabled,
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse("/market-intelligence?ok=capture_queued#capture", status_code=303)

    @router.post("/market-intelligence/capture-jobs/{job_id}/{action}")
    async def capture_job_action(
        job_id: str, action: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            if action == "cancel":
                cancel_capture_job(
                    db,
                    actor=_actor(db, user),
                    job_id=job_id,
                    reason=str(form.get("reason") or ""),
                )
            elif action == "retry":
                retry_capture_job(
                    db,
                    actor=_actor(db, user),
                    job_id=job_id,
                    idempotency_key=str(form.get("idempotency_key") or ""),
                    connector_enabled=settings.market_public_fetch_enabled,
                )
            else:
                raise MarketIntelligenceError("capture_action_invalid", "Ismeretlen job művelet.")
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse(
            f"/market-intelligence?ok=capture_{action}#capture", status_code=303
        )

    @router.post("/market-intelligence/observations")
    async def observation(
        request: Request,
        db: DatabaseSession,
        user: MarketUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            confidence_raw = str(form.get("confidence") or "").strip()
            create_observation(
                db,
                actor=_actor(db, user),
                snapshot_id=str(form.get("snapshot_id") or ""),
                statement=str(form.get("statement") or ""),
                start_offset=int(_form_scalar(form, "start_offset") or 0),
                end_offset=int(_form_scalar(form, "end_offset") or 0),
                evidence_level=str(form.get("evidence_level") or "OBSERVED"),
                method=str(form.get("method") or ""),
                confidence=float(confidence_raw) if confidence_raw else None,
            )
        except (MarketIntelligenceError, ValueError) as error:
            if isinstance(error, MarketIntelligenceError):
                return _error_redirect(error)
            return _error_redirect(MarketIntelligenceError("invalid_number", "Hibás számérték."))
        return RedirectResponse(
            "/market-intelligence?ok=observation_created#evidence", status_code=303
        )

    @router.post("/market-intelligence/assets")
    async def asset(request: Request, db: DatabaseSession, user: MarketUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_asset(
                db,
                actor=_actor(db, user),
                snapshot_id=str(form.get("snapshot_id") or ""),
                channel=str(form.get("channel") or ""),
                asset_type=str(form.get("asset_type") or ""),
                title=str(form.get("title") or ""),
                start_offset=int(_form_scalar(form, "start_offset") or 0),
                end_offset=int(_form_scalar(form, "end_offset") or 0),
                claims=[item.strip() for item in str(form.get("claims") or "").splitlines()],
            )
        except (MarketIntelligenceError, ValueError) as error:
            return _error_redirect(
                error
                if isinstance(error, MarketIntelligenceError)
                else MarketIntelligenceError("invalid_number", "Hibás számérték.")
            )
        return RedirectResponse(
            "/market-intelligence?ok=asset_created#evidence-objects", status_code=303
        )

    @router.post("/market-intelligence/voc-signals")
    async def voc_signal(request: Request, db: DatabaseSession, user: MarketUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_voc_signal(
                db,
                actor=_actor(db, user),
                snapshot_id=str(form.get("snapshot_id") or ""),
                masked_quote=str(form.get("masked_quote") or ""),
                theme=str(form.get("theme") or ""),
                sentiment=str(form.get("sentiment") or ""),
                start_offset=int(_form_scalar(form, "start_offset") or 0),
                end_offset=int(_form_scalar(form, "end_offset") or 0),
            )
        except (MarketIntelligenceError, ValueError) as error:
            return _error_redirect(
                error
                if isinstance(error, MarketIntelligenceError)
                else MarketIntelligenceError("invalid_number", "Hibás számérték.")
            )
        return RedirectResponse(
            "/market-intelligence?ok=voc_created#evidence-objects", status_code=303
        )

    @router.post("/market-intelligence/clusters")
    async def cluster(request: Request, db: DatabaseSession, user: MarketUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            raw_confidence = str(form.get("confidence") or "").strip()
            create_pattern_cluster(
                db,
                actor=_actor(db, user),
                title=str(form.get("title") or ""),
                summary=str(form.get("summary") or ""),
                member_ids=[str(item) for item in form.getlist("member_ids")],
                confidence=float(raw_confidence) if raw_confidence else None,
            )
        except (MarketIntelligenceError, ValueError) as error:
            return _error_redirect(
                error
                if isinstance(error, MarketIntelligenceError)
                else MarketIntelligenceError("invalid_number", "Hibás számérték.")
            )
        return RedirectResponse("/market-intelligence?ok=cluster_created#analysis", status_code=303)

    @router.post("/market-intelligence/clusters/{cluster_id}/revise")
    async def cluster_revise(
        cluster_id: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            raw_confidence = str(form.get("confidence") or "").strip()
            revise_pattern_cluster(
                db,
                actor=_actor(db, user),
                cluster_id=cluster_id,
                title=str(form.get("title") or ""),
                summary=str(form.get("summary") or ""),
                member_ids=[str(item) for item in form.getlist("member_ids")],
                confidence=float(raw_confidence) if raw_confidence else None,
            )
        except (MarketIntelligenceError, ValueError) as error:
            return _error_redirect(
                error
                if isinstance(error, MarketIntelligenceError)
                else MarketIntelligenceError("invalid_number", "Hibás számérték.")
            )
        return RedirectResponse("/market-intelligence?ok=cluster_revised#analysis", status_code=303)

    @router.post("/market-intelligence/hypotheses")
    async def hypothesis(request: Request, db: DatabaseSession, user: MarketUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_hypothesis(
                db,
                actor=_actor(db, user),
                statement=str(form.get("statement") or ""),
                audience=str(form.get("audience") or ""),
                supporting_ids=[str(item) for item in form.getlist("supporting_ids")],
                contradicting_ids=[str(item) for item in form.getlist("contradicting_ids")],
                falsification_criterion=str(form.get("falsification_criterion") or ""),
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse(
            "/market-intelligence?ok=hypothesis_created#analysis", status_code=303
        )

    @router.post("/market-intelligence/validations")
    async def validation(request: Request, db: DatabaseSession, user: MarketUser):
        form = await request.form()
        _require_csrf(request, form)
        try:
            metric = json.loads(str(form.get("metric_json") or "{}"))
            sample = json.loads(str(form.get("sample_json") or "{}"))
            if not isinstance(metric, dict) or not isinstance(sample, dict):
                raise ValueError
            subject_type, separator, subject_id = str(form.get("subject_selector") or "").partition(
                ":"
            )
            if not separator or not subject_id:
                raise MarketIntelligenceError(
                    "validation_subject_required", "A validáció tárgya kötelező."
                )
            create_validation(
                db,
                actor=_actor(db, user),
                subject_type=subject_type,
                subject_id=subject_id,
                method=str(form.get("method") or ""),
                metric=metric,
                sample=sample,
                outcome=str(form.get("outcome") or ""),
            )
        except (MarketIntelligenceError, ValueError, json.JSONDecodeError) as error:
            return _error_redirect(
                error
                if isinstance(error, MarketIntelligenceError)
                else MarketIntelligenceError(
                    "validation_json_invalid", "A mérőszám vagy minta JSON hibás."
                )
            )
        return RedirectResponse(
            "/market-intelligence?ok=validation_created#validation", status_code=303
        )

    @router.post("/market-intelligence/validations/{validation_id}/{action}")
    async def validation_transition(
        validation_id: str, action: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            transition_validation(
                db, actor=_actor(db, user), validation_id=validation_id, action=action
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse(
            f"/market-intelligence?ok=validation_{action}#validation", status_code=303
        )

    @router.post("/market-intelligence/packs")
    async def pack(
        request: Request,
        db: DatabaseSession,
        user: MarketUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            create_pack(
                db,
                actor=_actor(db, user),
                title=str(form.get("title") or ""),
                summary=str(form.get("summary") or ""),
                intended_use=str(form.get("intended_use") or ""),
                channels=[item.strip() for item in str(form.get("channels") or "").split(",")],
                observation_ids=[str(item) for item in form.getlist("observation_ids")],
            )
        except MarketIntelligenceError as error:
            return _error_redirect(error)
        return RedirectResponse("/market-intelligence?ok=pack_created#packs", status_code=303)

    @router.post("/market-intelligence/packs/{pack_id}/{action}")
    async def pack_transition(
        pack_id: str,
        action: str,
        request: Request,
        db: DatabaseSession,
        user: MarketUser,
    ):
        form = await request.form()
        _require_csrf(request, form)
        try:
            if action == "handoff":
                handoff_pack(
                    db,
                    actor=_actor(db, user),
                    pack_id=pack_id,
                    downstream_purpose=str(form.get("downstream_purpose") or ""),
                    idempotency_key=str(form.get("idempotency_key") or ""),
                )
            elif action == "revise":
                revise_pack(
                    db,
                    actor=_actor(db, user),
                    pack_id=pack_id,
                    row_version=int(_form_scalar(form, "row_version") or 0),
                    title=str(form.get("title") or ""),
                    summary=str(form.get("summary") or ""),
                    intended_use=str(form.get("intended_use") or ""),
                    channels=[item.strip() for item in str(form.get("channels") or "").split(",")],
                    observation_ids=[str(item) for item in form.getlist("observation_ids")],
                )
            else:
                transition_pack(
                    db,
                    actor=_actor(db, user),
                    pack_id=pack_id,
                    row_version=int(_form_scalar(form, "row_version") or 0),
                    action=action,
                    reason=str(form.get("reason") or ""),
                )
        except (MarketIntelligenceError, ValueError) as error:
            return _error_redirect(
                error
                if isinstance(error, MarketIntelligenceError)
                else MarketIntelligenceError("invalid_number", "Hibás számérték.")
            )
        return RedirectResponse(f"/market-intelligence?ok=pack_{action}#packs", status_code=303)

    @router.get("/api/market-intelligence/dashboard")
    def api_dashboard(db: DatabaseSession, user: MarketUser):
        return dashboard(
            db,
            _actor(db, user),
            public_fetch_enabled=settings.market_public_fetch_enabled,
        )

    @router.post("/api/market-intelligence/targets", status_code=201)
    async def api_create_target(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_target,
            db,
            actor=_actor(db, user),
            name=str(payload.get("name") or ""),
            source_type=str(payload.get("sourceType") or "public_web"),
            origin=str(payload.get("origin") or ""),
            allowed_path=str(payload.get("allowedPath") or "/"),
            rights_status=str(payload.get("rightsStatus") or ""),
            capture_mode=str(payload.get("captureMode") or "manual"),
            rate_limit_max=_integer_default(payload, "rateLimitMax", 10),
            rate_limit_window_seconds=_integer_default(payload, "rateLimitWindowSeconds", 3600),
        )

    @router.post("/api/market-intelligence/targets/{target_id}/{action}")
    async def api_target_transition(
        target_id: str, action: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        payload = await _api_payload(request)
        version = _if_match_int(request)
        if action == "revise":
            return _api_call(
                revise_target,
                db,
                actor=_actor(db, user),
                target_id=target_id,
                row_version=version,
                name=str(payload.get("name") or ""),
                origin=str(payload.get("origin") or ""),
                allowed_path=str(payload.get("allowedPath") or "/"),
                rights_status=str(payload.get("rightsStatus") or ""),
                rate_limit_max=_optional_integer(payload, "rateLimitMax"),
                rate_limit_window_seconds=_optional_integer(payload, "rateLimitWindowSeconds"),
            )
        return _api_call(
            transition_target,
            db,
            actor=_actor(db, user),
            target_id=target_id,
            row_version=version,
            action=action,
            reason=str(payload.get("reason") or ""),
        )

    @router.post("/api/market-intelligence/snapshots", status_code=201)
    async def api_import_snapshot(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            import_manual_snapshot,
            db,
            actor=_actor(db, user),
            target_id=str(payload.get("targetId") or ""),
            resolved_url=str(payload.get("resolvedUrl") or ""),
            mime_type=str(payload.get("mimeType") or "text/plain"),
            content=str(payload.get("content") or ""),
            idempotency_key=_idempotency_key(request),
        )

    @router.post("/api/market-intelligence/snapshots/{snapshot_id}/quarantine")
    async def api_quarantine_snapshot(
        snapshot_id: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        payload = await _api_payload(request)
        return _api_call(
            quarantine_snapshot,
            db,
            actor=_actor(db, user),
            snapshot_id=snapshot_id,
            legal_basis=str(payload.get("legalBasis") or ""),
            reason=str(payload.get("reason") or ""),
        )

    @router.post("/api/market-intelligence/snapshots/{snapshot_id}/erase")
    async def api_erase_snapshot(
        snapshot_id: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        payload = await _api_payload(request)
        return _api_call(
            erase_snapshot_content,
            db,
            actor=_actor(db, user),
            snapshot_id=snapshot_id,
            legal_basis=str(payload.get("legalBasis") or ""),
            reason=str(payload.get("reason") or ""),
        )

    @router.post("/api/market-intelligence/capture-jobs", status_code=202)
    async def api_queue_capture_job(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            queue_public_capture,
            db,
            actor=_actor(db, user),
            target_id=str(payload.get("targetId") or ""),
            resolved_url=str(payload.get("resolvedUrl") or ""),
            idempotency_key=_idempotency_key(request),
            connector_enabled=settings.market_public_fetch_enabled,
        )

    @router.post("/api/market-intelligence/capture-jobs/{job_id}/{action}")
    async def api_capture_job_action(
        job_id: str, action: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        payload = await _api_payload(request)
        if action == "cancel":
            return _api_call(
                cancel_capture_job,
                db,
                actor=_actor(db, user),
                job_id=job_id,
                reason=str(payload.get("reason") or ""),
            )
        if action == "retry":
            return _api_call(
                retry_capture_job,
                db,
                actor=_actor(db, user),
                job_id=job_id,
                idempotency_key=_idempotency_key(request),
                connector_enabled=settings.market_public_fetch_enabled,
            )
        raise HTTPException(status_code=422, detail="Ismeretlen capture job művelet.")

    @router.post("/api/market-intelligence/observations", status_code=201)
    async def api_create_observation(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_observation,
            db,
            actor=_actor(db, user),
            snapshot_id=str(payload.get("snapshotId") or ""),
            statement=str(payload.get("statement") or ""),
            start_offset=_integer(payload, "startOffset"),
            end_offset=_integer(payload, "endOffset"),
            evidence_level=str(payload.get("evidenceLevel") or "OBSERVED"),
            method=str(payload.get("method") or ""),
            confidence=_optional_float(payload, "confidence"),
        )

    @router.post("/api/market-intelligence/assets", status_code=201)
    async def api_create_asset(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_asset,
            db,
            actor=_actor(db, user),
            snapshot_id=str(payload.get("snapshotId") or ""),
            channel=str(payload.get("channel") or ""),
            asset_type=str(payload.get("assetType") or ""),
            title=str(payload.get("title") or ""),
            start_offset=_integer(payload, "startOffset"),
            end_offset=_integer(payload, "endOffset"),
            claims=_string_list(payload, "claims"),
        )

    @router.post("/api/market-intelligence/voc-signals", status_code=201)
    async def api_create_voc(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_voc_signal,
            db,
            actor=_actor(db, user),
            snapshot_id=str(payload.get("snapshotId") or ""),
            masked_quote=str(payload.get("maskedQuote") or ""),
            theme=str(payload.get("theme") or ""),
            sentiment=str(payload.get("sentiment") or ""),
            start_offset=_integer(payload, "startOffset"),
            end_offset=_integer(payload, "endOffset"),
        )

    @router.post("/api/market-intelligence/clusters", status_code=201)
    async def api_create_cluster(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_pattern_cluster,
            db,
            actor=_actor(db, user),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            member_ids=_string_list(payload, "memberIds"),
            confidence=_optional_float(payload, "confidence"),
        )

    @router.post("/api/market-intelligence/clusters/{cluster_id}/revisions", status_code=201)
    async def api_revise_cluster(
        cluster_id: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        payload = await _api_payload(request)
        return _api_call(
            revise_pattern_cluster,
            db,
            actor=_actor(db, user),
            cluster_id=cluster_id,
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            member_ids=_string_list(payload, "memberIds"),
            confidence=_optional_float(payload, "confidence"),
        )

    @router.get("/api/market-intelligence/clusters/compare")
    def api_compare_clusters(left_id: str, right_id: str, db: DatabaseSession, user: MarketUser):
        return _api_call(
            compare_pattern_clusters,
            db,
            actor=_actor(db, user),
            left_id=left_id,
            right_id=right_id,
        )

    @router.post("/api/market-intelligence/hypotheses", status_code=201)
    async def api_create_hypothesis(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_hypothesis,
            db,
            actor=_actor(db, user),
            statement=str(payload.get("statement") or ""),
            audience=str(payload.get("audience") or ""),
            supporting_ids=_string_list(payload, "supportingIds"),
            contradicting_ids=_string_list(payload, "contradictingIds"),
            falsification_criterion=str(payload.get("falsificationCriterion") or ""),
        )

    @router.post("/api/market-intelligence/validations", status_code=201)
    async def api_create_validation(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_validation,
            db,
            actor=_actor(db, user),
            subject_type=str(payload.get("subjectType") or ""),
            subject_id=str(payload.get("subjectId") or ""),
            method=str(payload.get("method") or ""),
            metric=_json_object(payload, "metric"),
            sample=_json_object(payload, "sample"),
            outcome=str(payload.get("outcome") or ""),
        )

    @router.post("/api/market-intelligence/validations/{validation_id}/{action}")
    async def api_validation_transition(
        validation_id: str, action: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        await _api_payload(request)
        return _api_call(
            transition_validation,
            db,
            actor=_actor(db, user),
            validation_id=validation_id,
            action=action,
            expected_subject_sha256=_if_match_hash(request),
        )

    @router.post("/api/market-intelligence/packs", status_code=201)
    async def api_create_pack(request: Request, db: DatabaseSession, user: MarketUser):
        payload = await _api_payload(request)
        return _api_call(
            create_pack,
            db,
            actor=_actor(db, user),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            intended_use=str(payload.get("intendedUse") or ""),
            channels=_string_list(payload, "channels"),
            observation_ids=_string_list(payload, "memberIds"),
        )

    @router.post("/api/market-intelligence/packs/{pack_id}/revisions", status_code=201)
    async def api_revise_pack(
        pack_id: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        payload = await _api_payload(request)
        return _api_call(
            revise_pack,
            db,
            actor=_actor(db, user),
            pack_id=pack_id,
            row_version=_if_match_int(request),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            intended_use=str(payload.get("intendedUse") or ""),
            channels=_string_list(payload, "channels"),
            observation_ids=_string_list(payload, "memberIds"),
        )

    @router.get("/api/market-intelligence/packs/compare")
    def api_compare_packs(left_id: str, right_id: str, db: DatabaseSession, user: MarketUser):
        return _api_call(
            compare_packs,
            db,
            actor=_actor(db, user),
            left_id=left_id,
            right_id=right_id,
        )

    @router.post("/api/market-intelligence/packs/{pack_id}/{action}")
    async def api_pack_transition(
        pack_id: str, action: str, request: Request, db: DatabaseSession, user: MarketUser
    ):
        payload = await _api_payload(request)
        if action == "handoff":
            return _api_call(
                handoff_pack,
                db,
                actor=_actor(db, user),
                pack_id=pack_id,
                downstream_purpose=str(payload.get("downstreamPurpose") or ""),
                idempotency_key=_idempotency_key(request),
            )
        return _api_call(
            transition_pack,
            db,
            actor=_actor(db, user),
            pack_id=pack_id,
            row_version=_if_match_int(request),
            action=action,
            reason=str(payload.get("reason") or ""),
        )

    @router.get(
        "/api/v1/market-intelligence/source-targets",
        summary="List governed market source targets",
        tags=["Market Intelligence service API v1"],
    )
    def service_source_targets(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "source-targets"),
        }

    @router.get(
        "/api/v1/market-intelligence/capture-jobs",
        summary="List capture jobs in token scope",
        tags=["Market Intelligence service API v1"],
    )
    def service_capture_jobs(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "capture-jobs"),
        }

    @router.get(
        "/api/v1/market-intelligence/observations",
        summary="List provenance-bound observations",
        tags=["Market Intelligence service API v1"],
    )
    def service_observations(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "observations"),
        }

    @router.get(
        "/api/v1/market-intelligence/assets",
        summary="List governed creative assets",
        tags=["Market Intelligence service API v1"],
    )
    def service_assets(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "assets"),
        }

    @router.get(
        "/api/v1/market-intelligence/voc-signals",
        summary="List masked voice-of-customer signals",
        tags=["Market Intelligence service API v1"],
    )
    def service_voc_signals(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "voc-signals"),
        }

    @router.get(
        "/api/v1/market-intelligence/pattern-clusters",
        summary="List immutable pattern-cluster revisions",
        tags=["Market Intelligence service API v1"],
    )
    def service_pattern_clusters(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "pattern-clusters"),
        }

    @router.get(
        "/api/v1/market-intelligence/hypotheses",
        summary="List evidence-linked hypotheses",
        tags=["Market Intelligence service API v1"],
    )
    def service_hypotheses(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "hypotheses"),
        }

    @router.get(
        "/api/v1/market-intelligence/research-packs",
        summary="List immutable research-pack revisions",
        tags=["Market Intelligence service API v1"],
    )
    def service_research_packs(db: DatabaseSession, principal: MarketServiceRead):
        return {
            "scope": _service_scope(principal),
            "items": service_resource_list(db, principal.actor(), "research-packs"),
        }

    @router.post(
        "/api/v1/market-intelligence/research-packs/{pack_id}/handoff",
        summary="Handoff one frozen research pack",
        tags=["Market Intelligence service API v1"],
        responses={
            200: {
                "description": "Created or idempotently replayed handoff",
                "content": {
                    "application/json": {
                        "example": {
                            "handoffId": "MPH-0123456789AB",
                            "packId": "MRP-0123456789AB",
                            "status": "ACCEPTED",
                        }
                    }
                },
            }
        },
    )
    async def service_pack_handoff(
        pack_id: str,
        request: Request,
        db: DatabaseSession,
        principal: MarketServiceHandoff,
    ):
        payload = await _service_payload(request)
        return _api_call(
            handoff_pack,
            db,
            actor=principal.actor(),
            pack_id=pack_id,
            downstream_purpose=str(payload.get("downstreamPurpose") or ""),
            idempotency_key=_idempotency_key(request),
        )

    return router
