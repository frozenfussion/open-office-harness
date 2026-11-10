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
