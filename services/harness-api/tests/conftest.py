# SPDX-License-Identifier: AGPL-3.0-only
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa

from harness_api.app import create_app
from harness_api.config import Settings
from harness_api.errors import ApiError

SETTINGS = Settings(
    "unused",
    "https://identity.test/realms/ooh",
    "ooh-harness-api",
    "ooh-harness-api",
    "fake-client-credential",
    "http://centre.test",
    "http://gateway.test",
)


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.fail_health = False

    async def health(self) -> None:
        if self.fail_health:
            import psycopg

            raise psycopg.OperationalError("private diagnostic")

    async def create(self, user: str) -> UUID:
        identifier = uuid4()
        self.rows[identifier] = {
            "id": identifier,
            "user_id": user,
            "title": "",
            "updated_at": datetime.now(UTC),
            "messages": [],
        }
        return identifier

    async def conversation(self, identifier: UUID, user: str) -> dict[str, Any]:
        if identifier not in self.rows or self.rows[identifier]["user_id"] != user:
            raise ApiError(404, "not_found", "Conversation not found.")
        row = self.rows[identifier]
        return {"id": identifier, "title": row["title"], "messages": row["messages"]}

    async def listing(
        self, user: str, limit: int, before: UUID | None
    ) -> list[dict[str, Any]]:
        rows = sorted(
            (row for row in self.rows.values() if row["user_id"] == user),
            key=lambda row: (row["updated_at"], row["id"]),
            reverse=True,
        )
        if before:
            await self.conversation(before, user)
            index = next(i for i, row in enumerate(rows) if row["id"] == before)
            rows = rows[index + 1 :]
        return [
            {key: row[key] for key in ("id", "title", "updated_at")}
            for row in rows[:limit]
        ]

    async def history(self, identifier: UUID) -> list[dict[str, str]]:
        messages = [
            {"role": row["role"], "content": row["content"]}
            for row in self.rows[identifier]["messages"]
            if row["outcome"] == "completed" and row["content"]
        ][-20:]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    async def title_source(
        self, identifier: UUID, user: str, message_id: UUID
    ) -> dict[str, str] | None:
        await self.conversation(identifier, user)
        messages = self.rows[identifier]["messages"]
        answer = next(
            (
                message
                for message in messages
                if message["role"] == "assistant" and message["outcome"] == "completed"
            ),
            None,
        )
        question = next(
            (message for message in messages if message["role"] == "user"), None
        )
        if (
            answer is None
            or question is None
            or answer["id"] != message_id
            or self.rows[identifier]["title"] != question["content"][:60]
        ):
            return None
        return {"question": question["content"], "answer": answer["content"]}

    async def set_title(
        self, identifier: UUID, user: str, title: str, default_title: str
    ) -> bool:
        await self.conversation(identifier, user)
        if self.rows[identifier]["title"] != default_title:
            return False
        self.rows[identifier]["title"] = title
        return True

    async def append(
        self,
        identifier: UUID,
        user: str,
        role: str,
        content: str,
        outcome: str,
        tier: int,
        metadata: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> UUID:
        identifier_message = uuid4()
        row = self.rows[identifier]
        if role == "user" and not row["title"]:
            row["title"] = content[:60]
        row["messages"].append(
            {
                "id": identifier_message,
                "role": role,
                "content": content,
                "outcome": outcome,
                "tier": tier,
                "note": note,
                **{
                    key: value
                    for key, value in (metadata or {}).items()
                    if key != "thinking_applied"
                },
            }
        )
        row["updated_at"] = datetime.now(UTC)
        return identifier_message


class Harness:
    def __init__(self, router: respx.MockRouter, private_key: Any) -> None:
        self.router = router
        self.private_key = private_key
        self.store = MemoryStore()
        self.http = httpx.AsyncClient()
        self.app = create_app(SETTINGS, store=self.store, client=self.http)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://harness.test"
        )
        public = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
        )
        self.jwks = router.get(
            f"{SETTINGS.issuer}/protocol/openid-connect/certs"
        ).respond(json={"keys": [{**public, "kid": "test", "alg": "RS256"}]})
        self.token_route = router.post(
            f"{SETTINGS.issuer}/protocol/openid-connect/token"
        ).respond(json={"access_token": "fake-service-token", "expires_in": 300})
        self.tier_requests = router.post(
            "http://centre.test/api/tier-requests"
        ).respond(
            201,
            json={"id": "00000000-0000-4000-8000-000000000010", "status": "pending"},
        )
        self.observe = router.post("http://centre.test/api/access/observe").respond(
            json={"status": "approved"}
        )
        self.rights = router.get("http://centre.test/api/rights/me").respond(
            json={
                "chat_tiers": [3, 1, 2],
                "skills": ["slides"],
                "chat_tier_titles": {"1": "Example model"},
                "chat_tier_thinking_switch": {"1": True},
                "requestable_tiers": [],
            }
        )
        self.skills = router.get("http://centre.test/api/skills").respond(
            json=[
                {
                    "name": "slides",
                    "title": "Example skill",
                    "description": "Example tool",
                    "input_schema": "contracts/skills/slides/input.schema.json",
                }
            ]
        )
        self.check = router.post("http://centre.test/api/rights/check").respond(
            json={"allowed": True}
        )
        self.title_gateway = router.post(
            "http://gateway.test/v1/call", json__stream=False
        ).respond(
            503, json={"code": "unavailable", "message": "Synthetic title failure"}
        )
        self.gateway = router.post("http://gateway.test/v1/call").respond(
            text=self.sse([{"type": "delta", "text": "Hello"}, self.completed()]),
            headers={"Content-Type": "text/event-stream"},
        )
        self.client.headers["Authorization"] = f"Bearer {self.token()}"

    def token(self, **changes: Any) -> str:
        claims = {
            "sub": "test-user",
            "name": "Test user",
            "iss": SETTINGS.issuer,
            "aud": "ooh-harness-api",
            "azp": "ooh-workspace",
            "exp": int(time.time()) + 300,
            **changes,
        }
        return jwt.encode(
            claims, self.private_key, algorithm="RS256", headers={"kid": "test"}
        )

    @staticmethod
    def completed(tier: int = 1) -> dict[str, Any]:
        return {
            "type": "completed",
            "model_entry_id": "00000000-0000-4000-8000-000000000001",
            "model_title": "Example model",
            "tier": tier,
            "usage": {"input_tokens": 4, "output_tokens": 2},
            "cost_usd": "0",
        }

    @staticmethod
    def sse(events: list[dict[str, Any]]) -> str:
        return "".join("data: " + json.dumps(event) + "\n\n" for event in events)

    async def conversation(self) -> str:
        response = await self.client.post("/api/conversations", json={})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    async def send(self, identifier: str, **body: Any) -> httpx.Response:
        return await self.client.post(
            f"/api/conversations/{identifier}/messages",
            json={"content": "Question", **body},
        )


@pytest.fixture(scope="session")
def private_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def h(private_key: Any) -> AsyncIterator[Harness]:
    with respx.mock(assert_all_called=False) as router:
        harness = Harness(router, private_key)
        yield harness
        await harness.client.aclose()
        await harness.http.aclose()
