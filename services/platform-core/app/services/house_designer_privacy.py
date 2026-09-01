from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import HouseDesignRevision, HouseDesignSiteVerification

PRIVATE_SITE_FIELDS = ("postalCode", "city", "address", "parcelNumber")
PRIVATE_SITE_ENVELOPE = "_privateSite"


class SitePrivacyError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def protect_site(site: dict[str, Any], revision_id: str) -> dict[str, Any]:
    public = dict(site)
    public.pop(PRIVATE_SITE_ENVELOPE, None)
    private = {field: str(public.pop(field, "") or "").strip() for field in PRIVATE_SITE_FIELDS}
    if not any(private.values()):
        return public

    plaintext = _json(private).encode("utf-8")
    content_sha256 = hashlib.sha256(plaintext).hexdigest()
    dek = secrets.token_bytes(32)
    content_nonce = secrets.token_bytes(12)
    dek_nonce = secrets.token_bytes(12)
    key_id = settings.house_designer_site_key_id
    content_aad = f"hd-site-content-v1:{revision_id}:{content_sha256}".encode()
    dek_aad = f"hd-site-dek-v1:{key_id}".encode()
    public[PRIVATE_SITE_ENVELOPE] = {
        "schemaVersion": "house-designer-private-site-v1",
        "keyId": key_id,
        "contentSha256": content_sha256,
        "contentNonce": _b64(content_nonce),
        "encryptedContent": _b64(AESGCM(dek).encrypt(content_nonce, plaintext, content_aad)),
        "dekNonce": _b64(dek_nonce),
        "encryptedDek": _b64(AESGCM(_site_kek()).encrypt(dek_nonce, dek, dek_aad)),
    }
    return public


def unprotect_site(site: dict[str, Any], revision_id: str) -> dict[str, Any]:
    logical = dict(site)
    envelope = logical.pop(PRIVATE_SITE_ENVELOPE, None)
    if envelope is None:
        for field in PRIVATE_SITE_FIELDS:
            logical[field] = str(logical.get(field, "") or "")
        return logical
    if not isinstance(envelope, dict):
        raise SitePrivacyError("site_envelope_invalid", "A telekadat titkosítási borítéka hibás.")
    key_id = str(envelope.get("keyId") or "")
    if key_id != settings.house_designer_site_key_id:
        raise SitePrivacyError(
            "site_key_version_unknown", "Ismeretlen telekadat-titkosítási kulcsverzió."
        )
    if envelope.get("schemaVersion") != "house-designer-private-site-v1":
        raise SitePrivacyError("site_envelope_invalid", "Ismeretlen telekadat-sémaverzió.")
    content_sha256 = str(envelope.get("contentSha256") or "")
    try:
        dek_nonce = _decode(envelope.get("dekNonce"))
        dek_aad = f"hd-site-dek-v1:{key_id}".encode()
        dek = AESGCM(_site_kek()).decrypt(dek_nonce, _decode(envelope.get("encryptedDek")), dek_aad)
        content_nonce = _decode(envelope.get("contentNonce"))
        content_aad = f"hd-site-content-v1:{revision_id}:{content_sha256}".encode()
        plaintext = AESGCM(dek).decrypt(
            content_nonce, _decode(envelope.get("encryptedContent")), content_aad
        )
        if not hmac.compare_digest(hashlib.sha256(plaintext).hexdigest(), content_sha256):
            raise ValueError("content hash mismatch")
        private = json.loads(plaintext.decode("utf-8"))
        if not isinstance(private, dict) or set(private) != set(PRIVATE_SITE_FIELDS):
            raise ValueError("private site schema mismatch")
    except (
        InvalidTag,
        binascii.Error,
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise SitePrivacyError(
            "site_decryption_failed", "A telekadat integritásellenőrzése sikertelen."
        ) from error
    for field in PRIVATE_SITE_FIELDS:
        logical[field] = str(private.get(field) or "")
    return logical


def verification_identity_token(municipality_code: str, parcel_number: str) -> str:
    normalized = f"{municipality_code.strip().upper()}\n{parcel_number.strip().upper()}".encode()
    return "h1:" + hmac.new(_site_kek(), normalized, hashlib.sha256).hexdigest()


def migrate_house_designer_site_encryption(db: Session) -> dict[str, int]:
    revisions = db.scalars(select(HouseDesignRevision).with_for_update()).all()
    encrypted_count = 0
    by_id: dict[str, dict[str, Any]] = {}
    for revision_row in revisions:
        raw = json.loads(revision_row.site_json)
        if not isinstance(raw, dict):
            raise SitePrivacyError("site_json_invalid", "A tárolt telekadat nem JSON objektum.")
        if PRIVATE_SITE_ENVELOPE not in raw and any(field in raw for field in PRIVATE_SITE_FIELDS):
            raw = protect_site(raw, revision_row.revision_id)
            revision_row.site_json = _json(raw)
            encrypted_count += 1
        by_id[revision_row.revision_id] = unprotect_site(raw, revision_row.revision_id)

    tokenized_count = 0
    verifications = db.scalars(select(HouseDesignSiteVerification).with_for_update()).all()
    for verification_row in verifications:
        if verification_row.parcel_number.startswith("h1:"):
            continue
        site = by_id.get(verification_row.verified_revision_id)
        if site is None or not str(site.get("parcelNumber") or "").strip():
            raise SitePrivacyError(
                "site_verification_cutover_failed",
                "Az igazolási rekord HRSZ-azonosítója nem állítható elő.",
            )
        verification_row.parcel_number = verification_identity_token(
            verification_row.municipality_code, str(site["parcelNumber"])
        )
        tokenized_count += 1

    if encrypted_count or tokenized_count:
        audit(
            db,
            actor="system:house-designer-site-encryption-cutover",
            action="house_designer.site.encryption_cutover",
            entity_type="HouseDesignRevision",
            after={
                "encrypted_revision_count": encrypted_count,
                "tokenized_verification_count": tokenized_count,
                "key_id": settings.house_designer_site_key_id,
            },
        )
        db.commit()
    return {"encrypted": encrypted_count, "tokenized": tokenized_count}


def has_private_site_values(site: dict[str, Any]) -> bool:
    return any(str(site.get(field) or "").strip() for field in PRIVATE_SITE_FIELDS)


def site_encryption_ready() -> bool:
    if not settings.house_designer_site_key_id.strip():
        return False
    try:
        site_key = _site_kek()
        market_key = base64.b64decode(settings.market_evidence_kek, validate=True)
    except (SitePrivacyError, binascii.Error, ValueError, TypeError):
        return False
    return len(market_key) == 32 and not hmac.compare_digest(site_key, market_key)


def _site_kek() -> bytes:
    try:
        key = base64.b64decode(settings.house_designer_site_kek, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise SitePrivacyError(
            "site_key_unavailable", "A telekadat-titkosítás kulcsa érvénytelen.", status_code=503
        ) from error
    if len(key) != 32:
        raise SitePrivacyError(
            "site_key_unavailable", "A telekadat-titkosítás kulcsa hiányzik.", status_code=503
        )
    return key


def _decode(value: Any) -> bytes:
    return base64.b64decode(str(value or ""), validate=True)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
