# SPDX-License-Identifier: AGPL-3.0-only
import json
import time
from collections.abc import Iterator
from uuid import UUID

import httpx
import jwt
import pytest
import respx
from conftest import FakeDatabase, FakeRegistry
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.config import Config
from gateway.engine import Engine
from gateway.identity import Identity
from gateway.models import Call, Entry, GatewayError
from gateway.registry import Registry

CONFIG = Config(
    "fake-db",
    "https://identity.invalid/realms/ooh",
    "ooh-model-gateway",
    "ooh-model-gateway",
    "fake-client-secret",
    "https://registry.invalid",
)


@pytest.fixture
def signed() -> tuple:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())) | {
        "kid": "fake-kid"
    }
    return key, jwk


def token(key: object, **changes: object) -> str:
    claims = {
        "sub": "fake-service",
        "iss": CONFIG.issuer,
        "aud": CONFIG.audience,
        "exp": int(time.time()) + 300,
        "azp": "ooh-harness-api",
    } | changes
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "fake-kid"})


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes", [{}, {"aud": "wrong"}, {"iss": "wrong"}, {"exp": 1}, {"sub": ""}]
)
async def test_signature_claims_and_jwks_cache(signed: tuple, changes: dict) -> None:
    key, jwk = signed
    with respx.mock as mock:
        route = mock.get(CONFIG.issuer + "/protocol/openid-connect/certs").mock(
            return_value=httpx.Response(200, json={"keys": [jwk]})
        )
        async with httpx.AsyncClient() as client:
            identity = Identity(CONFIG, client)
            if changes:
                with pytest.raises(GatewayError) as error:
                    await identity.authenticate("Bearer " + token(key, **changes))
                assert error.value.status == 401
            else:
                for _ in range(2):
                    assert (await identity.authenticate("Bearer " + token(key)))[
                        "sub"
                    ] == "fake-service"
                assert route.call_count == 1


@pytest.mark.anyio
async def test_registry_key_and_service_token_caches(
    entry: Entry, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    with respx.mock as mock:
        tokens = mock.post(CONFIG.issuer + "/protocol/openid-connect/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "fake-token", "expires_in": 120}
            )
        )
        entries = mock.get(CONFIG.registry_url + "/api/models").mock(
            return_value=httpx.Response(
                200, json=[entry.model_dump(mode="json", by_alias=True)]
            )
        )
        keys = mock.get(f"{CONFIG.registry_url}/api/models/{entry.id}/key").mock(
            return_value=httpx.Response(200, json={"api_key": "fake-provider-key"})
        )
        async with httpx.AsyncClient() as client:
            registry = Registry(CONFIG, client, Identity(CONFIG, client))
            for _ in range(2):
                assert (await registry.get("chat", 1))[0].id == entry.id
                assert await registry.key(entry) == "fake-provider-key"
            assert entries.call_count == keys.call_count == tokens.call_count == 1
            clock[0] += 31
            await registry.get("chat", 1)
            await registry.key(entry)
            assert entries.call_count == 2 and keys.call_count == 1
            clock[0] += 30
            await registry.key(entry)
            assert keys.call_count == 2 and tokens.call_count == 1
            clock[0] += 30
            await registry.get("chat", 1)
            assert tokens.call_count == 2


@pytest.mark.anyio
async def test_registry_failure_is_closed() -> None:
    with respx.mock as mock:
        mock.post(CONFIG.issuer + "/protocol/openid-connect/token").mock(
            return_value=httpx.Response(503)
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(GatewayError) as error:
                await Registry(CONFIG, client, Identity(CONFIG, client)).get("chat", 1)
            assert error.value.code == "registry_unavailable"


@pytest.fixture
def http(entry: Entry, signed: tuple) -> Iterator[tuple]:
    app = create_app(CONFIG)
    key, jwk = signed
    with TestClient(app) as client:
        app.state.db = FakeDatabase()
        app.state.identity.keys = {"fake-kid": jwt.PyJWK.from_dict(jwk).key}
        app.state.identity.keys_until = time.monotonic() + 300
        app.state.engine = Engine(
            app.state.engine.client, FakeRegistry([entry]), app.state.db
        )
        yield client, key


def test_health_and_classify(http: tuple) -> None:
    client, key = http
    assert client.get("/health").json() == {"status": "ok"}
    headers = {"Authorization": "Bearer " + token(key)}
    assert client.post(
        "/v1/classify",
        json={"text": "fake", "questions": {"x": "fake"}},
        headers=headers,
    ).json() == {
        "code": "not_built_yet",
        "message": "Classification arrives in Stage 3",
    }
    assert (
        client.post(
            "/v1/classify", json={"text": "", "questions": {}}, headers=headers
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/classify", json={"text": "fake", "questions": {"x": "fake"}}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "path,body",
    [
        (
            "/v1/call",
            {
                "purpose": "chat",
                "tier": 1,
                "user_id": "fake",
                "messages": [{"role": "user", "content": "fake"}],
                "stream": False,
            },
        ),
        ("/v1/classify", {"text": "fake", "questions": {"x": "fake"}}),
    ],
)
def test_wrong_caller_and_audience(http: tuple, path: str, body: dict) -> None:
    client, key = http
    assert (
        client.post(
            path,
            json=body,
            headers={"Authorization": "Bearer " + token(key, azp="ooh-control-centre")},
        ).status_code
        == 403
    )
    assert (
        client.post(
            path,
            json=body,
            headers={"Authorization": "Bearer " + token(key, aud="wrong")},
        ).status_code
        == 401
    )
    assert client.post(path, json=body).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"tier": None},
        {"messages": []},
        {"purpose": "image", "tier": 1},
        {"user_id": ""},
        {"tools": [{}]},
        {"model_entry_id": "bad"},
        {"extra": True},
    ],
)
def test_call_invalid_input(http: tuple, call: Call, change: dict) -> None:
    client, key = http
    assert (
        client.post(
            "/v1/call",
            json=call.model_dump(mode="json") | change,
            headers={"Authorization": "Bearer " + token(key)},
        ).status_code
        == 400
    )


