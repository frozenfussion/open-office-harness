# SPDX-License-Identifier: AGPL-3.0-only
import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from conftest import Harness
from test_routes import events

from harness_api.events import validator
from harness_api.routing import route
from harness_api.upstream import Skill

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def routing_settings(h: Harness) -> None:
    upstream = h.app.state.upstream
    upstream.settings = replace(
        upstream.settings, route_tier_question="Test complexity?"
    )


def classifier(h: Harness, **scores: float) -> Any:
    return h.router.post("http://gateway.test/v1/classify").respond(
        json={"scores": {"needs_tier2": 0.1, "wants_slides": 0.1, **scores}}
    )


async def test_simple_auto_correlations_storage_and_audit(h: Harness) -> None:
    classify = classifier(h)
    identifier = await h.conversation()
    response = await h.send(identifier, tier="auto")
    completed = events(response)[-1]
    assert completed["routing"] == {
        "tier": 1,
        "scores": {"needs_tier2": 0.1, "wants_slides": 0.1},
    }
    row = (await h.client.get(f"/api/conversations/{identifier}")).json()
    correlation = row["messages"][0]["id"]
    assert row["messages"][-1]["routing"] == completed["routing"]
    request = classify.calls[0].request
    assert request.headers["X-Correlation-Id"] == correlation
    assert json.loads(request.content) == {
        "user_id": "test-user",
        "text": "Question",
        "questions": {
            "needs_tier2": "Test complexity?",
            "wants_slides": "Is the user asking for this: Example tool?",
        },
    }
    for call in [*h.gateway.calls, *h.title_gateway.calls]:
        assert call.request.headers["X-Correlation-Id"] == correlation
    audit = next(
        event for topic, event in h.publisher.events if topic == "audit.events"
    )
    validator().validate(audit)
    assert audit["correlation_id"] == correlation
    assert audit["payload"] == {
        "actor": "test-user",
        "action": "route",
        "target": "chat",
        "outcome": "tier_1",
        "scores": completed["routing"]["scores"],
    }
    assert "Question" not in json.dumps(audit)


