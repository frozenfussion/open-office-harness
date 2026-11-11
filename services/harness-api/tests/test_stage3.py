# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from conftest import Harness
from test_routes import events

from harness_api.errors import ApiError
from harness_api.events import validator
from harness_api.jobs import download_path

pytestmark = pytest.mark.anyio


async def test_tool_loop_pinning_history_and_no_private_state(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = await h.conversation()
    state = {
        "model_entry_id": h.completed()["model_entry_id"],
        "opaque": "PRIVATE_STATE",
    }
    completed = {**h.completed(), "reasoning_state": state}
    tool = {
        "type": "tool_call",
        "id": "tool-one",
        "name": "slides",
        "arguments": {"topic": "Example"},
    }
    job_id = str(uuid4())
    calls = []

    async def start(
        user: str, conversation: UUID, request: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        calls.append(request)
        assert user == "test-user"
        return {"job_id": job_id, "status": "queued"}, {
            "type": "job",
            "job_id": job_id,
            "skill": "slides",
            "title": "Example",
            "status": "queued",
            "label": "Example",
        }

    async def attach(ids: list[str], message_id: UUID) -> None:
        assert ids == [job_id]

    monkeypatch.setattr(h.app.state.jobs, "start", start)
    monkeypatch.setattr(h.app.state.jobs, "attach", attach)
    h.gateway.side_effect = [
        httpx.Response(
            200,
            text=h.sse([tool, completed]),
            headers={"Content-Type": "text/event-stream"},
        ),
        httpx.Response(
            200,
            text=h.sse([{"type": "delta", "text": "Started."}, completed]),
            headers={"Content-Type": "text/event-stream"},
        ),
    ]
    response = await h.send(identifier)
    assert [item["type"] for item in events(response)] == ["job", "delta", "completed"]
    assert "PRIVATE_STATE" not in response.text
    followup = json.loads(h.gateway.calls[-1].request.content)
    assert followup["model_entry_id"] == completed["model_entry_id"]
    assert followup["messages"][-2]["reasoning_state"] == state
    assert followup["messages"][-1]["role"] == "tool"
    assert (await h.client.get(f"/api/conversations/{identifier}")).text.find(
        "PRIVATE_STATE"
    ) == -1
    h.gateway.side_effect = None
    h.gateway.respond(
        text=h.sse([completed]), headers={"Content-Type": "text/event-stream"}
    )
    await h.send(identifier)
    history = json.loads(h.gateway.calls[-1].request.content)["messages"]
    assert any(message.get("reasoning_state") == state for message in history)
    assert calls == [{key: tool[key] for key in ("id", "name", "arguments")}]
    for topic, event in h.publisher.events:
        validator().validate(event)
        if topic == "chat.messages":
            assert (
                h.gateway.calls[0].request.headers["X-Correlation-Id"]
                == event["correlation_id"]
                or event["payload"]["text"] == "Question"
            )


async def test_round_limit_and_followup_failure(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = await h.conversation()
    tool = {
        "type": "tool_call",
        "id": "one",
        "name": "slides",
        "arguments": {"topic": "Example"},
    }

    async def refused(*args: Any) -> tuple[dict[str, Any], None]:
        return {"error": "This skill is not allowed."}, None

    monkeypatch.setattr(h.app.state.jobs, "start", refused)
    h.gateway.respond(
        text=h.sse([tool, h.completed()]), headers={"Content-Type": "text/event-stream"}
    )
    response = await h.send(identifier)
    assert "Tool limit reached for this message." in response.text
    assert h.gateway.call_count == 3

    async def started(*args: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return {}, {"type": "job", "job_id": str(uuid4()), "status": "queued"}

    async def attach(*args: Any) -> None:
        pass

    monkeypatch.setattr(h.app.state.jobs, "attach", attach)
    monkeypatch.setattr(h.app.state.jobs, "start", started)
    h.gateway.side_effect = [
        httpx.Response(
            200,
            text=h.sse([tool, h.completed()]),
            headers={"Content-Type": "text/event-stream"},
        ),
        httpx.Response(503, json={"code": "unavailable"}),
    ]
    response = await h.send(identifier)
    assert events(response)[0]["type"] == "job"
    assert (
        events(response)[-1]["error"]["message"]
        == "The job has started, but the model could not finish its answer."
    )


async def test_chat_publish_cut_empty_and_failure(h: Harness) -> None:
    identifier = await h.conversation()
    await h.send(identifier, content="x" * 20001)
    chat = [event for topic, event in h.publisher.events if topic == "chat.messages"]
    assert len(chat[0]["payload"]["text"]) == 20000
    assert chat[0]["correlation_id"] == chat[1]["correlation_id"]
    h.publisher.fail = True
    assert events(await h.send(identifier))[-1]["type"] == "completed"
    h.publisher.fail = False
    h.publisher.events.clear()
    h.gateway.respond(
        text=h.sse([h.completed()]), headers={"Content-Type": "text/event-stream"}
    )
    await h.send(identifier)
    assert len(h.publisher.events) == 1


async def test_jobs_routes_and_download(
    h: Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job_id = uuid4()
    path = tmp_path / "outputs/slides/example.pptx"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic pptx bytes")
    job = {
        "status": "completed",
        "output": {
            "file_key": str(path),
            "mime": (
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
        },
    }
    # The configured /files root is replaced only for this isolated route check.
    import harness_api.app as module

    monkeypatch.setattr(
        module, "download_path", lambda root, row: download_path(str(tmp_path), row)
    )

    async def get(identifier: UUID, user: str) -> dict[str, Any]:
        if identifier != job_id or user != "test-user":
            raise ApiError(404, "not_found", "Job not found.")
        return job

    async def listing(
        user: str, limit: int, before: UUID | None
    ) -> list[dict[str, Any]]:
        assert user == "test-user" and limit == 1 and before is None
        return []

    monkeypatch.setattr(h.app.state.jobs, "get", get)
    monkeypatch.setattr(h.app.state.jobs, "listing", listing)
    assert (await h.client.get("/api/jobs?limit=1")).json() == []
    assert (await h.client.get("/api/jobs?limit=0")).status_code == 400
    response = await h.client.get(f"/api/jobs/{job_id}/file")
    assert (
        response.content == b"synthetic pptx bytes"
        and "attachment" in response.headers["Content-Disposition"]
    )
    assert (await h.client.get(f"/api/jobs/{uuid4()}/file")).status_code == 404
    assert (await h.client.get("/api/jobs/malformed/file")).status_code == 400
    h.client.headers["Authorization"] = "Bearer " + h.token(sub="other-user")
    assert (await h.client.get(f"/api/jobs/{job_id}/file")).status_code == 404
    job["output"]["file_key"] = "/etc/passwd"
    with pytest.raises(ApiError):
        download_path(str(tmp_path), job)
    link = tmp_path / "outputs/link"
    link.symlink_to(tmp_path.parent)
    job["output"]["file_key"] = "outputs/link/escape"
    with pytest.raises(ApiError):
        download_path(str(tmp_path), job)


async def test_skill_requests_identity_statuses_and_me(h: Harness) -> None:
    route = h.router.post("http://centre.test/api/skill-requests").respond(
        201, json={"id": str(uuid4()), "status": "pending"}
    )
    assert (
        await h.client.post("/api/skill-requests", json={"skill": "slides"})
    ).status_code == 201
    assert json.loads(route.calls[-1].request.content)["user_id"] == "test-user"
    assert (
        await h.client.post(
            "/api/skill-requests", json={"skill": "slides", "user_id": "other"}
        )
    ).status_code == 400
    for status, code in [
        (403, "not_approved"),
        (400, "skill_not_requestable"),
        (409, "already_requested"),
        (409, "too_soon"),
        (429, "too_many_requests"),
    ]:
        route.respond(status, json={"code": code})
        response = await h.client.post("/api/skill-requests", json={"skill": "slides"})
        assert response.status_code == status and response.json()["code"] == code
    h.client.headers["Authorization"] = "Bearer " + h.token(
        client_id="synthetic-client"
    )
    assert (await h.client.get("/api/me")).json()["requestable_skills"] == []
    assert json.loads(h.observe.calls[-1].request.content)["is_service_account"] is True


async def test_event_stream_isolated_and_cleanup(h: Harness) -> None:
    route = next(route for route in h.app.routes if route.path == "/api/events")
    from starlette.requests import Request

    request = Request({"type": "http", "query_string": b""})
    response = await route.endpoint(
        request, {"sub": "test-user", "exp": time.time() + 300}
    )
    iterator = response.body_iterator
    waiting = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    h.app.state.notifications.emit("other-user", {"type": "job.completed"})
    assert not waiting.done()
    h.app.state.notifications.emit(
        "test-user", {"type": "job.completed", "job_id": str(uuid4())}
    )
    assert "job.completed" in await waiting
    await iterator.aclose()
    assert h.app.state.notifications.subscribers == {}


async def test_pinned_entry_failure_and_mismatch(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = await h.conversation()
    tool = {"type": "tool_call", "id": "one", "name": "slides", "arguments": {}}

    async def refused(*args: Any) -> tuple[dict[str, Any], None]:
        return {"error": "The skill arguments are invalid."}, None

    monkeypatch.setattr(h.app.state.jobs, "start", refused)
    other = {**h.completed(), "model_entry_id": str(uuid4())}
    h.gateway.side_effect = [
        httpx.Response(
            200,
            text=h.sse([tool, h.completed()]),
            headers={"Content-Type": "text/event-stream"},
        ),
        httpx.Response(
            200, text=h.sse([other]), headers={"Content-Type": "text/event-stream"}
        ),
    ]
    assert events(await h.send(identifier))[-1]["type"] == "failed"
    assert h.gateway.call_count == 2


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/jobs", None),
        ("get", f"/api/jobs/{uuid4()}/file", None),
        ("post", "/api/skill-requests", {"skill": "slides"}),
    ],
)
async def test_new_routes_need_token(
    h: Harness, method: str, path: str, body: Any
) -> None:
    h.client.headers.clear()
    assert (await h.client.request(method, path, json=body)).status_code == 401


async def test_keep_alive(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    route = next(route for route in h.app.routes if route.path == "/api/events")
    response = await route.endpoint(
        Request({"type": "http", "query_string": b""}),
        {"sub": "test-user", "exp": time.time() + 300},
    )

    async def timeout(awaitable: Any, **kwargs: Any) -> None:
        assert kwargs["timeout"] == 15
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", timeout)
    assert await anext(response.body_iterator) == ": keep-alive\n\n"
    await response.body_iterator.aclose()


async def test_kafka_invalid_retry_and_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness_api.events import Kafka

    stop = asyncio.Event()
    raw_messages = [
        "not json",
        json.dumps({"event_id": 1, "user_id": 2}),
        json.dumps(
            {
                "event_id": str(uuid4()),
                "type": "skill.result",
                "version": 1,
                "occurred_at": "2026-11-11T00:00:00Z",
                "correlation_id": str(uuid4()),
                "user_id": "test-user",
                "producer": "slides-worker",
                "payload": {
                    "skill": "slides",
                    "status": "failed",
                    "output": None,
                    "error": {"code": "example", "message": "Example"},
                },
            }
        ),
    ]

    class Message:
        def __init__(self, raw: str) -> None:
            self.raw = raw

        def value(self) -> bytes:
            return self.raw.encode()

        def topic(self) -> str:
            return "skill.results"

        def error(self) -> None:
            return None

    class Consumer:
        commits = 0

        def poll(self, timeout: int) -> Message:
            return Message(raw_messages.pop(0))

        def commit(self, **kwargs: Any) -> None:
            self.commits += 1
            if not raw_messages:
                stop.set()

        def close(self) -> None:
            pass

    kafka = object.__new__(Kafka)
    kafka.consumer = Consumer()
    kafka.schema = validator()
    outputs = []

    async def publish(topic: str, event: dict[str, Any]) -> None:
        kafka.schema.validate(event)
        outputs.append((topic, event))

    monkeypatch.setattr(kafka, "publish", publish)
    waits = []

    async def sleep(seconds: int) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    handled = []

    async def handle(topic: str, event: dict[str, Any]) -> None:
        handled.append(event)
        raise RuntimeError("synthetic handler failure")

    await kafka.run(handle, stop)
    assert kafka.consumer.commits == 3 and len(handled) == 4
    assert waits == [1, 5, 15] and len(outputs) == 3
    assert not kafka.alive
