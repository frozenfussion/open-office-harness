# SPDX-License-Identifier: AGPL-3.0-only
import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import httpx
import pytest
from conftest import SETTINGS, Harness

from harness_api.config import DEFAULT_SYSTEM_PROMPT, Settings
from harness_api.diagnostics import JsonFormatter

pytestmark = pytest.mark.anyio


async def test_me_passes_through_tier_titles(h: Harness) -> None:
    titles = {"1": "Example main model", "3": "Another example model"}
    h.rights.respond(
        json={"chat_tiers": [3, 2, 1], "skills": [], "chat_tier_titles": titles}
    )
    response = await h.client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["chat_tier_titles"] == titles
    assert response.json()["chat_tiers"] == [1, 2, 3]
    assert "2" not in response.json()["chat_tier_titles"]


@pytest.mark.parametrize("include_map", [True, False])
async def test_me_has_no_invented_model_title(h: Harness, include_map: bool) -> None:
    body: dict[str, Any] = {"chat_tiers": [1], "skills": []}
    if include_map:
        body["chat_tier_titles"] = {}
    h.rights.respond(json=body)
    response = await h.client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["chat_tier_titles"] == {}


@pytest.mark.parametrize("titles", [None, [], {"1": 123}])
async def test_invalid_tier_title_map_fails_closed(h: Harness, titles: Any) -> None:
    h.rights.respond(json={"chat_tiers": [1], "skills": [], "chat_tier_titles": titles})
    response = await h.client.get("/api/me")
    assert response.status_code == 503
    assert response.json()["code"] == "rights_unavailable"


@pytest.mark.parametrize("setting", [None, "", "Synthetic custom system instruction"])
def test_system_prompt_environment_setting(
    monkeypatch: pytest.MonkeyPatch, setting: str | None
) -> None:
    values = {
        "HA_DB_CONNECTION": "unused",
        "HA_OIDC_ISSUER": "https://identity.test/realms/ooh",
        "HA_OIDC_AUDIENCE": "ooh-harness-api",
        "HA_CLIENT_ID": "ooh-harness-api",
        "HA_CLIENT_SECRET": "fake-client-credential",
        "HA_CONTROL_CENTRE_URL": "http://centre.test",
        "HA_GATEWAY_URL": "http://gateway.test",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    if setting is None:
        monkeypatch.delenv("HA_SYSTEM_PROMPT", raising=False)
    else:
        monkeypatch.setenv("HA_SYSTEM_PROMPT", setting)
    config = Settings.from_env()
    assert config.system_prompt == (
        DEFAULT_SYSTEM_PROMPT if setting is None else setting
    )
    if setting:
        assert setting not in repr(config)


async def test_default_system_message_precedes_history_and_latest_user(
    h: Harness,
) -> None:
    identifier = await h.conversation()
    await h.send(identifier, content="First question")
    await h.send(identifier, content="Second question")
    first, second = [
        json.loads(call.request.content)["messages"] for call in h.gateway.calls
    ]
    expected = {
        "role": "system",
        "content": (
            "You are the assistant in Open Office Harness. "
            "Always reply in the same language as the user's latest message."
        ),
    }
    assert first == [expected, {"role": "user", "content": "First question"}]
    assert second == [
        expected,
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Second question"},
    ]
    assert all(
        message["role"] != "system"
        for message in h.store.rows[UUID(identifier)]["messages"]
    )


async def test_custom_system_prompt_and_budget_fallback(h: Harness) -> None:
    prompt = "Synthetic custom system instruction"
    h.app.state.upstream.settings = replace(SETTINGS, system_prompt=prompt)
    identifier = await h.conversation()
    h.gateway.mock(
        side_effect=[
            httpx.Response(503, json={"code": "budget_exceeded"}),
            httpx.Response(
                200,
                text=h.sse([h.completed()]),
                headers={"Content-Type": "text/event-stream"},
            ),
        ]
    )
    assert (await h.send(identifier, tier=3)).status_code == 200
    calls = [json.loads(call.request.content) for call in h.gateway.calls]
    assert [call["tier"] for call in calls] == [3, 1]
    assert calls[0]["messages"] == calls[1]["messages"]
    for call in calls:
        assert call["messages"][0] == {"role": "system", "content": prompt}
        assert sum(message["role"] == "system" for message in call["messages"]) == 1


async def test_empty_system_prompt_omits_system_message(h: Harness) -> None:
    h.app.state.upstream.settings = replace(SETTINGS, system_prompt="")
    identifier = await h.conversation()
    assert (await h.send(identifier)).status_code == 200
    assert json.loads(h.gateway.calls.last.request.content)["messages"] == [
        {"role": "user", "content": "Question"}
    ]


async def test_system_prompt_is_never_logged_or_stored(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    prompt = "synthetic-private-system-prompt"
    h.app.state.upstream.settings = replace(SETTINGS, system_prompt=prompt)
    identifier = await h.conversation()
    h.gateway.respond(503, json={"code": "unavailable", "message": prompt})
    response = await h.send(identifier)
    assert response.status_code == 503
    assert prompt not in response.text
    assert prompt not in caplog.text
    assert all(
        prompt not in JsonFormatter().format(record) for record in caplog.records
    )
    assert all(
        prompt not in message["content"]
        for message in h.store.rows[UUID(identifier)]["messages"]
    )


async def test_caller_cannot_override_system_prompt(h: Harness) -> None:
    identifier = await h.conversation()
    response = await h.send(identifier, system_prompt="Caller instruction")
    assert response.status_code == 400
    assert not h.gateway.called
