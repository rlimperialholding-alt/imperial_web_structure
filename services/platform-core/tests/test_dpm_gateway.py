from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
from dataclasses import replace

import httpx
import jwt
import pytest

from app.config import settings
from app.services.dpm_gateway import ALL_SCOPES, DpmGateway, DpmGatewayError, DpmIdentity
from synthetic_fixtures import synthetic_auth_value

PRIVATE_ADDRESS = ipaddress.ip_address("10.40.40.40")

# Futásidőben képzett, közös synthetic fixture-értékek (a platform-core
# synthetic_fixtures factoryból); statikus credential-szerű literál a diffben
# nem szerepel, így a diff-credential kapu 0 találatot ad. A HS256-fixture
# két determinisztikus érték összefűzése, hogy az RFC 7518 szerinti minimális
# kulcshosszt elérje (nincs InsecureKeyLengthWarning).
_HS256_FIXTURE = synthetic_auth_value("platform-core", "dpm", "hs256") + synthetic_auth_value(
    "platform-core", "dpm", "hs256", "b"
)
_ITEP_FIXTURE = synthetic_auth_value("platform-core", "itep", "identity")


def _resolver():
    # Szintetikus, hálózatmentes DNS: a http://digital-project-managers:8000
    # docker-host privát címre oldódik, ami az engedélyezett plaintext-határ.
    return lambda host, port: {PRIVATE_ADDRESS}


def configured_gateway() -> DpmGateway:
    return DpmGateway(
        replace(
            settings,
            dpm_api_base_url="http://digital-project-managers:8000",
            dpm_auth_issuer="imperial-intelligence",
            dpm_auth_audience="digital-project-managers",
            dpm_auth_hs256_secret=_HS256_FIXTURE,
        ),
        resolver=_resolver(),
    )


def test_gateway_issues_short_lived_scoped_service_token() -> None:
    gateway = configured_gateway()
    token = gateway._token(
        DpmIdentity(
            subject="pm@example.test",
            role="project-manager",
            scopes=frozenset({"digital-pm:read", "digital-pm:write"}),
            project_ids=frozenset({"P-5001"}),
        )
    )
    claims = jwt.decode(
        token,
        gateway.settings.dpm_auth_hs256_secret,
        algorithms=["HS256"],
        issuer="imperial-intelligence",
        audience="digital-project-managers",
    )
    assert claims["sub"] == "pm@example.test"
    assert claims["role"] == "project-manager"
    assert claims["projects"] == ["P-5001"]
    assert set(claims["scope"].split()) == {"digital-pm:read", "digital-pm:write"}
    assert 0 < claims["exp"] - claims["iat"] <= 120


