# SPDX-License-Identifier: AGPL-3.0-only
import json
from typing import Any

import httpx
import jwt
import pytest
from conftest import Harness

from harness_api.diagnostics import JsonFormatter

pytestmark = pytest.mark.anyio


def sign_claims(
    h: Harness, changes: dict[str, Any], remove: tuple[str, ...] = ()
) -> None:
    claims = jwt.decode(h.token(), options={"verify_signature": False})
    claims.update(changes)
    for name in remove:
        claims.pop(name, None)
    token = jwt.encode(
        claims, h.private_key, algorithm="RS256", headers={"kid": "test"}
    )
    h.client.headers["Authorization"] = f"Bearer {token}"


async def test_observe_verified_claims_before_rights(h: Harness) -> None:
    sign_claims(
        h,
        {
            "sub": " exact-test-sub ",
            "name": "  Example user  ",
            "email": "  example@example.invalid  ",
            "organisation": "  Example team  ",
            "access_reason": "  Example reason  ",
            "realm_access": {"roles": ["ooh-admin"]},
        },
    )
    response = await h.client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["user_id"] == " exact-test-sub "
    assert response.json()["access"] == "approved"
    request = h.observe.calls.last.request
    assert request.headers["Authorization"] == "Bearer fake-service-token"
    assert json.loads(request.content) == {
        "user_id": " exact-test-sub ",
        "name": "Example user",
        "email": "example@example.invalid",
        "organisation": "Example team",
        "access_reason": "Example reason",
        "is_admin": True,
    }
    centre_paths = [
        call.request.url.path
        for call in h.router.calls
        if call.request.url.host == "centre.test"
    ]
    assert centre_paths == ["/api/access/observe", "/api/rights/me", "/api/skills"]
    assert h.rights.calls.last.request.url.params["user_id"] == " exact-test-sub "


async def test_observe_trims_before_applying_field_limits(h: Harness) -> None:
    limits = {"name": 200, "email": 320, "organisation": 100, "access_reason": 300}
    sign_claims(
        h, {field: "  " + "x" * (limit + 1) + "  " for field, limit in limits.items()}
    )
    assert (await h.client.get("/api/me")).status_code == 200
    body = json.loads(h.observe.calls.last.request.content)
    for field, limit in limits.items():
        assert body[field] == "x" * limit


@pytest.mark.parametrize("value", [None, 123, ["example"], {"value": "example"}])
async def test_non_string_profile_claims_become_null(h: Harness, value: Any) -> None:
    fields = ("name", "email", "organisation", "access_reason")
    sign_claims(h, dict.fromkeys(fields, value))
    assert (await h.client.get("/api/me")).status_code == 200
    body = json.loads(h.observe.calls.last.request.content)
    assert all(body[field] is None for field in fields)


async def test_missing_profile_claims_become_null(h: Harness) -> None:
    fields = ("name", "email", "organisation", "access_reason")
    sign_claims(h, {}, remove=fields + ("realm_access",))
    assert (await h.client.get("/api/me")).status_code == 200
    body = json.loads(h.observe.calls.last.request.content)
    assert all(body[field] is None for field in fields)
    assert body["is_admin"] is False


@pytest.mark.parametrize(
    "realm,expected",
    [
        ({"roles": ["ooh-admin", "other-role"]}, True),
        ({"roles": ["other-role"]}, False),
        ({"roles": ["ooh-admin-extra"]}, False),
        ({"roles": "ooh-admin"}, False),
        ({"roles": None}, False),
        ({}, False),
        (None, False),
        ("ooh-admin", False),
    ],
)
async def test_admin_flag_comes_from_realm_role_list(
    h: Harness, realm: Any, expected: bool
) -> None:
    sign_claims(h, {"realm_access": realm, "is_admin": True})
    assert (await h.client.get("/api/me")).status_code == 200
    assert json.loads(h.observe.calls.last.request.content)["is_admin"] is expected


@pytest.mark.parametrize("status", ["approved", "pending", "rejected", "closed"])
async def test_access_state_is_returned(h: Harness, status: str) -> None:
    h.observe.respond(json={"status": status})
    h.rights.respond(json={"chat_tiers": [], "skills": []})
    h.skills.respond(json=[])
    response = await h.client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["access"] == status
    assert response.json()["chat_tiers"] == []
    assert response.json()["skills"] == []
    assert h.rights.called and h.skills.called


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
async def test_observe_http_failure_is_closed(h: Harness, status: int) -> None:
    h.observe.respond(status, json={"message": "synthetic-private-upstream"})
    response = await h.client.get("/api/me")
    assert response.status_code == 503
    assert response.json()["code"] == "rights_unavailable"
    assert "access" not in response.json()
    assert not h.rights.called and not h.skills.called
    assert "synthetic-private-upstream" not in response.text


@pytest.mark.parametrize(
    "problem", ["connection", "timeout", "json", "missing", "unknown", "null", "array"]
)
async def test_observe_invalid_or_missing_response_is_closed(
    h: Harness, problem: str
) -> None:
    if problem == "connection":
        h.observe.mock(side_effect=httpx.ConnectError("synthetic-private-upstream"))
    elif problem == "timeout":
        h.observe.mock(side_effect=httpx.ReadTimeout("synthetic-private-upstream"))
    elif problem == "json":
        h.observe.respond(text="not-json")
    else:
        h.observe.respond(
            json={
                "missing": {},
                "unknown": {"status": "other"},
                "null": {"status": None},
                "array": [],
            }[problem]
        )
    response = await h.client.get("/api/me")
    assert response.status_code == 503
    assert response.json()["code"] == "rights_unavailable"
    assert not h.rights.called and not h.skills.called


async def test_rights_failure_after_observe_still_fails_closed(h: Harness) -> None:
    h.rights.respond(503)
    response = await h.client.get("/api/me")
    assert h.observe.called
    assert response.status_code == 503
    assert response.json()["code"] == "rights_unavailable"
    assert "access" not in response.json()


async def test_other_routes_do_not_observe(h: Harness) -> None:
    assert (await h.client.get("/health")).status_code == 200
    identifier = await h.conversation()
    assert (await h.client.get("/api/conversations")).status_code == 200
    assert (await h.client.get(f"/api/conversations/{identifier}")).status_code == 200
    assert (await h.send(identifier)).status_code == 200
    assert (await h.client.post("/api/uploads")).status_code == 503
    assert (await h.client.get("/api/events")).status_code == 503
    assert (await h.client.get("/api/files/example")).status_code == 503
    assert not h.observe.called


async def test_observe_failure_logs_exclude_profile(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    private = "synthetic-private-profile"
    sign_claims(
        h, dict.fromkeys(("name", "email", "organisation", "access_reason"), private)
    )
    h.observe.respond(503, json={"message": private})
    response = await h.client.get("/api/me")
    assert response.status_code == 503
    lines = [JsonFormatter().format(record) for record in caplog.records]
    assert all(private not in line for line in lines)
    assert any(json.loads(line).get("code") == "rights_unavailable" for line in lines)


async def test_me_query_cannot_supply_admin_or_profile(h: Harness) -> None:
    response = await h.client.get("/api/me?is_admin=true&name=example")
    assert response.status_code == 400
    assert not h.observe.called
