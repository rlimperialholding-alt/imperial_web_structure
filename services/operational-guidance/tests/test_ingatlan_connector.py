from __future__ import annotations

import ipaddress
from collections.abc import Callable

import httpx

from app.config import Settings
from app.connectors.ingatlan import IngatlanConnector
from app.connectors.safe_http import AddressResolver, SafeHttpClient
from synthetic_fixtures import synthetic_auth_value

PUBLIC_ADDRESS = ipaddress.ip_address("93.184.216.34")


def settings() -> Settings:
    # A login-fixture értéke futásidőben, a közös synthetic factoryból
    # képződik; statikus credential-szerű literál nincs a diffben.
    fixture = synthetic_auth_value("og", "ingatlan", "login")
    return Settings(
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        ingatlan_base_url="https://apitest.ingatlan.com/v1",
        ingatlan_username="demo",
        ingatlan_password=fixture,
    )


def _public_resolver() -> AddressResolver:
    # Szintetikus, hálózatmentes DNS: publikus cím, a https-origin szabály szerint.
    return lambda host, port: {PUBLIC_ADDRESS}


def _connector(**kwargs: object) -> IngatlanConnector:
    return IngatlanConnector(settings(), resolver=_public_resolver(), **kwargs)


def _mock_client(connector: IngatlanConnector, handler: Callable) -> None:
    connector.client.close()
    connector.client = SafeHttpClient(
        connector.base_url,
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver(),
    )


def test_login_and_upsert_ad() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/login":
            return httpx.Response(
                200,
                json={"status": "success", "data": {"token": "header.payload.signature"}},
            )
        if request.url.path == "/v1/ads/IMP000001":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"ad": {"id": 123, "ownId": "IMP000001", "statusId": 0}},
                },
            )
        return httpx.Response(404, json={"status": "error", "message": "not found"})

    connector = _connector()
    _mock_client(connector, handler)
    try:
        result = connector.upsert_ad(
            {
                "ownId": "IMP000001",
                "listingType": 1,
                "propertyType": 1,
                "priceHuf": 100_000_000,
            }
        )
    finally:
        connector.close()

    ad_request = next(request for request in requests if request.url.path.endswith("IMP000001"))
    assert ad_request.headers["Authorization"] == "Bearer header.payload.signature"
    assert result["id"] == 123


def test_unauthorized_request_refreshes_token_once() -> None:
    login_count = 0
    ad_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count, ad_count
        if request.url.path == "/v1/auth/login":
            login_count += 1
            return httpx.Response(
                200,
                json={"status": "success", "data": {"token": f"token-{login_count}"}},
            )
        ad_count += 1
        if ad_count == 1:
            return httpx.Response(401, json={"status": "fail", "data": "expired"})
        return httpx.Response(
            200,
            json={"status": "success", "data": {"ad": {"ownId": "IMP000001"}}},
        )

    connector = _connector()
    _mock_client(connector, handler)
    try:
        result = connector.get_ad("IMP000001")
    finally:
        connector.close()

    assert login_count == 2
    assert ad_count == 2
    assert result["ownId"] == "IMP000001"


def test_own_id_is_limited_to_fifteen_characters() -> None:
    with _connector() as connector:
        try:
            connector.upsert_ad({"ownId": "THIS-ID-IS-WAY-TOO-LONG"})
        except ValueError as exc:
            assert "15" in str(exc)
        else:
            raise AssertionError("Expected ValueError")