def test_gateway_exchanges_a_signed_platform_identity_with_itep() -> None:
    # Futásidőben képzett synthetic fixture-érték a közös factoryból;
    # statikus credential-szerű literál nincs a diffben.
    shared_key = _ITEP_FIXTURE
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/service-tokens/digital-project-managers":
            return httpx.Response(200, json={"accessToken": "header.payload.signature"})
        return httpx.Response(404, json={"detail": "not found"})

    gateway = DpmGateway(
        replace(
            settings,
            dpm_api_base_url="http://digital-project-managers:8000",
            dpm_auth_hs256_secret="",
            itep_api_base_url="http://itep-api:3000",
            itep_identity_shared_secret=shared_key,
        ),
        transport=httpx.MockTransport(handler),
        resolver=_resolver(),
    )
    token = gateway._token(
        DpmIdentity(
            subject="pm@imperial.local",
            role="project-manager",
            scopes=frozenset({"digital-pm:read", "digital-pm:write"}),
            project_ids=frozenset({"P-5002", "P-5001"}),
        )
    )

    request = requests[0]
    encoded = request.headers["X-imperial-identity"]
    expected = hmac.new(shared_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    identity = json.loads(
        base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    )
    assert token == "header.payload.signature"
    assert request.url.path.endswith("/v1/auth/service-tokens/digital-project-managers")
    assert request.headers["X-imperial-identity-signature"] == f"sha256={expected}"
    assert identity["actorId"] == "pm@imperial.local"
    assert identity["roles"] == ["PROJECT_MANAGER"]
    assert identity["projectIds"] == ["P-5001", "P-5002"]


def test_project_manager_context_is_derived_from_agent_link_and_assignments(
    monkeypatch,
) -> None:
    gateway = configured_gateway()

    def fake_request(method, path, identity, **kwargs):
        assert method == "GET"
        assert identity.role == "platform-admin"
        if path.endswith("/agents"):
            return [
                {"id": "AGENT-1", "human_manager_ref": "pm@example.test"},
                {"id": "AGENT-2", "human_manager_ref": "other@example.test"},
            ]
        return [
            {"digital_manager_id": "AGENT-1", "external_project_id": "P-5001"},
            {"digital_manager_id": "AGENT-2", "external_project_id": "P-5002"},
        ]

    monkeypatch.setattr(gateway, "request", fake_request)
    context = gateway.user_context(email="PM@example.test", role="project-manager")
    assert context.admin is False
    assert context.agent_ids == frozenset({"AGENT-1"})
    assert context.identity.project_ids == frozenset({"P-5001"})
    assert context.identity.scopes == ALL_SCOPES


def test_owner_context_is_platform_admin_without_project_expansion() -> None:
    context = configured_gateway().user_context(
        email="owner@example.test",
        role="owner",
    )
    assert context.admin is True
    assert context.identity.role == "platform-admin"
    assert context.identity.project_ids == frozenset()


class TestGatewayRequestHardening:
    def _gateway(self, handler, dpm_url: str | None = None) -> DpmGateway:
        return DpmGateway(
            replace(
                settings,
                dpm_api_base_url=dpm_url or "http://digital-project-managers:8000",
                dpm_auth_issuer="imperial-intelligence",
                dpm_auth_audience="digital-project-managers",
                dpm_auth_hs256_secret=_HS256_FIXTURE,
            ),
            transport=httpx.MockTransport(handler),
            resolver=_resolver(),
        )

    def _identity(self) -> DpmIdentity:
        return DpmIdentity(
            subject="owner@example.test",
            role="platform-admin",
            scopes=ALL_SCOPES,
            project_ids=frozenset(),
        )

    def test_traversal_path_fails_closed(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=[])

        gateway = self._gateway(handler)
        with pytest.raises(DpmGatewayError) as exc_info:
            gateway.request("GET", "/api/v1/tasks/../../admin", self._identity())
        assert exc_info.value.status_code == 502
        assert seen == []

    def test_encoded_traversal_path_fails_closed(self) -> None:
        gateway = self._gateway(lambda request: httpx.Response(200, json=[]))
        with pytest.raises(DpmGatewayError) as exc_info:
            gateway.request("GET", "/api/v1/tasks/%2e%2e/admin", self._identity())
        assert exc_info.value.status_code == 502

    def test_absolute_url_in_path_fails_closed(self) -> None:
        gateway = self._gateway(lambda request: httpx.Response(200, json=[]))
        with pytest.raises(DpmGatewayError) as exc_info:
            gateway.request("GET", "https://evil.example/api", self._identity())
        assert exc_info.value.status_code == 502

    def test_cross_origin_redirect_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://evil.example/steal"})

        gateway = self._gateway(handler)
        with pytest.raises(DpmGatewayError) as exc_info:
            gateway.request("GET", "/api/v1/agents", self._identity())
        assert exc_info.value.status_code == 502

    def test_public_resolving_http_origin_fails_closed(self) -> None:
        def public_resolver(host, port):
            return {ipaddress.ip_address("93.184.216.34")}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        gateway = DpmGateway(
            replace(
                settings,
                dpm_api_base_url="http://digital-project-managers:8000",
                dpm_auth_issuer="imperial-intelligence",
                dpm_auth_audience="digital-project-managers",
                dpm_auth_hs256_secret=_HS256_FIXTURE,
            ),
            transport=httpx.MockTransport(handler),
            resolver=public_resolver,
        )
        with pytest.raises(DpmGatewayError) as exc_info:
            gateway.request("GET", "/api/v1/agents", self._identity())
        assert exc_info.value.status_code == 502

    def test_valid_request_passes_query_and_payload(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["query"] = dict(request.url.params)
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"done": True})

        gateway = self._gateway(handler)
        result = gateway.request(
            "POST",
            "/api/v1/tasks",
            self._identity(),
            query={"project_id": "P-5001", "empty": None},
            payload={"title": "T1"},
        )
        assert result == {"done": True}
        assert captured["method"] == "POST"
        assert captured["path"] == "/api/v1/tasks"
        assert captured["query"] == {"project_id": "P-5001"}
        assert captured["json"] == {"title": "T1"}

    def test_http_error_body_detail_is_forwarded(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"detail": "A feladat zárolva."})

        gateway = self._gateway(handler)
        with pytest.raises(DpmGatewayError) as exc_info:
            gateway.request("GET", "/api/v1/agents", self._identity())
        assert exc_info.value.status_code == 409
        assert "zárolva" in str(exc_info.value)


