# SPDX-License-Identifier: AGPL-3.0-only
import json
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from consumer.app import create_app
from consumer.config import Config
from consumer.identity import Identity


class Database:
    async def health(self) -> None:
        pass

    async def trail(self, filters: dict, before_id: int | None, limit: int) -> list:
        return [
            {
                "action": "fake",
                "limit": limit,
                "before_id": before_id,
                "user_id": filters["user_id"],
            }
        ]

    async def counts(self, day: Any) -> dict:
        return {"day": day.isoformat(), "by_action": {"fake": 2}, "distinct_users": 1}

    async def costs(self, day: Any) -> dict:
        return {
            "day": day.isoformat(),
            "total_usd": 0.01,
            "calls": 1,
            "tokens": 5,
            "by_model": [],
        }


class Runner:
    def healthy(self) -> bool:
        return True


def setup() -> tuple[TestClient, Any, Config]:
    config = Config(issuer="https://identity.invalid/realms/ooh")
    app = create_app(config)
    app.state.db = Database()
    app.state.runner = Runner()
    app.state.identity = Identity(config, httpx.AsyncClient())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.identity.keys = {"fake": key.public_key()}
    app.state.identity.keys_until = time.monotonic() + 300
    return TestClient(app), key, config


def token(key: Any, config: Config, **change: Any) -> str:
    claims = {
        "sub": "fake-control",
        "azp": "ooh-control-centre",
        "iss": config.issuer,
        "aud": config.audience,
        "exp": datetime.now(UTC) + timedelta(minutes=2),
    } | change
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "fake"})


def test_health_does_not_require_token_and_reports_consumer_failure() -> None:
    client, _key, _config = setup()
    assert client.get("/health").json() == {"status": "ok"}
    client.app.state.runner.healthy = lambda: False
    assert client.get("/health").status_code == 503


@pytest.mark.parametrize(
    "path",
    ["/v1/trail?limit=10&before_id=20&user_id=fake", "/v1/counts?day=2026-11-11"],
)
def test_routes_validate_caller_audience_and_input(path: str) -> None:
    client, key, config = setup()
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer junk"}).status_code == 401
    for changes, status in [
        ({}, 200),
        ({"azp": "ooh-harness-api"}, 403),
        ({"aud": "wrong"}, 401),
        ({"iss": "wrong"}, 401),
        ({"exp": 0}, 401),
    ]:
        response = client.get(
            path, headers={"Authorization": "Bearer " + token(key, config, **changes)}
        )
        assert response.status_code == status
    headers = {"Authorization": "Bearer " + token(key, config)}
    for query in [
        "/v1/trail?limit=0",
        "/v1/trail?limit=201",
        "/v1/trail?before_id=0",
        "/v1/trail?correlation_id=bad",
        "/v1/trail?action=",
        "/v1/counts?day=bad",
        "/v1/counts?day=2026-02-30",
        "/v1/counts",
    ]:
        assert client.get(query, headers=headers).status_code == 400


def test_trail_cost_is_json_number_rounded_to_six_places_or_null() -> None:
    client, key, config = setup()

    class DecimalTrail(Database):
        async def trail(self, filters: dict, before_id: int | None, limit: int) -> list:
            return [
                {"cost_usd": Decimal("0.000451")},
                {"cost_usd": Decimal("12.1234567")},
                {"cost_usd": Decimal(0)},
                {"cost_usd": None},
            ]

    client.app.state.db = DecimalTrail()
    response = client.get(
        "/v1/trail", headers={"Authorization": "Bearer " + token(key, config)}
    )
    assert response.status_code == 200
    wire = json.loads(response.content)
    for row, expected in zip(wire[:3], [0.000451, 12.123457, 0], strict=True):
        assert isinstance(row["cost_usd"], (float, int)) and not isinstance(
            row["cost_usd"], bool
        )
        assert row["cost_usd"] == expected
    assert wire[3]["cost_usd"] is None


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-11-10T16:00:00Z", "2026-11-11T16:00:00Z"),
        ("2026-11-10T16:00:00+00:00", "2026-12-11T16:00:00+00:00"),
    ],
)
def test_summary_range_passes_exact_utc_bounds_and_uses_from_date(
    start: str, end: str
) -> None:
    client, key, config = setup()
    calls = []

    class Ranged(Database):
        async def counts(
            self, day: Any, *, bounds: tuple[datetime, datetime] | None = None
        ) -> dict:
            calls.append((day, bounds))
            return {
                "day": day.isoformat(),
                "by_action": {"model.call": 2},
                "distinct_users": 1,
            }

    client.app.state.db = Ranged()
    headers = {"Authorization": "Bearer " + token(key, config)}
    response = client.get(
        "/v1/counts", params={"from": start, "to": end}, headers=headers
    )
    assert response.status_code == 200
    wire = json.loads(response.content)
    assert wire["day"] == "2026-11-10"
    assert calls == [
        (
            date(2026, 11, 10),
            (datetime.fromisoformat(start), datetime.fromisoformat(end)),
        )
    ]
    assert set(wire) == {"day", "by_action", "distinct_users"}
    assert wire["by_action"] == {"model.call": 2} and wire["distinct_users"] == 1
    # Explicit bounds remain authoritative if the legacy day is also supplied.
    response = client.get(
        "/v1/counts",
        params={"from": start, "to": end, "day": "2026-11-11"},
        headers=headers,
    )
    assert response.status_code == 200 and response.json()["day"] == "2026-11-10"
    assert (
        client.get("/v1/counts", params={"from": start, "to": end}).status_code == 401
    )
    assert (
        client.get(
            "/v1/counts",
            params={"from": start, "to": end},
            headers={
                "Authorization": "Bearer " + token(key, config, azp="ooh-harness-api")
            },
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"from": "2026-11-10T16:00:00Z"},
        {"to": "2026-11-11T16:00:00Z"},
        {"day": "2026-11-11", "from": "2026-11-10T16:00:00Z"},
        {"from": "2026-11-10T16:00:00", "to": "2026-11-11T16:00:00Z"},
        {"from": "2026-11-10T16:00:00Z", "to": "2026-11-11T16:00:00"},
        {"from": "2026-11-10T16:00:00+08:00", "to": "2026-11-11T16:00:00Z"},
        {"from": "2026-11-10T16:00:00Z", "to": "2026-11-11T16:00:00-01:00"},
        {"from": "2026-11-10", "to": "2026-11-11T16:00:00Z"},
        {"from": "bad", "to": "2026-11-11T16:00:00Z"},
        {"from": "1794326400", "to": "2026-11-11T16:00:00Z"},
        {"from": "2026-11-10T16:00:00Z", "to": ""},
        {"from": "2026-11-10T16:00:00Z", "to": "2026-11-10T16:00:00Z"},
        {"from": "2026-11-11T16:00:00Z", "to": "2026-11-10T16:00:00Z"},
        {"from": "2026-11-10T16:00:00Z", "to": "2026-12-11T16:00:00.000001Z"},
    ],
)
def test_invalid_summary_ranges_are_rejected(query: dict[str, str]) -> None:
    client, key, config = setup()
    response = client.get(
        "/v1/counts",
        params=query,
        headers={"Authorization": "Bearer " + token(key, config)},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_input"