@pytest.mark.parametrize("stream", [False, True])
def test_call_success(http: tuple, call: Call, stream: bool) -> None:
    client, key = http
    payload = 'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":"stop"}],"usage":{"prompt_tokens":8,"completion_tokens":3}}\n\n'
    answer = {
        "choices": [{"message": {"content": "Hello"}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 3},
    }
    with respx.mock as mock:
        mock.post("https://example.invalid/chat/completions").mock(
            return_value=httpx.Response(200, text=payload)
            if stream
            else httpx.Response(200, json=answer)
        )
        response = client.post(
            "/v1/call",
            json=call.model_dump(mode="json") | {"stream": stream},
            headers={"Authorization": "Bearer " + token(key)},
        )
    assert response.status_code == 200
    if stream:
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-accel-buffering"] == "no"
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert [e["type"] for e in events] == ["delta", "completed"]
    else:
        assert (
            response.json()["content"] == "Hello"
            and response.json()["model_title"] == "Fake entry"
        )
    assert len(client.app.state.db.rows) == 1


def test_pinned_missing_pre_stream_error(http: tuple, call: Call) -> None:
    client, key = http
    response = client.post(
        "/v1/call",
        json=call.model_dump(mode="json") | {"model_entry_id": str(UUID(int=5))},
        headers={"Authorization": "Bearer " + token(key)},
    )
    assert response.status_code == 404 and response.json()["code"] == "no_model"


@pytest.mark.anyio
async def test_bad_signature(signed: tuple) -> None:
    _, jwk = signed
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    async with httpx.AsyncClient() as client:
        identity = Identity(CONFIG, client)
        identity.keys = {"fake-kid": jwt.PyJWK.from_dict(jwk).key}
        identity.keys_until = time.monotonic() + 300
        with pytest.raises(GatewayError) as error:
            await identity.authenticate("Bearer " + token(other))
        assert error.value.status == 401


def test_health_unavailable(http: tuple) -> None:
    import psycopg

    client, _ = http

    async def fail() -> None:
        raise psycopg.OperationalError("fake-private-connection")

    client.app.state.db.health = fail
    response = client.get("/health")
    assert response.status_code == 503 and "fake-private" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure,reason,status",
    [
        (401, "unauthorized", 401),
        (403, "unauthorized", 403),
        (500, "bad answer", 500),
        ("timeout", "unreachable", None),
        ("malformed", "bad answer", 200),
        ("token", "unauthorized", 401),
    ],
)
async def test_registry_failure_diagnostics(
    failure: int | str,
    reason: str,
    status: int | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.WARNING, logger="gateway")
    with respx.mock as mock:
        mock.post(CONFIG.issuer + "/protocol/openid-connect/token").mock(
            return_value=httpx.Response(401)
            if failure == "token"
            else httpx.Response(
                200, json={"access_token": "fake-service-token", "expires_in": 120}
            )
        )
        route = mock.get(CONFIG.registry_url + "/api/models")
        if failure == "timeout":
            route.mock(side_effect=httpx.ConnectTimeout("fake-private-diagnostic"))
        elif failure == "malformed":
            route.mock(return_value=httpx.Response(200, text="fake-private-diagnostic"))
        elif failure != "token":
            route.mock(
                return_value=httpx.Response(failure, text="fake-private-diagnostic")
            )
        async with httpx.AsyncClient() as client:
            with pytest.raises(GatewayError, match="registry_unavailable"):
                await Registry(CONFIG, client, Identity(CONFIG, client)).get("chat", 1)
    records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "gateway"
    ]
    assert records == [
        {"message": "registry " + reason, "reason": reason, "status": status}
    ]
    assert "fake-private-diagnostic" not in caplog.text
    assert "fake-service-token" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("refresh_fails", [False, True])
