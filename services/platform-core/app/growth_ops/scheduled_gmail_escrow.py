from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ESCROW_SIGNING_PRIVATE_KEY_FILE_ENV = (
    "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SIGNING_PRIVATE_KEY_FILE"
)
ESCROW_SIGNING_PUBLIC_KEY_FILE_ENV = (
    "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SIGNING_PUBLIC_KEY_FILE"
)
ESCROW_SIGNING_KEY_ID_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SIGNING_KEY_ID"


class ScheduledGmailEscrowCryptoError(ValueError):
    pass


def canonical_escrow_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def escrow_sha256(value: object) -> str:
    return hashlib.sha256(canonical_escrow_json(value).encode("utf-8")).hexdigest()


def _strict_file(path_value: str, *, secret: bool, label: str) -> Path:
    if not path_value:
        raise ScheduledGmailEscrowCryptoError(f"{label}_missing")
    supplied = Path(path_value).expanduser()
    if not supplied.is_absolute():
        raise ScheduledGmailEscrowCryptoError(f"{label}_path_invalid")
    try:
        metadata = supplied.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ScheduledGmailEscrowCryptoError(f"{label}_permissions_invalid")
        resolved = supplied.resolve(strict=True)
        if os.name != "nt":
            mode = stat.S_IMODE(metadata.st_mode)
            allowed_modes = {0o600} if secret else {0o600, 0o640, 0o644}
            if mode not in allowed_modes or metadata.st_uid != os.geteuid():
                raise ScheduledGmailEscrowCryptoError(
                    f"{label}_permissions_invalid"
                )
    except OSError as exc:
        raise ScheduledGmailEscrowCryptoError(f"{label}_unreadable") from exc
    return resolved


def escrow_signing_key_id() -> str:
    key_id = os.getenv(ESCROW_SIGNING_KEY_ID_ENV, "").strip()
    if (
        not 8 <= len(key_id) <= 120
        or not key_id[0].isalnum()
        or any(not (character.isalnum() or character in "._:-") for character in key_id)
    ):
        raise ScheduledGmailEscrowCryptoError("escrow_signing_key_id_invalid")
    return key_id


def _load_private_key(path_value: str | None = None) -> Ed25519PrivateKey:
    path = _strict_file(
        path_value
        or os.getenv(ESCROW_SIGNING_PRIVATE_KEY_FILE_ENV, "").strip(),
        secret=True,
        label="escrow_signing_private_key",
    )
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, TypeError, ValueError) as exc:
        raise ScheduledGmailEscrowCryptoError(
            "escrow_signing_private_key_invalid"
        ) from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ScheduledGmailEscrowCryptoError("escrow_signing_private_key_invalid")
    return key


def _load_public_key(path_value: str | None = None) -> Ed25519PublicKey:
    path = _strict_file(
        path_value
        or os.getenv(ESCROW_SIGNING_PUBLIC_KEY_FILE_ENV, "").strip(),
        secret=False,
        label="escrow_signing_public_key",
    )
    try:
        key = serialization.load_pem_public_key(path.read_bytes())
    except (OSError, TypeError, ValueError) as exc:
        raise ScheduledGmailEscrowCryptoError(
            "escrow_signing_public_key_invalid"
        ) from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ScheduledGmailEscrowCryptoError("escrow_signing_public_key_invalid")
    return key


def sign_escrow_manifest(
    manifest: dict[str, Any],
    *,
    private_key_path: str | None = None,
) -> tuple[str, str, str]:
    manifest_sha256 = escrow_sha256(manifest)
    signature = _load_private_key(private_key_path).sign(
        canonical_escrow_json(manifest).encode("utf-8")
    )
    return (
        manifest_sha256,
        escrow_signing_key_id(),
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    )


def verify_escrow_manifest(
    manifest: dict[str, Any],
    *,
    manifest_sha256: str,
    signing_key_id: str,
    signature: str,
    public_key_path: str | None = None,
) -> None:
    if signing_key_id != escrow_signing_key_id():
        raise ScheduledGmailEscrowCryptoError("escrow_signing_key_id_mismatch")
    actual_sha256 = escrow_sha256(manifest)
    if actual_sha256 != manifest_sha256:
        raise ScheduledGmailEscrowCryptoError("escrow_manifest_hash_mismatch")
    try:
        padded = signature + "=" * (-len(signature) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        _load_public_key(public_key_path).verify(
            decoded,
            canonical_escrow_json(manifest).encode("utf-8"),
        )
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ScheduledGmailEscrowCryptoError(
            "escrow_manifest_signature_invalid"
        ) from exc


def verify_client_event_signature(
    event: dict[str, Any],
    *,
    signature: str,
    public_key_pem: str,
) -> None:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
        if not isinstance(key, Ed25519PublicKey):
            raise TypeError("not_ed25519")
        padded = signature + "=" * (-len(signature) % 4)
        key.verify(
            base64.urlsafe_b64decode(padded.encode("ascii")),
            canonical_escrow_json(event).encode("utf-8"),
        )
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ScheduledGmailEscrowCryptoError(
            "escrow_client_event_signature_invalid"
        ) from exc


def escrow_signing_readiness() -> dict[str, str | bool]:
    """Prove that the configured signing key pair is usable without changing state."""
    manifest = {"version": "scheduled-gmail-offline-signing-readiness-v1"}
    manifest_sha256, key_id, signature = sign_escrow_manifest(manifest)
    verify_escrow_manifest(
        manifest,
        manifest_sha256=manifest_sha256,
        signing_key_id=key_id,
        signature=signature,
    )
    return {
        "ready": True,
        "signing_key_id": key_id,
        "manifest_sha256": manifest_sha256,
    }
