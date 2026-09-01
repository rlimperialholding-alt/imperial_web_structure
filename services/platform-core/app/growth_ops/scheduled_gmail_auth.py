from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

SCHEDULED_GMAIL_ENABLED_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_ENABLED"
SCHEDULED_GMAIL_CLIENTS_FILE_ENV = "GROWTH_OPS_SCHEDULED_GMAIL_CLIENTS_FILE"
SCHEDULED_GMAIL_PERMISSIONS = frozenset(
    {"lease", "finalize", "abort", "read", "escrow_prefetch", "escrow_sync"}
)
SCHEDULED_GMAIL_MOTOR_KEYS = frozenset({"construction", "distress", "ivs"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,119}$")
_EMAIL_RE = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

ScheduledGmailPermission = Literal[
    "lease",
    "finalize",
    "abort",
    "read",
    "escrow_prefetch",
    "escrow_sync",
]


class ScheduledGmailAuthError(ValueError):
    pass


class ScheduledGmailAuthorizationError(ScheduledGmailAuthError):
    pass


@dataclass(frozen=True)
class ScheduledGmailClientPrincipal:
    client_id: str
    permissions: frozenset[str]
    sender_emails: frozenset[str]
    motor_keys: frozenset[str]
    expires_at: datetime
    registry_version: str
    registry_sha256: str
    offline_escrow_enabled: bool = False
    client_key_id: str | None = None
    offline_public_key_pem: str | None = None
    offline_public_key_sha256: str | None = None
    offline_max_permits: int = 0
    offline_max_horizon_days: int = 0

    def assert_scope(
        self,
        *,
        permission: ScheduledGmailPermission,
        sender_email: str | None = None,
        motor_key: str | None = None,
    ) -> None:
        if permission not in self.permissions:
            raise ScheduledGmailAuthorizationError(
                "scheduled_gmail_client_permission_denied"
            )
        if sender_email is not None and sender_email.strip().casefold() not in self.sender_emails:
            raise ScheduledGmailAuthorizationError(
                "scheduled_gmail_client_sender_scope_denied"
            )
        if motor_key is not None and motor_key.strip().casefold() not in self.motor_keys:
            raise ScheduledGmailAuthorizationError(
                "scheduled_gmail_client_motor_scope_denied"
            )

    def assert_offline_escrow_scope(
        self,
        *,
        permit_count: int,
        horizon_days: int,
        client_key_id: str | None = None,
    ) -> None:
        if (
            not self.offline_escrow_enabled
            or self.client_key_id is None
            or self.offline_public_key_pem is None
            or self.offline_public_key_sha256 is None
        ):
            raise ScheduledGmailAuthorizationError(
                "scheduled_gmail_client_offline_escrow_denied"
            )
        if not 1 <= permit_count <= self.offline_max_permits:
            raise ScheduledGmailAuthorizationError(
                "scheduled_gmail_client_offline_permit_scope_denied"
            )
        if not 1 <= horizon_days <= self.offline_max_horizon_days:
            raise ScheduledGmailAuthorizationError(
                "scheduled_gmail_client_offline_horizon_scope_denied"
            )
        if client_key_id is not None and not hmac.compare_digest(
            self.client_key_id,
            client_key_id,
        ):
            raise ScheduledGmailAuthorizationError(
                "scheduled_gmail_client_offline_key_scope_denied"
            )


@dataclass(frozen=True)
class _ScheduledGmailClientRecord:
    principal: ScheduledGmailClientPrincipal
    token_sha256: str
    enabled: bool


def scheduled_gmail_bearer_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse_expiry(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_expiry_invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise ScheduledGmailAuthError("scheduled_gmail_client_expiry_invalid")
    parsed = parsed.astimezone(UTC)
    if parsed.year > 9998:
        raise ScheduledGmailAuthError("scheduled_gmail_client_expiry_invalid")
    return parsed


def _strict_string_set(
    value: object,
    *,
    field: str,
    allowed: frozenset[str] | None = None,
) -> frozenset[str]:
    if not isinstance(value, list) or not value or len(value) > 50:
        raise ScheduledGmailAuthError(f"scheduled_gmail_client_{field}_invalid")
    normalized = [str(item).strip().casefold() for item in value]
    if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
        raise ScheduledGmailAuthError(f"scheduled_gmail_client_{field}_invalid")
    result = frozenset(normalized)
    if allowed is not None and not result.issubset(allowed):
        raise ScheduledGmailAuthError(f"scheduled_gmail_client_{field}_invalid")
    return result


def _offline_positive_int(value: object, *, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ScheduledGmailAuthError(f"scheduled_gmail_client_{field}_invalid")
    return value


def _offline_public_key(
    path_value: object,
    expected_sha256_value: object,
) -> tuple[str, str]:
    expected_sha256 = str(expected_sha256_value or "").strip().casefold()
    if not _SHA256_RE.fullmatch(expected_sha256):
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_offline_public_key_sha256_invalid"
        )
    try:
        supplied = Path(str(path_value or ""))
        if not supplied.is_absolute():
            raise ScheduledGmailAuthError(
                "scheduled_gmail_client_offline_public_key_path_invalid"
            )
        link_metadata = supplied.lstat()
        if stat.S_ISLNK(link_metadata.st_mode):
            raise ScheduledGmailAuthError(
                "scheduled_gmail_client_offline_public_key_permissions_invalid"
            )
        path = supplied.resolve(strict=True)
        if not path.is_file():
            raise ScheduledGmailAuthError(
                "scheduled_gmail_client_offline_public_key_missing"
            )
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode)
        raw_bytes = path.read_bytes()
    except ScheduledGmailAuthError:
        raise
    except OSError as exc:
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_offline_public_key_unreadable"
        ) from exc
    if os.name != "nt" and (
        metadata.st_uid != os.geteuid() or bool(mode & 0o022)
    ):
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_offline_public_key_permissions_invalid"
        )
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_offline_public_key_hash_mismatch"
        )
    if not 80 <= len(raw_bytes) <= 4096 or b"PRIVATE KEY" in raw_bytes:
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_offline_public_key_invalid"
        )
    try:
        pem = raw_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_offline_public_key_invalid"
        ) from exc
    pem_lines = pem.splitlines()
    if not (
        pem_lines
        and pem_lines[0] == "-----BEGIN PUBLIC KEY-----"
        and pem_lines[-1] == "-----END PUBLIC KEY-----"
    ):
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_offline_public_key_invalid"
        )
    return pem, actual_sha256