async def test_unknown_key_refresh_throttled(
    signed: tuple, monkeypatch: pytest.MonkeyPatch, refresh_fails: bool
) -> None:
    import asyncio

    key, jwk = signed
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    claims = jwt.decode(token(key), options={"verify_signature": False})
    unknown = [
        jwt.encode(claims, key, algorithm="RS256", headers={"kid": "unknown-" + str(i)})
        for i in range(10)
    ]
    rotated_jwk = jwk | {"kid": "unknown-0"}
    with respx.mock as mock:
        route = mock.get(CONFIG.issuer + "/protocol/openid-connect/certs").mock(
            return_value=httpx.Response(200, json={"keys": [jwk]})
        )
        async with httpx.AsyncClient() as client:
            identity = Identity(CONFIG, client)
            await identity.authenticate("Bearer " + token(key))
            results = await asyncio.gather(
                *(identity.authenticate("Bearer " + value) for value in unknown),
                return_exceptions=True,
            )
            assert all(
                isinstance(result, GatewayError) and result.status == 401
                for result in results
            )
            assert route.call_count == 1
            clock[0] += 31
            route.mock(
                return_value=httpx.Response(503)
                if refresh_fails
                else httpx.Response(200, json={"keys": [jwk, rotated_jwk]})
            )
            results = await asyncio.gather(
                *(identity.authenticate("Bearer " + value) for value in unknown),
                return_exceptions=True,
            )
            assert route.call_count == 2
            if refresh_fails:
                assert all(isinstance(result, GatewayError) for result in results)
            else:
                assert results[0]["sub"] == "fake-service"
                assert all(isinstance(result, GatewayError) for result in results[1:])


@pytest.mark.parametrize("failure", [None, "provider_401", "key_500"])
def test_http_path_never_logs_provider_key_or_service_token(
    entry: Entry,
    call: Call,
    signed: tuple,
    failure: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    provider_key = "synthetic-private-provider-key"
    service_token = "synthetic-private-service-token"
    caplog.set_level(logging.DEBUG)
    key, jwk = signed
    app = create_app(CONFIG)
    with respx.mock as mock, TestClient(app) as client:
        app.state.identity.keys = {"fake-kid": jwt.PyJWK.from_dict(jwk).key}
        app.state.identity.keys_until = time.monotonic() + 300
        database = FakeDatabase()
        app.state.db = database
        app.state.engine.db = database
        mock.post(CONFIG.issuer + "/protocol/openid-connect/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": service_token, "expires_in": 120}
            )
        )
        mock.get(CONFIG.registry_url + "/api/models").mock(
            return_value=httpx.Response(
                200, json=[entry.model_dump(mode="json", by_alias=True)]
            )
        )
        key_route = mock.get(f"{CONFIG.registry_url}/api/models/{entry.id}/key").mock(
            return_value=httpx.Response(
                500 if failure == "key_500" else 200,
                json={"api_key": provider_key, "diagnostic": service_token},
            )
        )
        provider = mock.post("https://example.invalid/chat/completions")
        if failure != "key_500":
            provider.mock(
                return_value=httpx.Response(
                    401, json={"error": provider_key + service_token}
                )
                if failure
                else httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": "Example"}}],
                        "usage": {"prompt_tokens": 8, "completion_tokens": 3},
                    },
                )
            )
        response = client.post(
            "/v1/call",
            json=call.model_dump(mode="json") | {"stream": False},
            headers={"Authorization": "Bearer " + token(key)},
        )
        assert response.status_code == (200 if failure is None else 503)
        assert key_route.call_count == 1
        assert provider.call_count == (0 if failure == "key_500" else 1)
    captured = repr([record.__dict__ for record in caplog.records])
    assert provider_key not in captured and service_token not in captured
    assert provider_key not in response.text and service_token not in response.text


def test_server_log_diagnostics_are_safe() -> None:
    import logging
    import sys

    from gateway.__main__ import JsonFormatter

    formatter = JsonFormatter()
    try:
        raise RuntimeError("synthetic-private-key-and-token")
    except RuntimeError:
        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            "",
            0,
            "Exception in ASGI application",
            (),
            sys.exc_info(),
        )
    diagnostic = json.loads(formatter.format(record))
    assert diagnostic["logger"] == "uvicorn.error"
    assert diagnostic["exception_type"] == "RuntimeError"
    assert diagnostic["message_class"] == "unhandled_exception"
    assert "synthetic-private" not in formatter.format(record)
    startup = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        "",
        0,
        OSError(98, "synthetic-private-key-and-token"),
        (),
        None,
    )
    assert json.loads(formatter.format(startup))["exception_type"] == "OSError"
    assert json.loads(formatter.format(startup))["message_class"] == "startup_error"
    lifecycle = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        "",
        0,
        "Traceback (most recent call last):\n  private source text\nKeyError: synthetic-private-key-and-token\nsyntheticprivate: additional secret text\n",
        (),
        None,
    )
    assert json.loads(formatter.format(lifecycle))["exception_type"] == "KeyError"
    assert "synthetic-private" not in formatter.format(lifecycle)
