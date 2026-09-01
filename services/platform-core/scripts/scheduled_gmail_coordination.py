#!/usr/bin/env python3
"""Lease and reconcile scheduled Gmail deliveries through the local core API."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.growth_ops.scheduled_gmail_escrow import (
    ScheduledGmailEscrowCryptoError,
    canonical_escrow_json,
    escrow_sha256,
    verify_escrow_manifest,
)

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/internal/growth-ops/scheduled-gmail"
CLIENT_TOKEN_FILE_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_CLIENT_TOKEN_FILE"
LEASE_TOKEN_FILE_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_LEASE_TOKEN_FILE"
REQUEST_ID_FILE_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_REQUEST_ID_FILE"
ESCROW_CACHE_DB_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_CACHE_DB"
ESCROW_CACHE_KEY_FILE_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_CACHE_KEY_FILE"
ESCROW_CLIENT_SIGNING_KEY_FILE_ENV = (
    "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_CLIENT_SIGNING_KEY_FILE"
)
ESCROW_CLIENT_ID_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_CLIENT_ID"
ESCROW_SENDER_EMAIL_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SENDER_EMAIL"
ESCROW_MOTOR_KEYS_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_MOTOR_KEYS"
ESCROW_EVENT_VERSION = "scheduled-gmail-offline-sync-event-v1"
ESCROW_BUNDLE_VERSION = "scheduled-gmail-offline-bundle-v1"
ESCROW_PERMIT_VERSION = "scheduled-gmail-offline-permit-v1"
MAX_OFFLINE_WAIT_SECONDS = 3_600
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SECRET_KEY_RE = re.compile(
    r"(?:authorization|bearer|credential|password|secret|token)",
    re.IGNORECASE,
)


class CoordinationError(RuntimeError):
    def __init__(self, message: str, *, detail: object | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        del req, fp, code, msg, headers, newurl
        return None


def _secure_token_path(path: Path, *, label: str) -> Path:
    if not path.is_absolute():
        raise CoordinationError(f"{label}_path_must_be_absolute")
    try:
        if os.name != "nt":
            metadata = path.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
            ):
                raise CoordinationError(f"{label}_file_permissions_invalid")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CoordinationError(f"{label}_file_unreadable") from exc
    return resolved


def _read_raw_token(path: Path, *, label: str) -> str:
    path = _secure_token_path(path, label=label)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CoordinationError(f"{label}_file_unreadable") from exc
    if not raw or len(raw) > 16_384:
        raise CoordinationError(f"{label}_file_invalid")
    try:
        token = raw.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise CoordinationError(f"{label}_file_invalid_utf8") from exc
    if not token or any(character.isspace() for character in token):
        raise CoordinationError(f"{label}_file_invalid")
    return token


def _write_raw_token(path: Path, token: str) -> None:
    if not token or any(character.isspace() for character in token):
        raise CoordinationError("lease_response_token_invalid")
    if not path.is_absolute():
        raise CoordinationError("lease_token_path_must_be_absolute")
    parent = path.parent.resolve()
    if not parent.is_dir():
        raise CoordinationError("lease_token_parent_missing")
    if os.name != "nt":
        allowed_roots = (Path("/tmp"), Path("/run/secrets/growth"))
        if not any(parent == root or parent.is_relative_to(root) for root in allowed_roots):
            raise CoordinationError("lease_token_parent_not_approved")
        if path.exists():
            _secure_token_path(path, label="lease_token")
    temporary_path: str | None = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=str(parent),
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
        _secure_token_path(path, label="lease_token")
    except OSError as exc:
        raise CoordinationError("lease_token_file_write_failed") from exc
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _validated_api_base_url(value: str) -> str:
    candidate = str(value or "").rstrip("/")
    parsed = urllib.parse.urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/api/internal/growth-ops/scheduled-gmail"
    ):
        raise CoordinationError("api_base_url_must_be_loopback_coordination_endpoint")
    return candidate


def _identifier(value: str, *, label: str) -> str:
    candidate = str(value or "")
    if not IDENTIFIER_RE.fullmatch(candidate):
        raise CoordinationError(f"{label}_invalid")
    return candidate


def _request_identifier(value: str) -> str:
    candidate = _identifier(value, label="request_id")
    if len(candidate) < 16 or len(candidate) > 120:
        raise CoordinationError("request_id_invalid")
    return candidate


def _sanitize(value: object, *, secrets: tuple[str, ...]) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text):
                sanitized[key_text] = "<redacted>"
            else:
                sanitized[key_text] = _sanitize(item, secrets=secrets)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        sanitized_text = value
        for secret in secrets:
            if secret:
                sanitized_text = sanitized_text.replace(secret, "<redacted>")
        return sanitized_text
    return value


def _json_response(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CoordinationError("coordination_api_response_invalid_json") from exc
    if not isinstance(payload, dict):
        raise CoordinationError("coordination_api_response_not_object")
    return payload


def _request(
    *,
    method: str,
    url: str,
    bearer_token: str,
    payload: dict[str, object] | None,
    expected_statuses: set[int],
    known_secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    data = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "imperial-scheduled-gmail-coordination/1",
    }
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            status = int(response.status)
            raw = response.read(10_000_000)
    except urllib.error.HTTPError as exc:
        try:
            raw_error = exc.read(1_000_000)
            detail = _json_response(raw_error)
        except (OSError, CoordinationError):
            detail = {"error": "coordination_api_http_error"}
        raise CoordinationError(
            f"coordination_api_http_{exc.code}",
            detail=_sanitize(
                detail,
                secrets=(bearer_token, *known_secrets),
            ),
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise CoordinationError(f"coordination_api_unavailable:{type(exc).__name__}") from exc
    if status not in expected_statuses:
        raise CoordinationError(f"coordination_api_unexpected_status_{status}")
    return _json_response(raw)


def _offline_fallback_allowed(error: BaseException) -> bool:
    """Allow escrow only for connectivity failures or transient server outages."""

    current: BaseException | None = error
    while current is not None:
        if isinstance(current, CoordinationError):
            message = str(current)
            for prefix in (
                "coordination_api_http_",
                "coordination_api_unexpected_status_",
            ):
                if message.startswith(prefix):
                    try:
                        status = int(message.removeprefix(prefix))
                    except ValueError:
                        return False
                    return status in {502, 503, 504}
            if message.startswith("coordination_api_unavailable:"):
                return not message.endswith("HTTPError")
        if isinstance(current, urllib.error.HTTPError):
            return int(current.code) in {502, 503, 504}
        if isinstance(
            current,
            (
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                ConnectionAbortedError,
                ConnectionRefusedError,
                ConnectionResetError,
            ),
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _utc(value: datetime | str, *, label: str) -> datetime:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise CoordinationError(f"{label}_invalid") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise CoordinationError(f"{label}_invalid")
    if parsed.tzinfo is None:
        raise CoordinationError(f"{label}_timezone_required")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime | str, *, label: str) -> str:
    return _utc(value, label=label).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _monotonic() -> float:
    return time.monotonic()


def _sleep_seconds(value: float) -> None:
    time.sleep(value)


def _bounded_wait_seconds(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("wait seconds must be an integer") from exc
    if not 0 <= parsed <= MAX_OFFLINE_WAIT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"wait seconds must be between 0 and {MAX_OFFLINE_WAIT_SECONDS}"
        )
    return parsed


def _private_path(path: Path, *, label: str, create: bool = False) -> Path:
    if not path.is_absolute():
        raise CoordinationError(f"{label}_path_must_be_absolute")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise CoordinationError(f"{label}_parent_missing")
    if create and not path.exists():
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CoordinationError(f"{label}_create_failed") from exc
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise CoordinationError(f"{label}_file_permissions_invalid")
        if os.name != "nt" and (
            stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise CoordinationError(f"{label}_file_permissions_invalid")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CoordinationError(f"{label}_file_unreadable") from exc
    return resolved


def _write_private_bytes(path: Path, value: bytes, *, label: str) -> Path:
    if not path.is_absolute():
        raise CoordinationError(f"{label}_path_must_be_absolute")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise CoordinationError(f"{label}_parent_missing")
    temporary_path: str | None = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=str(parent),
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as exc:
        raise CoordinationError(f"{label}_write_failed") from exc
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
    return _private_path(path, label=label)


def _cache_key(path_value: str | None) -> tuple[Path, bytes]:
    raw_path = path_value or os.environ.get(ESCROW_CACHE_KEY_FILE_ENV)
    if not raw_path:
        raise CoordinationError("escrow_cache_key_file_required")
    path = Path(raw_path)
    if not path.is_absolute():
        raise CoordinationError("escrow_cache_key_path_must_be_absolute")
    if not path.exists():
        parent = path.parent.resolve(strict=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(AESGCM.generate_key(bit_length=256))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o600)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CoordinationError("escrow_cache_key_create_failed") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if not parent.is_dir():
            raise CoordinationError("escrow_cache_key_parent_missing")
    resolved = _private_path(path, label="escrow_cache_key")
    try:
        value = resolved.read_bytes()
    except OSError as exc:
        raise CoordinationError("escrow_cache_key_file_unreadable") from exc
    if len(value) != 32:
        raise CoordinationError("escrow_cache_key_invalid")
    return resolved, value


def _load_or_derive_client_signing_key(
    *,
    path_value: str | None,
    encryption_key: bytes,
    client_id: str,
) -> Ed25519PrivateKey:
    if not path_value:
        # A domain-separated seed keeps the test seam deterministic. Production
        # callers pass a registered, dedicated key file.
        seed = hashlib.sha256(
            b"imperial-scheduled-gmail-offline-client-signing-v1\0"
            + encryption_key
            + b"\0"
            + client_id.encode("utf-8")
        ).digest()
        return Ed25519PrivateKey.from_private_bytes(seed)
    path = _private_path(Path(path_value), label="escrow_client_signing_key")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, TypeError, ValueError) as exc:
        raise CoordinationError("escrow_client_signing_key_invalid") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise CoordinationError("escrow_client_signing_key_invalid")
    return key


class OfflineEscrowJournal:
    """Encrypted, single-use local escrow journal for coordination outages."""

    def __init__(
        self,
        path: str | Path,
        encryption_key: bytes,
        client_id: str,
        sender_email: str,
        motor_keys: Sequence[str],
        *,
        client_signing_key_file: str | None = None,
        server_public_key_file: str | None = None,
    ) -> None:
        supplied = Path(path)
        self.path = _private_path(supplied, label="escrow_cache_db", create=True)
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise CoordinationError("escrow_encryption_key_invalid")
        self._cipher = AESGCM(encryption_key)
        self.client_id = _identifier(client_id, label="escrow_client_id")
        sender = str(sender_email or "").strip().lower()
        if "@" not in sender or any(character.isspace() for character in sender):
            raise CoordinationError("escrow_sender_email_invalid")
        self.sender_email = sender
        self.motor_keys = frozenset(
            _identifier(value, label="escrow_motor_key") for value in motor_keys
        )
        if not self.motor_keys:
            raise CoordinationError("escrow_motor_keys_empty")
        self.server_public_key_file = server_public_key_file
        self._client_private_key = _load_or_derive_client_signing_key(
            path_value=client_signing_key_file,
            encryption_key=encryption_key,
            client_id=self.client_id,
        )
        client_public_pem = self._client_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.client_public_key_sha256 = hashlib.sha256(client_public_pem).hexdigest()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path, label="escrow_cache_db")
        connection = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            connection.close()
            raise CoordinationError("escrow_cache_wal_unavailable")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.path}{suffix}")
            if sidecar.exists():
                try:
                    os.chmod(sidecar, 0o600)
                except OSError as exc:
                    connection.close()
                    raise CoordinationError("escrow_cache_sidecar_permissions_failed") from exc
        return connection

    @contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS escrow_bundles (
                    bundle_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    client_id TEXT NOT NULL,
                    client_key_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL UNIQUE,
                    signing_key_id TEXT NOT NULL,
                    manifest_signature TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    encrypted_bundle BLOB NOT NULL,
                    bundle_nonce BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS escrow_permits (
                    permit_id TEXT PRIMARY KEY,
                    bundle_id TEXT NOT NULL REFERENCES escrow_bundles(bundle_id),
                    permit_index INTEGER NOT NULL,
                    client_key_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'READY','CONSUMING','PROVIDER_ACCEPTED','AMBIGUOUS',
                        'PRETRANSPORT_ABORTED','RELEASED','SENT','ACCEPTED_UNVERIFIED'
                    )),
                    sender_email TEXT NOT NULL,
                    motor_key TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    exact_payload_sha256 TEXT NOT NULL,
                    quota_local_date TEXT NOT NULL,
                    slot_not_before TEXT NOT NULL,
                    slot_not_after TEXT NOT NULL,
                    permit_token_sha256 TEXT NOT NULL,
                    permit_manifest_sha256 TEXT NOT NULL UNIQUE,
                    signing_key_id TEXT NOT NULL,
                    permit_signature TEXT NOT NULL,
                    encrypted_secret BLOB NOT NULL,
                    secret_nonce BLOB NOT NULL,
                    claimed_at TEXT,
                    provider_message_id TEXT UNIQUE,
                    terminal_reason TEXT,
                    last_client_sequence INTEGER NOT NULL DEFAULT 0,
                    last_event_sha256 TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(bundle_id, permit_index)
                );
                CREATE INDEX IF NOT EXISTS ix_escrow_permits_next
                    ON escrow_permits(status, slot_not_before, slot_not_after, permit_index);
                CREATE TABLE IF NOT EXISTS escrow_events (
                    event_id TEXT PRIMARY KEY,
                    permit_id TEXT NOT NULL REFERENCES escrow_permits(permit_id),
                    bundle_id TEXT NOT NULL REFERENCES escrow_bundles(bundle_id),
                    client_sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL UNIQUE,
                    encrypted_event BLOB NOT NULL,
                    event_nonce BLOB NOT NULL,
                    synced_at TEXT,
                    processing_status TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(permit_id, client_sequence)
                );
                CREATE INDEX IF NOT EXISTS ix_escrow_events_pending
                    ON escrow_events(bundle_id, synced_at, client_sequence);
                """
            )
        finally:
            connection.close()

    def journal_mode(self) -> str:
        connection = self._connect()
        try:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        finally:
            connection.close()

    def _encrypt(self, value: object, *, aad: str) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        plaintext = canonical_escrow_json(value).encode("utf-8")
        return nonce, self._cipher.encrypt(nonce, plaintext, aad.encode("utf-8"))

    def _decrypt(self, nonce: bytes, ciphertext: bytes, *, aad: str) -> Any:
        try:
            raw = self._cipher.decrypt(nonce, ciphertext, aad.encode("utf-8"))
            return json.loads(raw)
        except (InvalidTag, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CoordinationError("escrow_cache_ciphertext_invalid") from exc

    @staticmethod
    def _manifest_matches_response(
        manifest: dict[str, Any],
        response: dict[str, Any],
        *,
        excluded: frozenset[str] = frozenset(),
    ) -> bool:
        for key, value in manifest.items():
            if key in excluded:
                continue
            if key not in response:
                continue
            if response.get(key) != value:
                return False
        return True

    def _assert_client_public_key_binding(self, bundle: dict[str, Any]) -> None:
        manifest = bundle.get("manifest")
        candidates: list[object] = []
        if "client_public_key_sha256" in bundle:
            candidates.append(bundle.get("client_public_key_sha256"))
        if isinstance(manifest, dict) and "client_public_key_sha256" in manifest:
            candidates.append(manifest.get("client_public_key_sha256"))
        if not candidates:
            return
        bindings = {str(value or "") for value in candidates}
        if (
            len(bindings) != 1
            or not all(SHA256_RE.fullmatch(value) for value in bindings)
            or self.client_public_key_sha256 not in bindings
        ):
            raise CoordinationError("escrow_bundle_client_public_key_mismatch")

    def import_bundle(
        self,
        bundle: dict[str, Any],
        now: datetime | str,
    ) -> int:
        if not isinstance(bundle, dict):
            raise CoordinationError("escrow_bundle_invalid")
        imported_at = _utc_text(now, label="escrow_imported_at")
        manifest = bundle.get("manifest")
        if not isinstance(manifest, dict) or manifest.get("version") != ESCROW_BUNDLE_VERSION:
            raise CoordinationError("escrow_bundle_manifest_invalid")
        try:
            verify_escrow_manifest(
                manifest,
                manifest_sha256=str(bundle.get("manifest_sha256") or ""),
                signing_key_id=str(bundle.get("signing_key_id") or ""),
                signature=str(bundle.get("manifest_signature") or ""),
                public_key_path=self.server_public_key_file,
            )
        except ScheduledGmailEscrowCryptoError as exc:
            raise CoordinationError(str(exc)) from exc
        if not self._manifest_matches_response(
            manifest,
            bundle,
            excluded=frozenset({"version", "permits"}),
        ):
            raise CoordinationError("escrow_bundle_manifest_response_mismatch")
        self._assert_client_public_key_binding(bundle)
        bundle_id = _identifier(str(bundle.get("bundle_id") or ""), label="bundle_id")
        if str(bundle.get("client_id") or "") != self.client_id:
            raise CoordinationError("escrow_bundle_client_mismatch")
        valid_from = _utc_text(bundle.get("valid_from"), label="escrow_bundle_valid_from")
        expires_at = _utc_text(bundle.get("expires_at"), label="escrow_bundle_expires_at")
        if _utc(valid_from, label="escrow_bundle_valid_from") >= _utc(
            expires_at, label="escrow_bundle_expires_at"
        ):
            raise CoordinationError("escrow_bundle_time_window_invalid")
        permits = bundle.get("permits")
        if not isinstance(permits, list) or not permits:
            raise CoordinationError("escrow_bundle_permits_missing")
        try:
            permit_count = int(manifest.get("permit_count") or 0)
        except (TypeError, ValueError) as exc:
            raise CoordinationError("escrow_bundle_permit_count_mismatch") from exc
        if permit_count != len(permits):
            raise CoordinationError("escrow_bundle_permit_count_mismatch")
        signed_permits = manifest.get("permits")
        if not isinstance(signed_permits, list):
            raise CoordinationError("escrow_bundle_permit_index_invalid")
        try:
            signed_ref_list = [
                (
                    int(item.get("permit_index")),
                    str(item.get("permit_id") or ""),
                    str(item.get("permit_manifest_sha256") or ""),
                )
                for item in signed_permits
                if isinstance(item, dict)
            ]
        except (TypeError, ValueError) as exc:
            raise CoordinationError("escrow_bundle_permit_index_invalid") from exc
        if (
            len(signed_ref_list) != len(permits)
            or signed_ref_list != sorted(signed_ref_list)
            or len(set(signed_ref_list)) != len(signed_ref_list)
        ):
            raise CoordinationError("escrow_bundle_permit_index_invalid")
        signed_refs = set(signed_ref_list)
        prepared: list[dict[str, Any]] = []
        for permit in permits:
            if not isinstance(permit, dict):
                raise CoordinationError("escrow_permit_invalid")
            permit_manifest = permit.get("manifest")
            if (
                not isinstance(permit_manifest, dict)
                or permit_manifest.get("version") != ESCROW_PERMIT_VERSION
            ):
                raise CoordinationError("escrow_permit_manifest_invalid")
            try:
                verify_escrow_manifest(
                    permit_manifest,
                    manifest_sha256=str(permit.get("permit_manifest_sha256") or ""),
                    signing_key_id=str(permit.get("signing_key_id") or ""),
                    signature=str(permit.get("permit_signature") or ""),
                    public_key_path=self.server_public_key_file,
                )
            except ScheduledGmailEscrowCryptoError as exc:
                raise CoordinationError(str(exc)) from exc
            if not self._manifest_matches_response(
                permit_manifest,
                permit,
                excluded=frozenset({"version"}),
            ):
                raise CoordinationError("escrow_permit_manifest_response_mismatch")
            permit_id = _identifier(
                str(permit.get("permit_id") or ""), label="permit_id"
            )
            try:
                permit_index = int(permit.get("permit_index"))
            except (TypeError, ValueError) as exc:
                raise CoordinationError("escrow_permit_index_invalid") from exc
            if permit_index < 0:
                raise CoordinationError("escrow_permit_index_invalid")
            permit_manifest_sha256 = str(
                permit.get("permit_manifest_sha256") or ""
            )
            if (
                permit_index,
                permit_id,
                permit_manifest_sha256,
            ) not in signed_refs:
                raise CoordinationError("escrow_permit_not_bound_to_bundle")
            if str(permit.get("bundle_id") or "") != bundle_id:
                raise CoordinationError("escrow_permit_bundle_mismatch")
            if str(permit.get("client_id") or "") != self.client_id:
                raise CoordinationError("escrow_permit_client_mismatch")
            sender_email = str(permit.get("sender_email") or "").strip().lower()
            if sender_email != self.sender_email:
                raise CoordinationError("escrow_permit_sender_mismatch")
            motor_key = str(permit.get("motor_key") or "")
            if motor_key not in self.motor_keys:
                raise CoordinationError("escrow_permit_motor_not_allowed")
            payload = permit.get("payload")
            if not isinstance(payload, dict):
                raise CoordinationError("escrow_permit_payload_missing")
            exact_payload_sha256 = str(permit.get("exact_payload_sha256") or "")
            if (
                not SHA256_RE.fullmatch(exact_payload_sha256)
                or escrow_sha256(payload) != exact_payload_sha256
            ):
                raise CoordinationError("escrow_exact_payload_hash_mismatch")
            payload_sha256 = str(permit.get("payload_sha256") or "")
            if not SHA256_RE.fullmatch(payload_sha256):
                raise CoordinationError("escrow_payload_hash_invalid")
            if (
                str(payload.get("sender_email") or "").lower() != sender_email
                or str(payload.get("payload_sha256") or "") != payload_sha256
                or str(payload.get("outreach_id") or "")
                != str(permit.get("outreach_id") or "")
            ):
                raise CoordinationError("escrow_permit_payload_contract_invalid")
            permit_token = str(permit.get("permit_token") or "")
            if len(permit_token) < 32 or any(
                character.isspace() for character in permit_token
            ):
                raise CoordinationError("escrow_permit_token_invalid")
            token_sha256 = hashlib.sha256(permit_token.encode("utf-8")).hexdigest()
            if token_sha256 != str(permit_manifest.get("permit_token_sha256") or ""):
                raise CoordinationError("escrow_permit_token_hash_mismatch")
            slot_not_before = _utc_text(
                permit.get("slot_not_before"), label="escrow_slot_not_before"
            )
            slot_not_after = _utc_text(
                permit.get("slot_not_after"), label="escrow_slot_not_after"
            )
            if _utc(slot_not_before, label="escrow_slot_not_before") >= _utc(
                slot_not_after, label="escrow_slot_not_after"
            ):
                raise CoordinationError("escrow_permit_slot_invalid")
            quota_local_date = str(permit.get("quota_local_date") or "")
            try:
                date.fromisoformat(quota_local_date)
            except ValueError as exc:
                raise CoordinationError("escrow_quota_local_date_invalid") from exc
            secret = {
                "payload": payload,
                "permit_token": permit_token,
                "permit": permit,
            }
            nonce, encrypted_secret = self._encrypt(
                secret, aad=f"escrow-permit:{permit_id}"
            )
            prepared.append(
                {
                    "permit_id": permit_id,
                    "permit_index": permit_index,
                    "client_key_id": str(permit.get("client_key_id") or ""),
                    "sender_email": sender_email,
                    "motor_key": motor_key,
                    "payload_sha256": payload_sha256,
                    "exact_payload_sha256": exact_payload_sha256,
                    "quota_local_date": quota_local_date,
                    "slot_not_before": slot_not_before,
                    "slot_not_after": slot_not_after,
                    "permit_token_sha256": token_sha256,
                    "permit_manifest_sha256": permit_manifest_sha256,
                    "signing_key_id": str(permit.get("signing_key_id") or ""),
                    "permit_signature": str(permit.get("permit_signature") or ""),
                    "encrypted_secret": encrypted_secret,
                    "secret_nonce": nonce,
                }
            )
        if {
            (
                int(item["permit_index"]),
                str(item["permit_id"]),
                str(item["permit_manifest_sha256"]),
            )
            for item in prepared
        } != signed_refs:
            raise CoordinationError("escrow_bundle_permit_set_mismatch")
        bundle_start = _utc(valid_from, label="escrow_bundle_valid_from")
        bundle_end = _utc(expires_at, label="escrow_bundle_expires_at")
        ordered_slots = sorted(
            (
                _utc(str(item["slot_not_before"]), label="escrow_slot_not_before"),
                _utc(str(item["slot_not_after"]), label="escrow_slot_not_after"),
                int(item["permit_index"]),
            )
            for item in prepared
        )
        previous_slot_end: datetime | None = None
        for slot_start, slot_end, _permit_index in ordered_slots:
            if (
                slot_start < bundle_start
                or slot_end > bundle_end
                or (
                    previous_slot_end is not None
                    and slot_start < previous_slot_end
                )
            ):
                raise CoordinationError("escrow_permit_slots_overlap_or_escape_bundle")
            previous_slot_end = slot_end
        bundle_nonce, encrypted_bundle = self._encrypt(
            bundle, aad=f"escrow-bundle:{bundle_id}"
        )
        inserted = 0
        with self._immediate() as connection:
            prior = connection.execute(
                "SELECT manifest_sha256 FROM escrow_bundles WHERE bundle_id = ?",
                (bundle_id,),
            ).fetchone()
            if prior is not None:
                if prior["manifest_sha256"] != str(bundle.get("manifest_sha256") or ""):
                    raise CoordinationError("escrow_bundle_id_reused")
                return 0
            connection.execute(
                """
                INSERT INTO escrow_bundles (
                    bundle_id, request_id, client_id, client_key_id, status,
                    valid_from, expires_at, manifest_sha256, signing_key_id,
                    manifest_signature, imported_at, encrypted_bundle, bundle_nonce
                ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle_id,
                    str(bundle.get("request_id") or ""),
                    self.client_id,
                    str(bundle.get("client_key_id") or ""),
                    valid_from,
                    expires_at,
                    str(bundle.get("manifest_sha256") or ""),
                    str(bundle.get("signing_key_id") or ""),
                    str(bundle.get("manifest_signature") or ""),
                    imported_at,
                    encrypted_bundle,
                    bundle_nonce,
                ),
            )
            for item in prepared:
                connection.execute(
                    """
                    INSERT INTO escrow_permits (
                        permit_id, bundle_id, permit_index, client_key_id, status,
                        sender_email, motor_key, payload_sha256,
                        exact_payload_sha256, quota_local_date, slot_not_before,
                        slot_not_after, permit_token_sha256,
                        permit_manifest_sha256, signing_key_id, permit_signature,
                        encrypted_secret, secret_nonce, updated_at
                    ) VALUES (?, ?, ?, ?, 'READY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["permit_id"],
                        bundle_id,
                        item["permit_index"],
                        item["client_key_id"],
                        item["sender_email"],
                        item["motor_key"],
                        item["payload_sha256"],
                        item["exact_payload_sha256"],
                        item["quota_local_date"],
                        item["slot_not_before"],
                        item["slot_not_after"],
                        item["permit_token_sha256"],
                        item["permit_manifest_sha256"],
                        item["signing_key_id"],
                        item["permit_signature"],
                        item["encrypted_secret"],
                        item["secret_nonce"],
                        imported_at,
                    ),
                )
                inserted += 1
        return inserted

    def _append_event(
        self,
        connection: sqlite3.Connection,
        permit: sqlite3.Row,
        *,
        event_type: str,
        occurred_at: datetime | str,
        provider_transport_called: bool,
        provider_message_id: str | None,
        reason: str | None,
    ) -> dict[str, Any]:
        sequence = int(permit["last_client_sequence"]) + 1
        previous_hash = permit["last_event_sha256"]
        event_id = f"SGE-{secrets.token_urlsafe(24)}"
        signed_event: dict[str, Any] = {
            "version": ESCROW_EVENT_VERSION,
            "event_id": event_id,
            "permit_id": permit["permit_id"],
            "bundle_id": permit["bundle_id"],
            "client_id": self.client_id,
            "client_key_id": permit["client_key_id"],
            "client_sequence": sequence,
            "event_type": event_type,
            "occurred_at": _utc_text(occurred_at, label="escrow_event_occurred_at"),
            "payload_sha256": permit["payload_sha256"],
            "exact_payload_sha256": permit["exact_payload_sha256"],
            "permit_token_sha256": permit["permit_token_sha256"],
            "previous_event_sha256": previous_hash,
            "client_public_key_sha256": self.client_public_key_sha256,
            "provider_transport_called": provider_transport_called,
            "provider_message_id": provider_message_id,
            "reason": reason,
        }
        event_sha256 = escrow_sha256(signed_event)
        signature = self._client_private_key.sign(
            canonical_escrow_json(signed_event).encode("utf-8")
        )
        secret = self._decrypt(
            permit["secret_nonce"],
            permit["encrypted_secret"],
            aad=f"escrow-permit:{permit['permit_id']}",
        )
        permit_token = str(secret.get("permit_token") or "")
        public_event: dict[str, Any] = {
            "event_id": event_id,
            "permit_id": permit["permit_id"],
            "client_sequence": sequence,
            "event_type": event_type,
            "occurred_at": signed_event["occurred_at"],
            "payload_sha256": permit["payload_sha256"],
            "exact_payload_sha256": permit["exact_payload_sha256"],
            "previous_event_sha256": previous_hash,
            "event_sha256": event_sha256,
            "client_key_id": permit["client_key_id"],
            "client_signature": base64.urlsafe_b64encode(signature)
            .decode("ascii")
            .rstrip("="),
            "permit_token": permit_token,
            "provider_transport_called": provider_transport_called,
            "provider_message_id": provider_message_id,
            "reason": reason,
        }
        nonce, encrypted_event = self._encrypt(
            public_event, aad=f"escrow-event:{event_id}"
        )
        connection.execute(
            """
            INSERT INTO escrow_events (
                event_id, permit_id, bundle_id, client_sequence, event_type,
                event_sha256, encrypted_event, event_nonce, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                permit["permit_id"],
                permit["bundle_id"],
                sequence,
                event_type,
                event_sha256,
                encrypted_event,
                nonce,
                signed_event["occurred_at"],
            ),
        )
        connection.execute(
            """
            UPDATE escrow_permits
            SET last_client_sequence = ?, last_event_sha256 = ?, updated_at = ?
            WHERE permit_id = ?
            """,
            (
                sequence,
                event_sha256,
                signed_event["occurred_at"],
                permit["permit_id"],
            ),
        )
        return public_event

    def next_ready_schedule(
        self,
        now: datetime | str,
    ) -> dict[str, Any] | None:
        """Return only timing metadata for the next unconsumed valid permit."""

        checked_at = _utc_text(now, label="escrow_schedule_checked_at")
        checked_datetime = _utc(checked_at, label="escrow_schedule_checked_at")
        connection = self._connect()
        try:
            permit = connection.execute(
                """
                SELECT p.slot_not_before
                FROM escrow_permits AS p
                JOIN escrow_bundles AS b ON b.bundle_id = p.bundle_id
                WHERE p.status = 'READY'
                  AND b.status = 'ACTIVE'
                  AND b.expires_at > ?
                  AND p.slot_not_before > ?
                  AND p.slot_not_after > p.slot_not_before
                  AND p.slot_not_before < b.expires_at
                  AND NOT EXISTS (
                      SELECT 1 FROM escrow_events AS e
                      WHERE e.permit_id = p.permit_id
                        AND e.event_type = 'expired_unused'
                  )
                ORDER BY p.slot_not_before, p.permit_index, p.permit_id
                LIMIT 1
                """,
                (checked_at, checked_at),
            ).fetchone()
            if permit is None:
                return None
            next_due_at = _utc_text(
                permit["slot_not_before"], label="escrow_next_due_at"
            )
            wait_seconds = max(
                0,
                math.ceil(
                    (
                        _utc(next_due_at, label="escrow_next_due_at")
                        - checked_datetime
                    ).total_seconds()
                ),
            )
            return {
                "status": "WAITING_FOR_PERMIT_SLOT",
                "next_due_at": next_due_at,
                "wait_seconds": wait_seconds,
            }
        finally:
            connection.close()

    def claim_next(
        self,
        now: datetime | str,
        coordination_error: BaseException,
    ) -> dict[str, Any] | None:
        if not _offline_fallback_allowed(coordination_error):
            raise coordination_error
        claimed_at = _utc_text(now, label="escrow_claimed_at")
        with self._immediate() as connection:
            permit = connection.execute(
                """
                SELECT p.*, b.encrypted_bundle AS cached_bundle,
                       b.bundle_nonce AS cached_bundle_nonce
                FROM escrow_permits AS p
                JOIN escrow_bundles AS b ON b.bundle_id = p.bundle_id
                WHERE p.status = 'READY'
                  AND b.status = 'ACTIVE'
                  AND b.valid_from <= ? AND b.expires_at > ?
                  AND p.slot_not_before <= ? AND p.slot_not_after > ?
                  AND NOT EXISTS (
                      SELECT 1 FROM escrow_events AS e
                      WHERE e.permit_id = p.permit_id
                        AND e.event_type = 'expired_unused'
                  )
                ORDER BY p.slot_not_before, p.permit_index, p.permit_id
                LIMIT 1
                """,
                (claimed_at, claimed_at, claimed_at, claimed_at),
            ).fetchone()
            if permit is None:
                return None
            cached_bundle = self._decrypt(
                permit["cached_bundle_nonce"],
                permit["cached_bundle"],
                aad=f"escrow-bundle:{permit['bundle_id']}",
            )
            if not isinstance(cached_bundle, dict):
                raise CoordinationError("escrow_cached_bundle_invalid")
            self._assert_client_public_key_binding(cached_bundle)
            changed = connection.execute(
                """
                UPDATE escrow_permits
                SET status = 'CONSUMING', claimed_at = ?, updated_at = ?
                WHERE permit_id = ? AND status = 'READY'
                """,
                (claimed_at, claimed_at, permit["permit_id"]),
            ).rowcount
            if changed != 1:
                raise CoordinationError("escrow_permit_atomic_claim_failed")
            event = self._append_event(
                connection,
                permit,
                event_type="permit_consumed",
                occurred_at=claimed_at,
                provider_transport_called=False,
                provider_message_id=None,
                reason=None,
            )
            secret = self._decrypt(
                permit["secret_nonce"],
                permit["encrypted_secret"],
                aad=f"escrow-permit:{permit['permit_id']}",
            )
            return {
                "bundle_id": permit["bundle_id"],
                "permit_id": permit["permit_id"],
                "status": "CONSUMING",
                "payload": secret["payload"],
                "payload_sha256": permit["payload_sha256"],
                "exact_payload_sha256": permit["exact_payload_sha256"],
                "quota_local_date": permit["quota_local_date"],
                "slot_not_before": permit["slot_not_before"],
                "slot_not_after": permit["slot_not_after"],
                "journal_event_id": event["event_id"],
                "transport_contract": {
                    "send_with_registered_connected_gmail": True,
                    "draft_forbidden": True,
                    "automatic_retry_after_transport_attempt_forbidden": True,
                },
            }

    def _terminal_event(
        self,
        permit_id: str,
        *,
        required_status: str,
        next_status: str,
        event_type: str,
        occurred_at: datetime | str,
        provider_transport_called: bool,
        provider_message_id: str | None,
        reason: str | None,
    ) -> dict[str, Any]:
        permit_id = _identifier(permit_id, label="permit_id")
        with self._immediate() as connection:
            permit = connection.execute(
                "SELECT * FROM escrow_permits WHERE permit_id = ?",
                (permit_id,),
            ).fetchone()
            if permit is None:
                raise CoordinationError("escrow_permit_unknown")
            if permit["status"] != required_status:
                raise CoordinationError(
                    f"escrow_permit_state_{str(permit['status']).lower()}"
                )
            event = self._append_event(
                connection,
                permit,
                event_type=event_type,
                occurred_at=occurred_at,
                provider_transport_called=provider_transport_called,
                provider_message_id=provider_message_id,
                reason=reason,
            )
            connection.execute(
                """
                UPDATE escrow_permits
                SET status = ?, provider_message_id = ?, terminal_reason = ?,
                    updated_at = ?
                WHERE permit_id = ?
                """,
                (
                    next_status,
                    provider_message_id,
                    reason,
                    event["occurred_at"],
                    permit_id,
                ),
            )
            return event

    def record_provider_accepted(
        self,
        permit_id: str,
        provider_message_id: str,
        occurred_at: datetime | str,
    ) -> dict[str, Any]:
        provider_id = _identifier(
            provider_message_id, label="provider_message_id"
        )
        return self._terminal_event(
            permit_id,
            required_status="CONSUMING",
            next_status="PROVIDER_ACCEPTED",
            event_type="provider_accepted",
            occurred_at=occurred_at,
            provider_transport_called=True,
            provider_message_id=provider_id,
            reason=None,
        )

    def record_ambiguous(
        self,
        permit_id: str,
        reason: str,
        occurred_at: datetime | str,
    ) -> dict[str, Any]:
        clean_reason = str(reason or "")
        if not 3 <= len(clean_reason) <= 2_000 or any(
            character in clean_reason for character in ("\r", "\n", "\0")
        ):
            raise CoordinationError("escrow_ambiguous_reason_invalid")
        return self._terminal_event(
            permit_id,
            required_status="CONSUMING",
            next_status="AMBIGUOUS",
            event_type="transport_ambiguous",
            occurred_at=occurred_at,
            provider_transport_called=True,
            provider_message_id=None,
            reason=clean_reason,
        )

    def record_pretransport_abort(
        self,
        permit_id: str,
        reason: str,
        occurred_at: datetime | str,
    ) -> dict[str, Any]:
        clean_reason = str(reason or "")
        if not 10 <= len(clean_reason) <= 2_000 or any(
            character in clean_reason for character in ("\r", "\n", "\0")
        ):
            raise CoordinationError("escrow_pretransport_abort_reason_invalid")
        return self._terminal_event(
            permit_id,
            required_status="CONSUMING",
            next_status="PRETRANSPORT_ABORTED",
            event_type="pretransport_aborted",
            occurred_at=occurred_at,
            provider_transport_called=False,
            provider_message_id=None,
            reason=clean_reason,
        )

    def pending_events(self, bundle_id: str) -> list[dict[str, Any]]:
        events, _errors = self.pending_events_with_errors(bundle_id)
        return events

    def pending_events_with_errors(
        self,
        bundle_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Decrypt each event independently so one corrupt row cannot block later ones."""

        bundle_id = _identifier(bundle_id, label="bundle_id")
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT event_id, permit_id, encrypted_event, event_nonce
                FROM escrow_events
                WHERE bundle_id = ? AND synced_at IS NULL
                ORDER BY created_at, client_sequence, event_id
                """,
                (bundle_id,),
            ).fetchall()
            decoded_events: list[tuple[str, dict[str, Any]]] = []
            errors: list[dict[str, str]] = []
            corrupt_permit_ids: set[str] = set()
            for row in rows:
                permit_id = str(row["permit_id"])
                try:
                    event = self._decrypt(
                        row["event_nonce"],
                        row["encrypted_event"],
                        aad=f"escrow-event:{row['event_id']}",
                    )
                    if not isinstance(event, dict):
                        raise CoordinationError("escrow_event_payload_invalid")
                    decoded_events.append((permit_id, event))
                except CoordinationError:
                    corrupt_permit_ids.add(permit_id)
                    errors.append(
                        {
                            "event_id": str(row["event_id"]),
                            "permit_id": permit_id,
                            "error": "escrow_event_decryption_failed",
                        }
                    )
            events = [
                event
                for permit_id, event in decoded_events
                if permit_id not in corrupt_permit_ids
            ]
            for permit_id, event in decoded_events:
                if permit_id in corrupt_permit_ids:
                    errors.append(
                        {
                            "event_id": str(event.get("event_id") or ""),
                            "permit_id": permit_id,
                            "error": "escrow_event_chain_quarantined",
                        }
                    )
            return events, errors
        finally:
            connection.close()

    def prepare_expired_unused(
        self,
        now: datetime | str,
        *,
        bundle_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Sign expired READY permits before asking central coordination to release them."""

        occurred_at = _utc_text(now, label="escrow_expiry_sweep_at")
        selected_bundle_ids = tuple(
            _identifier(value, label="bundle_id") for value in (bundle_ids or ())
        )
        bundle_filter = ""
        parameters: list[object] = [occurred_at, occurred_at]
        if selected_bundle_ids:
            placeholders = ",".join("?" for _value in selected_bundle_ids)
            bundle_filter = f" AND p.bundle_id IN ({placeholders})"
            parameters.extend(selected_bundle_ids)
        prepared: list[dict[str, Any]] = []
        with self._immediate() as connection:
            permits = connection.execute(
                f"""
                SELECT p.*
                FROM escrow_permits AS p
                JOIN escrow_bundles AS b ON b.bundle_id = p.bundle_id
                WHERE p.status = 'READY'
                  AND (p.slot_not_after <= ? OR b.expires_at <= ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM escrow_events AS e
                      WHERE e.permit_id = p.permit_id
                        AND e.event_type = 'expired_unused'
                  )
                  {bundle_filter}
                ORDER BY p.slot_not_after, p.permit_index, p.permit_id
                """,
                parameters,
            ).fetchall()
            for permit in permits:
                prepared.append(
                    self._append_event(
                        connection,
                        permit,
                        event_type="expired_unused",
                        occurred_at=occurred_at,
                        provider_transport_called=False,
                        provider_message_id=None,
                        reason="local_permit_window_expired_unused",
                    )
                )
        return prepared

    @staticmethod
    def _central_release_ack(
        permit_id: str,
        event_id: str,
        central_ack: dict[str, Any],
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        if isinstance(central_ack, dict):
            candidates.append(central_ack)
            for key in ("events", "results", "permits"):
                values = central_ack.get(key)
                if isinstance(values, list):
                    candidates.extend(item for item in values if isinstance(item, dict))
        for item in candidates:
            if (
                str(item.get("permit_id") or "") != permit_id
                or str(item.get("event_id") or "") != event_id
            ):
                continue
            processing = str(item.get("processing_status") or "applied").lower()
            status = str(
                item.get("permit_status") or item.get("status") or ""
            ).lower()
            if processing == "applied" and status in {
                "aborted",
                "released",
                "expired_unreconciled",
            }:
                return item
        return None

    def release_unused_after_ack(
        self,
        permit_id: str,
        central_ack: dict[str, Any],
        occurred_at: datetime | str,
    ) -> dict[str, Any]:
        permit_id = _identifier(permit_id, label="permit_id")
        acknowledged_at = _utc_text(occurred_at, label="escrow_release_acknowledged_at")
        with self._immediate() as connection:
            permit = connection.execute(
                "SELECT * FROM escrow_permits WHERE permit_id = ?",
                (permit_id,),
            ).fetchone()
            if permit is None:
                raise CoordinationError("escrow_permit_unknown")
            if permit["status"] not in {"READY", "RELEASED"}:
                raise CoordinationError("escrow_unused_release_state_invalid")
            event_row = connection.execute(
                """
                SELECT * FROM escrow_events
                WHERE permit_id = ? AND event_type = 'expired_unused'
                ORDER BY client_sequence DESC LIMIT 1
                """,
                (permit_id,),
            ).fetchone()
            if event_row is None:
                raise CoordinationError("escrow_unused_release_not_prepared")
            if (
                self._central_release_ack(
                    permit_id,
                    str(event_row["event_id"]),
                    central_ack,
                )
                is None
            ):
                raise CoordinationError("escrow_unused_release_not_acknowledged")
            event = self._decrypt(
                event_row["event_nonce"],
                event_row["encrypted_event"],
                aad=f"escrow-event:{event_row['event_id']}",
            )
            connection.execute(
                """
                UPDATE escrow_events
                SET synced_at = COALESCE(synced_at, ?), processing_status = 'applied'
                WHERE event_id = ?
                """,
                (acknowledged_at, event_row["event_id"]),
            )
            connection.execute(
                """
                UPDATE escrow_permits
                SET status = 'RELEASED', terminal_reason = ?, updated_at = ?
                WHERE permit_id = ?
                """,
                (event["reason"], acknowledged_at, permit_id),
            )
            return event

    def apply_sync_acknowledgements(
        self,
        response: dict[str, Any],
        *,
        now: datetime | str,
    ) -> int:
        synced_at = _utc_text(now, label="escrow_synced_at")
        results = response.get("events") or response.get("results")
        if not isinstance(results, list):
            raise CoordinationError("escrow_sync_response_invalid")
        applied = 0
        with self._immediate() as connection:
            for result in results:
                if not isinstance(result, dict):
                    continue
                event_id = str(result.get("event_id") or "")
                processing_status = str(result.get("processing_status") or "")
                if processing_status not in {"applied", "pending_verification"}:
                    continue
                event = connection.execute(
                    "SELECT permit_id FROM escrow_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if event is None:
                    continue
                connection.execute(
                    """
                    UPDATE escrow_events
                    SET synced_at = ?, processing_status = ?
                    WHERE event_id = ? AND synced_at IS NULL
                    """,
                    (synced_at, processing_status, event_id),
                )
                permit_status = str(result.get("permit_status") or "").lower()
                local_status = {
                    "sent": "SENT",
                    "accepted_unverified": "ACCEPTED_UNVERIFIED",
                    "aborted": "RELEASED",
                    "expired_unreconciled": "RELEASED",
                }.get(permit_status)
                if local_status:
                    connection.execute(
                        "UPDATE escrow_permits SET status = ?, updated_at = ? WHERE permit_id = ?",
                        (local_status, synced_at, event["permit_id"]),
                    )
                applied += 1
        return applied

    def bundle_ids_with_pending_events(self) -> list[str]:
        connection = self._connect()
        try:
            return [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT DISTINCT bundle_id FROM escrow_events
                    WHERE synced_at IS NULL ORDER BY bundle_id
                    """
                ).fetchall()
            ]
        finally:
            connection.close()


def _lease_token_path(value: str | None) -> Path:
    candidate = value or os.environ.get(LEASE_TOKEN_FILE_ENV)
    if not candidate:
        raise CoordinationError("lease_token_file_required")
    path = Path(candidate)
    if not path.is_absolute():
        raise CoordinationError("lease_token_path_must_be_absolute")
    return path


def _remove_terminal_secret(path: Path, *, label: str) -> None:
    path = _secure_token_path(path, label=label)
    try:
        path.unlink()
    except OSError as exc:
        raise CoordinationError(f"{label}_file_cleanup_failed") from exc


def _request_id_path(value: str | None) -> Path:
    candidate = value or os.environ.get(REQUEST_ID_FILE_ENV)
    if not candidate:
        raise CoordinationError("scheduled_gmail_request_id_file_required")
    path = Path(candidate)
    if not path.is_absolute():
        raise CoordinationError("scheduled_gmail_request_id_path_must_be_absolute")
    return path


def _read_or_create_request_id(path: Path) -> str:
    if path.exists():
        return _request_identifier(
            _read_raw_token(path, label="scheduled_gmail_request_id"),
        )
    request_id = f"SGR-{secrets.token_urlsafe(24)}"
    _write_raw_token(path, request_id)
    return _request_identifier(request_id)


def _client_token(value: str | None = None) -> str:
    raw_path = value or os.environ.get(CLIENT_TOKEN_FILE_ENV)
    if not raw_path:
        raise CoordinationError("scheduled_gmail_client_token_file_env_missing")
    return _read_raw_token(Path(raw_path), label="scheduled_gmail_client_token")


def _escrow_cache_path(value: str | None) -> Path:
    raw_path = value or os.environ.get(ESCROW_CACHE_DB_ENV)
    if not raw_path:
        raise CoordinationError("escrow_cache_db_required")
    path = Path(raw_path)
    if not path.is_absolute():
        raise CoordinationError("escrow_cache_db_path_must_be_absolute")
    return path


def _escrow_identity(args: argparse.Namespace) -> tuple[str, str, tuple[str, ...]]:
    client_id = str(
        getattr(args, "escrow_client_id", None)
        or os.environ.get(ESCROW_CLIENT_ID_ENV)
        or ""
    )
    sender_email = str(
        getattr(args, "escrow_sender_email", None)
        or os.environ.get(ESCROW_SENDER_EMAIL_ENV)
        or ""
    )
    raw_motors = str(
        getattr(args, "escrow_motor_keys", None)
        or os.environ.get(ESCROW_MOTOR_KEYS_ENV)
        or ""
    )
    motor_keys = tuple(
        value.strip() for value in raw_motors.split(",") if value.strip()
    )
    return client_id, sender_email, motor_keys


def _offline_journal(args: argparse.Namespace) -> OfflineEscrowJournal:
    _key_path, encryption_key = _cache_key(
        getattr(args, "escrow_cache_key_file", None)
    )
    client_id, sender_email, motor_keys = _escrow_identity(args)
    client_signing_key_file = (
        getattr(args, "escrow_client_signing_key_file", None)
        or os.environ.get(ESCROW_CLIENT_SIGNING_KEY_FILE_ENV)
    )
    if not client_signing_key_file:
        raise CoordinationError("escrow_client_signing_key_file_required")
    return OfflineEscrowJournal(
        _escrow_cache_path(getattr(args, "escrow_cache_db", None)),
        encryption_key,
        client_id,
        sender_email,
        motor_keys,
        client_signing_key_file=client_signing_key_file,
        server_public_key_file=getattr(args, "escrow_server_public_key_file", None),
    )


def _command_time(value: str | None, *, label: str) -> datetime:
    return _utc(value, label=label) if value else datetime.now(UTC)


def _escrow_candidate(value: str) -> dict[str, str]:
    outreach_id, separator, payload_sha256 = str(value or "").partition("=")
    if not separator:
        raise CoordinationError("escrow_candidate_invalid")
    outreach_id = _identifier(outreach_id, label="outreach_id")
    if not SHA256_RE.fullmatch(payload_sha256):
        raise CoordinationError("expected_payload_sha256_invalid")
    return {
        "outreach_id": outreach_id,
        "expected_payload_sha256": payload_sha256,
    }


def _coordination_outage(
    *,
    base_url: str,
    bearer_token: str,
) -> CoordinationError:
    try:
        _request(
            method="GET",
            url=f"{base_url}/readiness",
            bearer_token=bearer_token,
            payload=None,
            expected_statuses={200},
        )
    except CoordinationError as exc:
        if not _offline_fallback_allowed(exc):
            raise
        return exc
    raise CoordinationError("offline_fallback_refused_coordination_available")


def _offline_next_with_wait(
    *,
    journal: OfflineEscrowJournal,
    base_url: str,
    bearer_token: str,
    wait_seconds: int,
    now_override: str | None,
) -> dict[str, Any]:
    if not 0 <= wait_seconds <= MAX_OFFLINE_WAIT_SECONDS:
        raise CoordinationError("offline_wait_seconds_invalid")
    started_monotonic = _monotonic()
    synthetic_waited = 0.0
    initial_time = (
        _utc(now_override, label="escrow_claimed_at")
        if now_override
        else _now_utc()
    )

    def current_time() -> datetime:
        elapsed = max(_monotonic() - started_monotonic, synthetic_waited)
        return initial_time + timedelta(seconds=max(0.0, elapsed))

    coordination_error = _coordination_outage(
        base_url=base_url,
        bearer_token=bearer_token,
    )
    while True:
        now = current_time()
        permit = journal.claim_next(now, coordination_error)
        if permit is not None:
            return permit
        schedule = journal.next_ready_schedule(now)
        if schedule is None:
            return {"status": "NO_READY_PERMIT"}
        elapsed = max(_monotonic() - started_monotonic, synthetic_waited)
        remaining_budget = max(0.0, wait_seconds - elapsed)
        next_due = _utc(schedule["next_due_at"], label="escrow_next_due_at")
        seconds_until_due = max(0.0, (next_due - now).total_seconds())
        if wait_seconds == 0 or seconds_until_due > remaining_budget:
            return schedule
        sleep_for = min(seconds_until_due, remaining_budget, 60.0)
        if sleep_for <= 0:
            return schedule
        _sleep_seconds(sleep_for)
        synthetic_waited += sleep_for
        # Refresh the outage proof during a long wait. For the final short hop,
        # retain the last successful outage proof so a readiness timeout cannot
        # make the task miss its already-reserved narrow permit window.
        if sleep_for + 0.001 < seconds_until_due:
            coordination_error = _coordination_outage(
                base_url=base_url,
                bearer_token=bearer_token,
            )


def _run(args: argparse.Namespace) -> dict[str, Any]:
    base_url = _validated_api_base_url(args.api_base_url)
    network_commands = {
        "readiness",
        "lease",
        "finalize",
        "abort",
        "status",
        "prefetch",
        "offline-next",
        "sync",
    }
    bearer_token = (
        _client_token(getattr(args, "client_token_file", None))
        if args.command in network_commands
        else ""
    )
    if args.command == "readiness":
        return _sanitize(
            _request(
                method="GET",
                url=f"{base_url}/readiness",
                bearer_token=bearer_token,
                payload=None,
                expected_statuses={200},
            ),
            secrets=(bearer_token,),
        )
    if args.command == "lease":
        request_id_path = _request_id_path(getattr(args, "request_id_file", None))
        request_id = _read_or_create_request_id(request_id_path)
        request_payload: dict[str, object] = {"request_id": request_id}
        if args.outreach_id:
            request_payload["outreach_id"] = _identifier(
                args.outreach_id,
                label="outreach_id",
            )
        if args.expected_payload_sha256:
            if not SHA256_RE.fullmatch(args.expected_payload_sha256):
                raise CoordinationError("expected_payload_sha256_invalid")
            request_payload["expected_payload_sha256"] = args.expected_payload_sha256
        response = _request(
            method="POST",
            url=f"{base_url}/lease",
            bearer_token=bearer_token,
            payload=request_payload,
            expected_statuses={200, 201},
        )
        lease_token = str(response.get("lease_token") or "")
        _write_raw_token(_lease_token_path(args.lease_token_file), lease_token)
        public_response = dict(response)
        public_response.pop("lease_token", None)
        public_response["lease_file_written"] = True
        return _sanitize(
            public_response,
            secrets=(bearer_token, lease_token, request_id),
        )

    if args.command == "prefetch":
        journal = _offline_journal(args)
        request_id_path = _request_id_path(getattr(args, "request_id_file", None))
        request_id = _read_or_create_request_id(request_id_path)
        quota_dates: list[str] = []
        for value in args.quota_local_date:
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError as exc:
                raise CoordinationError("escrow_quota_local_date_invalid") from exc
            quota_dates.append(parsed_date.isoformat())
        if quota_dates != sorted(set(quota_dates)):
            raise CoordinationError("escrow_quota_local_dates_not_unique_sorted")
        candidates = [_escrow_candidate(value) for value in args.candidate]
        response = _request(
            method="POST",
            url=f"{base_url}/escrow/bundles",
            bearer_token=bearer_token,
            payload={
                "request_id": request_id,
                "desired_permit_count": int(args.desired_permit_count),
                "quota_local_dates": quota_dates,
                "candidates": candidates,
            },
            expected_statuses={200, 201},
        )
        imported = journal.import_bundle(response, datetime.now(UTC))
        return {
            "bundle_id": str(response.get("bundle_id") or ""),
            "status": str(response.get("status") or ""),
            "permit_count": int(response.get("permit_count") or len(response.get("permits") or [])),
            "permits_imported": imported,
            "journal_mode": journal.journal_mode(),
        }

    if args.command == "offline-next":
        journal = _offline_journal(args)
        return _offline_next_with_wait(
            journal=journal,
            base_url=base_url,
            bearer_token=bearer_token,
            wait_seconds=int(getattr(args, "wait_seconds", 0) or 0),
            now_override=getattr(args, "now", None),
        )

    if args.command == "report-accepted":
        journal = _offline_journal(args)
        event = journal.record_provider_accepted(
            args.permit_id,
            args.provider_message_id,
            _command_time(
                getattr(args, "occurred_at", None), label="escrow_event_occurred_at"
            ),
        )
        return {
            "permit_id": args.permit_id,
            "status": "PROVIDER_ACCEPTED",
            "event_id": event["event_id"],
            "automatic_retry_forbidden": True,
        }

    if args.command == "report-ambiguous":
        journal = _offline_journal(args)
        event = journal.record_ambiguous(
            args.permit_id,
            args.reason,
            _command_time(
                getattr(args, "occurred_at", None), label="escrow_event_occurred_at"
            ),
        )
        return {
            "permit_id": args.permit_id,
            "status": "AMBIGUOUS",
            "event_id": event["event_id"],
            "automatic_retry_forbidden": True,
        }

    if args.command == "report-pretransport-abort":
        journal = _offline_journal(args)
        event = journal.record_pretransport_abort(
            args.permit_id,
            args.reason,
            _command_time(
                getattr(args, "occurred_at", None), label="escrow_event_occurred_at"
            ),
        )
        return {
            "permit_id": args.permit_id,
            "status": "PRETRANSPORT_ABORTED",
            "event_id": event["event_id"],
            "provider_transport_called": False,
        }

    if args.command == "sync":
        journal = _offline_journal(args)
        requested_bundle_ids = [
            _identifier(value, label="bundle_id") for value in (args.bundle_id or [])
        ]
        if len(requested_bundle_ids) != len(set(requested_bundle_ids)):
            raise CoordinationError("escrow_sync_bundle_ids_not_unique")
        sync_now = datetime.now(UTC)
        prepared_expirations = journal.prepare_expired_unused(
            sync_now,
            bundle_ids=requested_bundle_ids or None,
        )
        bundle_ids = list(
            requested_bundle_ids or journal.bundle_ids_with_pending_events()
        )
        summaries: list[dict[str, Any]] = []
        for bundle_id in bundle_ids:
            bundle_id = _identifier(bundle_id, label="bundle_id")
            events, local_event_errors = journal.pending_events_with_errors(bundle_id)
            if not events:
                summaries.append(
                    {
                        "bundle_id": bundle_id,
                        "events_submitted": 0,
                        "events_applied": 0,
                        "local_events_rejected": local_event_errors,
                    }
                )
                continue
            request_id = f"SGS-{secrets.token_urlsafe(24)}"
            permit_tokens = tuple(
                str(event.get("permit_token") or "") for event in events
            )
            response = _request(
                method="POST",
                url=(
                    f"{base_url}/escrow/bundles/"
                    f"{urllib.parse.quote(bundle_id, safe='')}/sync"
                ),
                bearer_token=bearer_token,
                payload={
                    "request_id": request_id,
                    "bundle_id": bundle_id,
                    "events": events,
                },
                expected_statuses={200, 202},
                known_secrets=permit_tokens,
            )
            applied = journal.apply_sync_acknowledgements(
                response,
                now=datetime.now(UTC),
            )
            summaries.append(
                {
                    "bundle_id": bundle_id,
                    "events_submitted": len(events),
                    "events_applied": applied,
                    "local_events_rejected": local_event_errors,
                    "status": str(response.get("status") or ""),
                }
            )
        return {
            "bundles": summaries,
            "expired_unused_prepared": len(prepared_expirations),
        }

    lease_id = _identifier(args.lease_id, label="lease_id")
    lease_url = f"{base_url}/{urllib.parse.quote(lease_id, safe='')}"
    if args.command == "status":
        return _sanitize(
            _request(
                method="GET",
                url=lease_url,
                bearer_token=bearer_token,
                payload=None,
                expected_statuses={200},
            ),
            secrets=(bearer_token,),
        )

    lease_token = _read_raw_token(
        _lease_token_path(args.lease_token_file),
        label="lease_token",
    )
    lease_token_path = _lease_token_path(args.lease_token_file)
    request_id_path = _request_id_path(getattr(args, "request_id_file", None))
    if args.command == "finalize":
        provider_message_id = _identifier(
            args.provider_message_id,
            label="provider_message_id",
        )
        response = _request(
                method="POST",
                url=f"{lease_url}/finalize",
                bearer_token=bearer_token,
                payload={
                    "lease_token": lease_token,
                    "provider_message_id": provider_message_id,
                },
                expected_statuses={200, 202},
                known_secrets=(lease_token,),
            )
        if str(response.get("status") or "") == "sent":
            _remove_terminal_secret(lease_token_path, label="lease_token")
            _remove_terminal_secret(
                request_id_path,
                label="scheduled_gmail_request_id",
            )
        return _sanitize(
            response,
            secrets=(bearer_token, lease_token),
        )
    if args.command == "abort":
        reason = str(args.reason or "")
        if (
            len(reason) < 10
            or len(reason) > 2_000
            or any(character in reason for character in ("\r", "\n", "\0"))
        ):
            raise CoordinationError("abort_reason_invalid")
        response = _request(
                method="POST",
                url=f"{lease_url}/abort",
                bearer_token=bearer_token,
                payload={
                    "lease_token": lease_token,
                    "reason": reason,
                    "provider_transport_called": False,
                },
                expected_statuses={200},
                known_secrets=(lease_token,),
            )
        if str(response.get("status") or "") == "aborted":
            _remove_terminal_secret(lease_token_path, label="lease_token")
            _remove_terminal_secret(
                request_id_path,
                label="scheduled_gmail_request_id",
            )
        return _sanitize(
            response,
            secrets=(bearer_token, lease_token),
        )
    raise CoordinationError("unknown_command")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coordinate a scheduled Gmail sender with the local Imperial outbox.",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="Loopback coordination API base URL.",
    )
    parser.add_argument(
        "--client-token-file",
        help=(
            "Registered client bearer-token file; defaults to "
            f"{CLIENT_TOKEN_FILE_ENV}."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "readiness",
        help="Read the mutation-free scheduled Gmail coordination preflight.",
    )

    def add_escrow_journal_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--escrow-cache-db")
        command.add_argument("--escrow-cache-key-file")
        command.add_argument("--escrow-client-id")
        command.add_argument("--escrow-sender-email")
        command.add_argument(
            "--escrow-motor-keys",
            help="Comma-separated registered motor keys.",
        )
        command.add_argument("--escrow-client-signing-key-file")
        command.add_argument("--escrow-server-public-key-file")

    lease = commands.add_parser("lease", help="Reserve and fetch one exact outbound payload.")
    lease.add_argument("--outreach-id")
    lease.add_argument("--expected-payload-sha256")
    lease.add_argument("--lease-token-file")
    lease.add_argument("--request-id-file")

    finalize = commands.add_parser(
        "finalize",
        help="Finalize a Gmail-accepted delivery by provider message ID.",
    )
    finalize.add_argument("lease_id")
    finalize.add_argument("provider_message_id")
    finalize.add_argument("--lease-token-file")
    finalize.add_argument("--request-id-file")

    abort = commands.add_parser(
        "abort",
        help="Abort a lease only before the Gmail transport was called.",
    )
    abort.add_argument("lease_id")
    abort.add_argument("--reason", required=True)
    abort.add_argument("--lease-token-file")
    abort.add_argument("--request-id-file")

    status = commands.add_parser("status", help="Read non-secret lease status metadata.")
    status.add_argument("lease_id")

    prefetch = commands.add_parser(
        "prefetch",
        help="Reserve, verify, and encrypt a multi-day offline escrow bundle.",
    )
    add_escrow_journal_arguments(prefetch)
    prefetch.add_argument("--request-id-file")
    prefetch.add_argument("--desired-permit-count", type=int, required=True)
    prefetch.add_argument(
        "--quota-local-date",
        action="append",
        required=True,
        help="Europe/Budapest quota date; repeat for a multi-day bundle.",
    )
    prefetch.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="OUTREACH_ID=PAYLOAD_SHA256",
    )

    offline_next = commands.add_parser(
        "offline-next",
        help="Claim one cached permit only after a real coordination network outage.",
    )
    add_escrow_journal_arguments(offline_next)
    offline_next.add_argument("--now")
    offline_next.add_argument(
        "--wait-seconds",
        type=_bounded_wait_seconds,
        default=0,
        help=(
            "Wait at most this many seconds for the next reserved slot "
            f"(0-{MAX_OFFLINE_WAIT_SECONDS})."
        ),
    )

    report_accepted = commands.add_parser(
        "report-accepted",
        help="Journal a Gmail provider acceptance; this permanently forbids resend.",
    )
    add_escrow_journal_arguments(report_accepted)
    report_accepted.add_argument("permit_id")
    report_accepted.add_argument("provider_message_id")
    report_accepted.add_argument("--occurred-at")

    report_ambiguous = commands.add_parser(
        "report-ambiguous",
        help="Journal an ambiguous Gmail transport; this permanently forbids resend.",
    )
    add_escrow_journal_arguments(report_ambiguous)
    report_ambiguous.add_argument("permit_id")
    report_ambiguous.add_argument("--reason", required=True)
    report_ambiguous.add_argument("--occurred-at")

    report_abort = commands.add_parser(
        "report-pretransport-abort",
        help="Journal an abort only when Gmail transport was provably never called.",
    )
    add_escrow_journal_arguments(report_abort)
    report_abort.add_argument("permit_id")
    report_abort.add_argument("--reason", required=True)
    report_abort.add_argument("--occurred-at")

    sync = commands.add_parser(
        "sync",
        help="Reconcile encrypted offline events after coordination recovers.",
    )
    add_escrow_journal_arguments(sync)
    sync.add_argument("--bundle-id", action="append")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except CoordinationError as exc:
        error: dict[str, object] = {"ok": False, "error": str(exc)}
        if exc.detail is not None:
            error["detail"] = exc.detail
        print(json.dumps(error, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