def _registry_path() -> Path:
    configured = os.getenv(SCHEDULED_GMAIL_CLIENTS_FILE_ENV, "").strip()
    if not configured:
        raise ScheduledGmailAuthError("scheduled_gmail_client_registry_missing")
    try:
        supplied = Path(configured).expanduser()
        if not supplied.is_absolute():
            raise ScheduledGmailAuthError(
                "scheduled_gmail_client_registry_path_invalid"
            )
        link_metadata = supplied.lstat()
        if stat.S_ISLNK(link_metadata.st_mode):
            raise ScheduledGmailAuthError(
                "scheduled_gmail_client_registry_permissions_invalid"
            )
        path = supplied.resolve(strict=True)
        if not path.is_file():
            raise ScheduledGmailAuthError("scheduled_gmail_client_registry_missing")
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode)
    except OSError as exc:
        raise ScheduledGmailAuthError("scheduled_gmail_client_registry_missing") from exc
    if os.name != "nt" and (
        mode != 0o600 or metadata.st_uid != os.geteuid()
    ):
        raise ScheduledGmailAuthError(
            "scheduled_gmail_client_registry_permissions_invalid"
        )
    return path


def _load_registry() -> tuple[list[_ScheduledGmailClientRecord], str, str]:
    enabled = os.getenv(SCHEDULED_GMAIL_ENABLED_ENV, "false").strip().casefold()
    if enabled not in {"true", "false"}:
        raise ScheduledGmailAuthError("scheduled_gmail_enabled_flag_invalid")
    if enabled != "true":
        raise ScheduledGmailAuthError("scheduled_gmail_disabled")

    path = _registry_path()
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ScheduledGmailAuthError("scheduled_gmail_client_registry_unreadable") from exc
    if not isinstance(raw, dict):
        raise ScheduledGmailAuthError("scheduled_gmail_client_registry_invalid")
    version = str(raw.get("version") or "").strip()
    clients = raw.get("clients")
    if not version or len(version) > 120 or not isinstance(clients, list) or not clients:
        raise ScheduledGmailAuthError("scheduled_gmail_client_registry_invalid")
    registry_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    records: list[_ScheduledGmailClientRecord] = []
    client_ids: set[str] = set()
    token_hashes: set[str] = set()
    client_key_ids: set[str] = set()
    offline_public_key_hashes: set[str] = set()
    for value in clients:
        if not isinstance(value, dict):
            raise ScheduledGmailAuthError("scheduled_gmail_client_registry_invalid")
        if any("private_key" in str(key).casefold() for key in value):
            raise ScheduledGmailAuthError(
                "scheduled_gmail_client_private_key_forbidden"
            )
        client_id = str(value.get("client_id") or "").strip().casefold()
        token_sha256 = str(value.get("token_sha256") or "").strip().casefold()
        client_enabled = value.get("enabled")
        if (
            not _CLIENT_ID_RE.fullmatch(client_id)
            or not _SHA256_RE.fullmatch(token_sha256)
            or not isinstance(client_enabled, bool)
            or client_id in client_ids
            or token_sha256 in token_hashes
        ):
            raise ScheduledGmailAuthError("scheduled_gmail_client_registry_invalid")
        permissions = _strict_string_set(
            value.get("permissions"),
            field="permissions",
            allowed=SCHEDULED_GMAIL_PERMISSIONS,
        )
        sender_emails = _strict_string_set(
            value.get("sender_emails"),
            field="sender_emails",
        )
        if any(not _EMAIL_RE.fullmatch(email) for email in sender_emails):
            raise ScheduledGmailAuthError("scheduled_gmail_client_sender_emails_invalid")
        motor_keys = _strict_string_set(
            value.get("motor_keys"),
            field="motor_keys",
            allowed=SCHEDULED_GMAIL_MOTOR_KEYS,
        )
        expires_at = _parse_expiry(value.get("expires_at"))
        offline_escrow_enabled = value.get("offline_escrow_enabled", False)
        if not isinstance(offline_escrow_enabled, bool):
            raise ScheduledGmailAuthError(
                "scheduled_gmail_client_offline_escrow_enabled_invalid"
            )
        client_key_id_raw = value.get("client_key_id")
        offline_public_key_file_raw = value.get("offline_public_key_file")
        offline_public_key_sha256_raw = value.get("offline_public_key_sha256")
        offline_max_permits_raw = value.get("offline_max_permits")
        offline_max_horizon_days_raw = value.get("offline_max_horizon_days")
        if offline_escrow_enabled:
            client_key_id = str(client_key_id_raw or "").strip().casefold()
            if not _CLIENT_ID_RE.fullmatch(client_key_id):
                raise ScheduledGmailAuthError(
                    "scheduled_gmail_client_client_key_id_invalid"
                )
            offline_public_key_pem, offline_public_key_sha256 = _offline_public_key(
                offline_public_key_file_raw,
                offline_public_key_sha256_raw,
            )
            if (
                client_key_id in client_key_ids
                or offline_public_key_sha256 in offline_public_key_hashes
            ):
                raise ScheduledGmailAuthError(
                    "scheduled_gmail_client_offline_key_duplicate"
                )
            offline_max_permits = _offline_positive_int(
                offline_max_permits_raw,
                field="offline_max_permits",
                maximum=2000,
            )
            offline_max_horizon_days = _offline_positive_int(
                offline_max_horizon_days_raw,
                field="offline_max_horizon_days",
                maximum=31,
            )
            if not {"escrow_prefetch", "escrow_sync"}.issubset(permissions):
                raise ScheduledGmailAuthError(
                    "scheduled_gmail_client_offline_permissions_invalid"
                )
        else:
            if any(
                item is not None and item != 0 and item != ""
                for item in (
                    client_key_id_raw,
                    offline_public_key_file_raw,
                    offline_public_key_sha256_raw,
                    offline_max_permits_raw,
                    offline_max_horizon_days_raw,
                )
            ):
                raise ScheduledGmailAuthError(
                    "scheduled_gmail_client_offline_configuration_invalid"
                )
            client_key_id = None
            offline_public_key_pem = None
            offline_public_key_sha256 = None
            offline_max_permits = 0
            offline_max_horizon_days = 0
        records.append(
            _ScheduledGmailClientRecord(
                principal=ScheduledGmailClientPrincipal(
                    client_id=client_id,
                    permissions=permissions,
                    sender_emails=sender_emails,
                    motor_keys=motor_keys,
                    expires_at=expires_at,
                    registry_version=version,
                    registry_sha256=registry_sha256,
                    offline_escrow_enabled=offline_escrow_enabled,
                    client_key_id=client_key_id,
                    offline_public_key_pem=offline_public_key_pem,
                    offline_public_key_sha256=offline_public_key_sha256,
                    offline_max_permits=offline_max_permits,
                    offline_max_horizon_days=offline_max_horizon_days,
                ),
                token_sha256=token_sha256,
                enabled=client_enabled,
            )
        )
        client_ids.add(client_id)
        token_hashes.add(token_sha256)
        if client_key_id is not None and offline_public_key_sha256 is not None:
            client_key_ids.add(client_key_id)
            offline_public_key_hashes.add(offline_public_key_sha256)
    return records, version, registry_sha256


