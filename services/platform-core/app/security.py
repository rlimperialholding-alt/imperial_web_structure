from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import PartnerFieldAccess, User


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
    return f"pbkdf2_sha256$240000${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, int(user_id))


def require_api_token(x_api_token: Annotated[str | None, Header()] = None) -> None:
    if settings.api_token and not hmac.compare_digest(x_api_token or "", settings.api_token):
        raise HTTPException(status_code=401, detail="Érvénytelen API token.")


def require_internal_job_token(x_internal_job_token: Annotated[str | None, Header()] = None) -> None:
    if settings.internal_job_token and not hmac.compare_digest(x_internal_job_token or "", settings.internal_job_token):
        raise HTTPException(status_code=401, detail="Érvénytelen belső job token.")


def require_role(*roles: str):
    def dependency(request: Request, db: Session = Depends(get_db)) -> User:
        user = current_user(request, db)
        if not user or not user.active:
            raise HTTPException(status_code=401, detail="Bejelentkezés szükséges.")
        if user.must_change_password:
            raise HTTPException(status_code=403, detail="A folytatáshoz előbb jelszót kell módosítani.")
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Nincs jogosultság.")
        return user
    return dependency


API_FINANCE_GATE_ROLES = ("finance", "managing-director", "owner", "platform-admin")


def require_api_token_finance_actor(
    request: Request,
    db: Session = Depends(get_db),
    x_api_token: Annotated[str | None, Header()] = None,
) -> User:
    """API token + bejelentkezett, pénzügyi/vezetői szerepkörű felhasználó.

    A TENDER-kapu adminisztratív API-útvonalainak (költségvetés-import
    jóváhagyás, allokációs pillanatképek) identitás-kötése: a generikus API
    token ÖNMAGÁBAN nem ad platform-admin szerepkört — a tényleges actor a
    session-felhasználó, az ő szerepköre az auditált döntéshozó.
    """
    if settings.api_token and not hmac.compare_digest(x_api_token or "", settings.api_token):
        raise HTTPException(status_code=401, detail="Érvénytelen API token.")
    user = current_user(request, db)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Bejelentkezés szükséges.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="A folytatáshoz előbb jelszót kell módosítani.")
    if user.role not in API_FINANCE_GATE_ROLES:
        raise HTTPException(status_code=403, detail="Nincs jogosultság.")
    return user


def require_session_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    user = current_user(request, db)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Bejelentkezés szükséges.")
    if user.must_change_password and request.url.path != "/account/password":
        raise HTTPException(status_code=403, detail="A folytatáshoz előbb jelszót kell módosítani.")
    return user



def current_partner_access(request: Request, db: Session) -> PartnerFieldAccess | None:
    access_id = request.session.get("partner_access_id")
    if not access_id:
        return None
    return db.scalar(select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == access_id))
