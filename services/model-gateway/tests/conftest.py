# SPDX-License-Identifier: AGPL-3.0-only
from typing import Any

import pytest

from gateway.models import Call, Entry


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def entry() -> Entry:
    return Entry.model_validate(
        {
            "model_entry_id": "00000000-0000-4000-8000-000000000001",
            "title": "Fake entry",
            "purpose": "chat",
            "tier": 1,
            "role": "main",
            "created_at": "2026-11-10T00:00:00Z",
            "api_type": "openai_chat_completions",
            "endpoint_url": "https://example.invalid",
            "model_id": "fake-model",
            "has_key": True,
            "rate_limit_per_minute": 2,
            "daily_budget": 0,
            "input_price_per_million": 2,
            "output_price_per_million": 4,
        }
    )


@pytest.fixture
def call() -> Call:
    return Call.model_validate(
        {
            "purpose": "chat",
            "tier": 1,
            "user_id": "fake-user",
            "messages": [
                {"role": "system", "content": "Fake instruction"},
                {"role": "user", "content": "Example"},
            ],
            "tools": [
                {
                    "name": "fake_tool",
                    "description": "Fake tool",
                    "input_schema": {"type": "object"},
                }
            ],
            "stream": True,
        }
    )


class FakeDatabase:
    def __init__(self) -> None:
        self.count = 0
        self.spent = 0
        self.rows: list[Any] = []

    async def health(self) -> None:
        return None

    async def limits(self, entry: Entry, call: Call) -> tuple:
        return self.count, self.spent

    async def record(self, *row: Any) -> None:
        self.rows.append(row)


class FakeRegistry:
    def __init__(self, entries: list[Entry]) -> None:
        self.entries = entries

    async def get(self, purpose: str, tier: int | None) -> list[Entry]:
        return self.entries

    async def key(self, entry: Entry) -> str:
        return "fake-provider-key"