def _bearer_token(authorization: str | None) -> str:
    value = str(authorization or "")
    scheme, separator, token = value.partition(" ")
    if (
        separator != " "
        or scheme.casefold() != "bearer"
        or not 32 <= len(token) <= 4096
        or token.strip() != token
        or any(character.isspace() for character in token)
    ):
        raise ScheduledGmailAuthError("scheduled_gmail_client_authentication_failed")
    return token


def authenticate_scheduled_gmail_client(
    authorization: str | None,
    *,
    required_permission: ScheduledGmailPermission,
    sender_email: str | None = None,
    motor_key: str | None = None,
    now: datetime | None = None,
) -> ScheduledGmailClientPrincipal:
    token_sha256 = scheduled_gmail_bearer_sha256(_bearer_token(authorization))
    records, _version, _registry_sha256 = _load_registry()
    matched: _ScheduledGmailClientRecord | None = None
    for record in records:
        if hmac.compare_digest(record.token_sha256, token_sha256):
            matched = record
    current = _aware(now or datetime.now(UTC)).astimezone(UTC)
    if matched is None or not matched.enabled or matched.principal.expires_at <= current:
        raise ScheduledGmailAuthError("scheduled_gmail_client_authentication_failed")
    matched.principal.assert_scope(
        permission=required_permission,
        sender_email=sender_email,
        motor_key=motor_key,
    )
    return matched.principal