class _LazyBody(httpx.SyncByteStream):
    """Egyszer olvasható, szintetikus válaszstream (streaming/lazy modell)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._read = False

    def __iter__(self):
        if self._read:
            raise httpx.StreamConsumed("A stream már olvasva volt.")
        self._read = True
        yield self._data


class _LazyClosedAwareResponse(httpx.Response):
    """Streaming válasz, amely a transport lezárása után nem olvasható.

    Pontosan azt a hibát modellezi, amelyet a független review jelzett:
    lezárt kliens/kapcsolat után a lazy választörzs olvasása httpx-hibát ad.
    """

    def __init__(
        self, owner: _LazyClosingTransport, status_code: int, body: dict | None
    ) -> None:
        super().__init__(
            status_code,
            headers={"content-type": "application/json"},
            stream=_LazyBody(json.dumps(body).encode("utf-8") if body is not None else b""),
        )
        self._owner = owner

    def read(self) -> bytes:
        if self._owner.closed:
            raise httpx.TransportError("A transport lezárása után a válasz nem olvasható.")
        return super().read()


class _LazyClosingTransport(httpx.BaseTransport):
    """Szintetikus, hálózatmentes transport streaming/lazy válasszal."""

    def __init__(self, status_code: int, body: dict | None) -> None:
        self._status = status_code
        self._body = body
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return _LazyClosedAwareResponse(self, self._status, self._body)

    def close(self) -> None:
        self.closed = True


class TestLazyResponseProcessedBeforeClientClose:
    """A válasz teljes feldolgozása a kliens context lezárása előtt történik.

    Ha a gateway a kliens lezárása után olvasná a lazy/streaming választ,
    a fenti transport hibát adna, és a kérés 503-ra fordulna; a tesztek
    a pufferelő viselkedést rögzítik.
    """

    def _gateway(self, transport: httpx.BaseTransport) -> DpmGateway:
        return DpmGateway(
            replace(
                settings,
                dpm_api_base_url="http://digital-project-managers:8000",
                dpm_auth_issuer="imperial-intelligence",
                dpm_auth_audience="digital-project-managers",
                dpm_auth_hs256_secret=_HS256_FIXTURE,
            ),
            transport=transport,
            resolver=_resolver(),
        )

    def test_request_reads_lazy_body_before_closing_the_client(self) -> None:
        transport = _LazyClosingTransport(200, {"done": True})
        gateway = self._gateway(transport)
        result = gateway.request(
            "GET", "/api/v1/agents", gateway.admin_identity("owner@example.test")
        )
        assert result == {"done": True}
        assert transport.closed

    def test_itep_exchange_reads_lazy_body_before_closing_the_client(self) -> None:
        transport = _LazyClosingTransport(200, {"accessToken": "a.b.c"})
        gateway = DpmGateway(
            replace(
                settings,
                dpm_api_base_url="http://digital-project-managers:8000",
                dpm_auth_hs256_secret="",
                itep_api_base_url="http://itep-api:3000",
                itep_identity_shared_secret=_ITEP_FIXTURE,
            ),
            transport=transport,
            resolver=_resolver(),
        )
        token = gateway._token(gateway.admin_identity("owner@example.test"))
        assert token == "a.b.c"
        assert transport.closed

    def test_error_detail_is_buffered_before_closing_the_client(self) -> None:
        transport = _LazyClosingTransport(409, {"detail": "A feladat zárolva."})
        gateway = self._gateway(transport)
        with pytest.raises(DpmGatewayError) as exc_info:
            gateway.request(
                "GET", "/api/v1/agents", gateway.admin_identity("owner@example.test")
            )
        assert exc_info.value.status_code == 409
        assert "zárolva" in str(exc_info.value)
        assert transport.closed
