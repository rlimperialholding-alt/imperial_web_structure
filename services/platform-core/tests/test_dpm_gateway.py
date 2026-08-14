from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import replace

import jwt

from app.config import settings
from app.services.dpm_gateway import ALL_SCOPES, DpmGateway, DpmIdentity


def configured_gateway() -> DpmGateway:
    return DpmGateway(
        replace(
            settings,
            dpm_api_base_url="http://digital-project-managers:8000",
            dpm_auth_issuer="imperial-intelligence",
            dpm_auth_audience="digital-project-managers",
            dpm_auth_hs256_secret="test-dpm-secret-012345678901234567890123",
        )
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


def test_gateway_exchanges_a_signed_platform_identity_with_itep(monkeypatch) -> None:
    secret = "test-itep-identity-shared-secret-which-is-long-enough"
    gateway = DpmGateway(
        replace(
            settings,
            dpm_api_base_url="http://digital-project-managers:8000",
            dpm_auth_hs256_secret="",
            itep_api_base_url="http://itep-api:3000",
            itep_identity_shared_secret=secret,
        )
    )
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def read():
            return b'{"accessToken":"header.payload.signature"}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.services.dpm_gateway.urlopen", fake_urlopen)
    token = gateway._token(
        DpmIdentity(
            subject="pm@imperial.local",
            role="project-manager",
            scopes=frozenset({"digital-pm:read", "digital-pm:write"}),
            project_ids=frozenset({"P-5002", "P-5001"}),
        )
    )

    request = captured["request"]
    encoded = request.headers["X-imperial-identity"]
    expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    identity = json.loads(
        base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    )
    assert token == "header.payload.signature"
    assert captured["timeout"] == 8
    assert request.full_url.endswith("/v1/auth/service-tokens/digital-project-managers")
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