@pytest.mark.parametrize("decision", [True, False, "unavailable"])
async def test_high_score_requires_right_and_falls_back(
    h: Harness, decision: Any
) -> None:
    classifier(h, needs_tier2=0.7)

    def check(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["target"] == "2":
            return (
                httpx.Response(503)
                if decision == "unavailable"
                else httpx.Response(200, json={"allowed": decision})
            )
        return httpx.Response(200, json={"allowed": True})

    h.check.side_effect = check
    tier = 2 if decision is True else 1
    h.gateway.respond(
        text=h.sse([h.completed(tier)]), headers={"Content-Type": "text/event-stream"}
    )
    completed = events(await h.send(await h.conversation(), tier="auto"))[-1]
    assert completed["tier"] == completed["routing"]["tier"] == tier
    if decision is not True:
        assert (
            completed["note"]
            == completed["routing"]["note"]
            == "This question may need tier 2. An admin can give you tier 2."
        )
    assert any(
        json.loads(call.request.content)["target"] == "2" for call in h.check.calls
    )


@pytest.mark.parametrize(
    "answer",
    [
        404,
        429,
        503,
        "timeout",
        {},
        {"needs_tier2": 1.1},
        {"needs_tier2": True},
        {"needs_tier2": "0.9"},
    ],
)
async def test_classifier_failure_lowest_allowed(h: Harness, answer: Any) -> None:
    h.rights.respond(json={"chat_tiers": [3, 2], "skills": []})
    classify = h.router.post("http://gateway.test/v1/classify")
    if type(answer) is int:
        classify.respond(answer, json={"code": "no_model"})
    elif answer == "timeout":
        classify.side_effect = httpx.ReadTimeout("synthetic timeout")
    else:
        classify.respond(json={"scores": answer})
    h.gateway.respond(
        text=h.sse([h.completed(2)]), headers={"Content-Type": "text/event-stream"}
    )
    completed = events(await h.send(await h.conversation(), tier="auto"))[-1]
    assert completed["routing"] == {
        "tier": 2,
        "scores": {},
        "note": "Routing is unavailable; answered with tier 2.",
    }
    assert json.loads(h.gateway.calls[0].request.content)["tier"] == 2


@pytest.mark.parametrize("tier", [None, 1, 3])
async def test_explicit_and_omitted_tier_bypass_classifier(
    h: Harness, tier: int | None
) -> None:
    classify = classifier(h, needs_tier2=1, wants_slides=1)
    h.gateway.respond(
        text=h.sse([h.completed(tier or 1)]),
        headers={"Content-Type": "text/event-stream"},
    )
    completed = events(await h.send(await h.conversation(), tier=tier))[-1]
    assert not classify.called
    assert "routing" not in completed
    assert "tool_choice" not in json.loads(h.gateway.calls[0].request.content)
    assert completed["tier"] == (tier or 1)


async def test_no_tier_and_removed_lowest_fail_closed(h: Harness) -> None:
    classify = classifier(h)
    h.rights.respond(json={"chat_tiers": [], "skills": []})
    assert (await h.send(await h.conversation(), tier="auto")).status_code == 403
    assert not classify.called and not h.gateway.called
    h.rights.respond(json={"chat_tiers": [1], "skills": []})
    h.check.respond(json={"allowed": False})
    assert (await h.send(await h.conversation(), tier="auto")).status_code == 403
    assert not classify.called and not h.gateway.called


async def test_disallowed_skill_is_never_classified_or_forced(h: Harness) -> None:
    h.rights.respond(json={"chat_tiers": [1], "skills": []})
    classify = classifier(h, wants_slides=1)
    completed = events(await h.send(await h.conversation(), tier="auto"))[-1]
    assert json.loads(classify.calls[0].request.content)["questions"] == {
        "needs_tier2": "Test complexity?"
    }
    assert completed["routing"]["scores"] == {"needs_tier2": 0.1}
    assert "skill" not in completed["routing"]
    assert "tool_choice" not in json.loads(h.gateway.calls[0].request.content)


@pytest.mark.parametrize("applied", [True, False])
async def test_forced_skill_without_call_note(h: Harness, applied: bool) -> None:
    classifier(h, wants_slides=0.8)
    h.gateway.respond(
        text=h.sse([{**h.completed(), "tool_choice_applied": applied}]),
        headers={"Content-Type": "text/event-stream"},
    )
    completed = events(await h.send(await h.conversation(), tier="auto"))[-1]
    assert json.loads(h.gateway.calls[0].request.content)["tool_choice"] == {
        "name": "slides"
    }
    assert completed["routing"]["skill"] == "slides"
    if not applied:
        assert (
            completed["routing"]["note"]
            == completed["note"]
            == "The model chose not to use Example skill."
        )
    else:
        assert "note" not in completed["routing"]


async def test_forced_skill_first_call_only_preserves_reasoning(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    classifier(h, wants_slides=0.9)
    state = {
        "model_entry_id": h.completed()["model_entry_id"],
        "opaque": "PRIVATE_STATE",
    }
    completed = {
        **h.completed(),
        "reasoning_state": state,
        "tool_choice_applied": False,
    }
    tool = {
        "type": "tool_call",
        "id": "tool-one",
        "name": "slides",
        "arguments": {"topic": "Example"},
    }

    async def start(*args: Any) -> tuple[dict[str, Any], None]:
        return {"job_id": str(uuid4()), "status": "queued"}, None

    monkeypatch.setattr(h.app.state.jobs, "start", start)
    h.gateway.side_effect = [
        httpx.Response(
            200, text=h.sse(items), headers={"Content-Type": "text/event-stream"}
        )
        for items in (
            [tool, completed],
            [{"type": "delta", "text": "Started"}, completed],
        )
    ]
    response = await h.send(await h.conversation(), tier="auto")
    done = events(response)[-1]
    assert "note" not in done["routing"]
    first, follow = [json.loads(call.request.content) for call in h.gateway.calls]
    assert first["tool_choice"] == {"name": "slides"}
    assert "tool_choice" not in follow
    assert follow["model_entry_id"] == state["model_entry_id"]
    assert follow["messages"][-2]["reasoning_state"] == state
    assert "PRIVATE_STATE" not in response.text
    audit = next(
        event for topic, event in h.publisher.events if topic == "audit.events"
    )
    assert audit["payload"]["outcome"] == "skill_slides"


async def test_normalized_keys_highest_skill_and_settings(h: Harness) -> None:
    upstream = h.app.state.upstream
    upstream.settings = replace(
        upstream.settings,
        route_tier_threshold=0.9,
        route_skill_threshold=0.95,
        route_up_tier=3,
    )
    skills = [
        Skill(
            name=name,
            title="Example",
            description=name,
            input_schema="unused",
            needs_approval=False,
            topic="unused",
            version="1.0.0",
        )
        for name in ("example-skill", "slides")
    ]
    classify = classifier(
        h, needs_tier2=0.9, wants_example_skill=0.96, wants_slides=0.95
    )
    result = await route(upstream, "test-user", "Question", 1, skills, uuid4())
    assert result["tier"] == 3 and result["skill"] == "example-skill"
    assert (
        "wants_example_skill"
        in json.loads(classify.calls[0].request.content)["questions"]
    )


async def test_route_audit_outage_does_not_fail_chat(h: Harness) -> None:
    classifier(h)
    h.publisher.fail = True
    assert (
        events(await h.send(await h.conversation(), tier="auto"))[-1]["type"]
        == "completed"
    )


@pytest.mark.parametrize("tier", ["AUTO", "1", True, 0, -1])
async def test_invalid_routing_tier(h: Harness, tier: Any) -> None:
    assert (await h.send(await h.conversation(), tier=tier)).status_code == 400


async def test_auto_budget_fallback_keeps_metadata_and_audit_consistent(
    h: Harness,
) -> None:
    classifier(h, needs_tier2=0.9)
    h.gateway.side_effect = [
        httpx.Response(503, json={"code": "budget_exceeded"}),
        httpx.Response(
            200,
            text=h.sse([h.completed(1)]),
            headers={"Content-Type": "text/event-stream"},
        ),
    ]
    done = events(await h.send(await h.conversation(), tier="auto"))[-1]
    assert done["tier"] == done["routing"]["tier"] == 1
    assert done["note"] == done["routing"]["note"]
    audit = next(
        event for topic, event in h.publisher.events if topic == "audit.events"
    )
    assert audit["payload"]["outcome"] == "tier_1"
