from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from ..config import Settings, settings
from .safe_http import AddressResolver, SafeHttpClient, SafeHttpError

ADMIN_ROLES = frozenset({"owner", "managing-director", "platform-admin"})
ALL_SCOPES = frozenset(
    {"digital-pm:read", "digital-pm:write", "digital-pm:approve", "digital-pm:audit"}
)


class DpmGatewayError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DpmIdentity:
    subject: str
    role: str
    scopes: frozenset[str]
    project_ids: frozenset[str]


@dataclass(frozen=True)
class DpmUserContext:
    identity: DpmIdentity
    agent_ids: frozenset[str]
    admin: bool


class DpmGateway:
    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: AddressResolver | None = None,
        timeout: float = 8.0,
    ):
        self.settings = app_settings
        # A transport/resolver csak szintetikus, hálózatmentes tesztekben cserélhető.
        self._transport = transport
        self._resolver = resolver
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        token_source = bool(
            (self.settings.itep_api_base_url and self.settings.itep_identity_shared_secret)
            or self.settings.dpm_auth_hs256_secret
        )
        return bool(self.settings.dpm_api_base_url and token_source)

    def _client(self, base_url: str) -> SafeHttpClient:
        return SafeHttpClient(
            base_url.rstrip("/"),
            transport=self._transport,
            resolver=self._resolver,
            timeout=self._timeout,
        )

    def _token(self, identity: DpmIdentity) -> str:
        if not self.configured:
            raise DpmGatewayError(503, "A Digital Project Managers kapcsolat nincs konfigurálva.")
        if self.settings.itep_api_base_url and self.settings.itep_identity_shared_secret:
            return self._exchange_itep_token(identity)
        issued_at = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": identity.subject,
                "iss": self.settings.dpm_auth_issuer,
                "aud": self.settings.dpm_auth_audience,
                "iat": issued_at,
                "exp": issued_at + timedelta(minutes=2),
                "scope": " ".join(sorted(identity.scopes)),
                "projects": sorted(identity.project_ids),
                "role": identity.role,
            },
            self.settings.dpm_auth_hs256_secret,
            algorithm="HS256",
        )

    def _exchange_itep_token(self, identity: DpmIdentity) -> str:
        try:
            client = self._client(self.settings.itep_api_base_url)
        except SafeHttpError as error:
            raise DpmGatewayError(
                502, "Az ITEP DPM tokenváltás célja nem biztonságos."
            ) from error
        with client:
            try:
                response = client.post(
                    "/v1/auth/service-tokens/digital-project-managers",
                    json={},
                    headers={
                        **self._itep_identity_headers(identity),
                        "Accept": "application/json",
                    },
                )
                # A válasz statusát, törzsét és JSON-feldolgozását még a kliens
                # context lezárása előtt puffereljük: lezárt kapcsolat után
                # streaming/lazy választörzs már nem olvasható biztonságosan.
                status_code = response.status_code
                try:
                    payload: Any = response.json()
                except ValueError:
                    payload = None
            except SafeHttpError as error:
                raise DpmGatewayError(
                    502, "Az ITEP DPM tokenváltás célja nem biztonságos."
                ) from error
            except httpx.HTTPError as error:
                raise DpmGatewayError(
                    503, "Az ITEP DPM tokenváltás nem érhető el."
                ) from error
        if status_code != 200:
            raise DpmGatewayError(
                status_code, "Az ITEP nem adott ki DPM hozzáférési tokent."
            )
        if payload is None:
            raise DpmGatewayError(502, "Az ITEP hibás DPM tokenválaszt adott.")
        token = payload.get("accessToken") if isinstance(payload, dict) else None
        if not isinstance(token, str) or token.count(".") != 2:
            raise DpmGatewayError(502, "Az ITEP hibás DPM tokenválaszt adott.")
        return token

    def _itep_identity_headers(self, identity: DpmIdentity) -> dict[str, str]:
        now = int(datetime.now(UTC).timestamp())
        canonical_role = (
            "SYSTEM_ADMIN" if identity.role == "platform-admin" else "PROJECT_MANAGER"
        )
        permissions = (
            ["*"]
            if canonical_role == "SYSTEM_ADMIN"
            else ["project.read", "project.write", "task.accept.all", "audit.read.project"]
        )
        payload = {
            "actorId": identity.subject,
            "organizationId": "imperial-holding",
            "roles": [canonical_role],
            "permissions": permissions,
            "projectIds": sorted(identity.project_ids),
            "isSystemAdmin": canonical_role == "SYSTEM_ADMIN",
            "issuedAt": now,
            "expiresAt": now + 120,
            "nonce": str(uuid.uuid4()),
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).decode("ascii").rstrip("=")
        signature = hmac.new(
            self.settings.itep_identity_shared_secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Imperial-Identity": encoded,
            "X-Imperial-Identity-Signature": f"sha256={signature}",
        }

    def request(
        self,
        method: str,
        path: str,
        identity: DpmIdentity,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        # Az útvonal felhasználói-vezérelt része csak biztonságos
        # path-karakterekből állhat; traversal kísérlet fail-closed leáll.
        headers = {
            "Authorization": f"Bearer {self._token(identity)}",
            "Accept": "application/json",
        }
        kwargs: dict[str, Any] = {"headers": headers}
        if query:
            kwargs["params"] = {
                key: value for key, value in query.items() if value is not None
            }
        if payload is not None:
            kwargs["json"] = payload
        try:
            client = self._client(self.settings.dpm_api_base_url)
        except SafeHttpError as error:
            raise DpmGatewayError(
                502, "A Digital Project Managers cél nem biztonságos."
            ) from error
        with client:
            try:
                response = client.request(method, path, **kwargs)
                # A válasz statusát, törzsét és JSON-feldolgozását még a kliens
                # context lezárása előtt puffereljük: lezárt kapcsolat után
                # streaming/lazy választörzs már nem olvasható biztonságosan.
                status_code = response.status_code
                content = response.content
                try:
                    parsed_json: Any = response.json()
                except ValueError:
                    parsed_json = None
            except SafeHttpError as error:
                raise DpmGatewayError(
                    502, "A Digital Project Managers cél nem biztonságos."
                ) from error
            except httpx.HTTPError as error:
                raise DpmGatewayError(
                    503, "A Digital Project Managers szolgáltatás nem érhető el."
                ) from error
        if status_code >= 400:
            detail = f"DPM HTTP {status_code}"
            if isinstance(parsed_json, dict) and parsed_json.get("detail"):
                detail = str(parsed_json["detail"])
            raise DpmGatewayError(status_code, detail)
        if not content:
            return None
        if parsed_json is None:
            raise DpmGatewayError(
                502, "A Digital Project Managers hibás választ adott."
            )
        return parsed_json

    @staticmethod
    def admin_identity(subject: str) -> DpmIdentity:
        return DpmIdentity(
            subject=subject,
            role="platform-admin",
            scopes=ALL_SCOPES,
            project_ids=frozenset(),
        )

    def user_context(self, *, email: str, role: str) -> DpmUserContext:
        if role in ADMIN_ROLES:
            return DpmUserContext(
                identity=self.admin_identity(email),
                agent_ids=frozenset(),
                admin=True,
            )
        if role != "project-manager":
            raise DpmGatewayError(403, "Ehhez a DPM munkatérhez nincs jogosultság.")
        admin = self.admin_identity(f"platform-gateway:{email}")
        agents = self.request("GET", "/api/v1/agents", admin)
        agent_ids = frozenset(
            str(agent["id"])
            for agent in agents
            if str(agent.get("human_manager_ref") or "").casefold() == email.casefold()
        )
        assignments = self.request("GET", "/api/v1/assignments", admin)
        projects = frozenset(
            str(item["external_project_id"])
            for item in assignments
            if str(item["digital_manager_id"]) in agent_ids
        )
        return DpmUserContext(
            identity=DpmIdentity(
                subject=email,
                role="project-manager",
                scopes=ALL_SCOPES,
                project_ids=projects,
            ),
            agent_ids=agent_ids,
            admin=False,
        )


dpm_gateway = DpmGateway()
