# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import base64
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from conftest import SETTINGS, Harness

from harness_api.app import create_app
from harness_api.config import Settings
from harness_api.diagnostics import JsonFormatter
from harness_api.pictures import SIGNATURES, read_picture, safe_name, write_picture

pytestmark = pytest.mark.anyio
PNG = SIGNATURES["image/png"] + b"synthetic-picture"
JPEG = SIGNATURES["image/jpeg"] + b"synthetic-picture"


@pytest.fixture
async def picture_h(h: Harness, tmp_path: Path) -> Harness:
    await h.client.aclose()
    h.app = create_app(
        replace(SETTINGS, files_root=str(tmp_path), upload_max_bytes=1048576),
        store=h.store,
        client=h.http,
        publisher=h.publisher,
    )
    h.client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=h.app),
        base_url="http://harness.test",
        headers={"Authorization": f"Bearer {h.token()}"},
    )
    return h


async def upload(
    h: Harness, content: bytes = PNG, mime: str = "image/png", **headers: str
) -> httpx.Response:
    return await h.client.post(
        "/api/uploads",
        content=content,
        headers={
            key: value.encode("latin-1")
            for key, value in {"Content-Type": mime, **headers}.items()
        },
    )


@pytest.mark.parametrize(
    "mime,content,name",
    [("image/png", PNG, "picture.png"), ("image/jpeg", JPEG, "picture.jpg")],
)
async def test_upload_and_owned_read(
    picture_h: Harness, tmp_path: Path, mime: str, content: bytes, name: str
) -> None:
    h = picture_h
    response = await upload(h, content, mime + "; charset=binary")
    assert response.status_code == 201
    row = response.json()
    assert row == {
        "upload_id": row["upload_id"],
        "file_name": name,
        "mime": mime,
        "size_bytes": len(content),
    }
    assert (tmp_path / "uploads" / row["upload_id"] / name).read_bytes() == content
    read = await h.client.get(f"/api/uploads/{row['upload_id']}")
    assert read.status_code == 200 and read.content == content
    assert read.headers["content-type"] == mime
    assert read.headers["content-disposition"] == "inline"
    assert read.headers["cache-control"] == "private, max-age=3600"
    assert read.headers["x-content-type-options"] == "nosniff"
    payload = h.publisher.events[-1][1]["payload"]
    assert payload == {
        "actor": "test-user",
        "action": "upload.created",
        "target": mime,
        "outcome": "ok",
    }
    h.client.headers["Authorization"] = f"Bearer {h.token(sub='other-user')}"
    assert (await h.client.get(f"/api/uploads/{row['upload_id']}")).status_code == 404


@pytest.mark.parametrize(
    "header,expected,jpeg_name",
    [
        (None, "picture.png", "picture.jpg"),
        ("", "picture.png", "picture.jpg"),
        ("%FF", "picture.png", "picture.jpg"),
        ("ÿ", "picture.png", "picture.jpg"),
        ("/path/to/cat.jpeg", "cat.png", "cat.jpg"),
        (r"C:\folder\cat.jpeg", "cat.png", "cat.jpg"),
        ("%2Ffolder%2Fmy%20photo.jpeg", "my photo.png", "my photo.jpg"),
        ("%E7%8C%AB%21.png", "__.png", "__.jpg"),
        (".. .hidden.jpeg", "hidden.png", "hidden.jpg"),
        ("...", "picture.png", "picture.jpg"),
        (".png", "png.png", "png.jpg"),
        ("a" * 120 + ".jpeg", "a" * 96 + ".png", "a" * 96 + ".jpg"),
    ],
)
async def test_file_names(
    picture_h: Harness, header: str | None, expected: str, jpeg_name: str
) -> None:
    headers = {"X-File-Name": header} if header is not None else {}
    response = await upload(picture_h, **headers)
    assert response.status_code == 201
    assert response.json()["file_name"] == expected
    assert safe_name(header, "image/jpeg") == jpeg_name


@pytest.mark.parametrize(
    "mime,content,status,code",
    [
        ("image/jpg", JPEG, 400, "unsupported_type"),
        ("application/octet-stream", PNG, 400, "unsupported_type"),
        ("image/png", JPEG, 400, "unsupported_type"),
        ("image/jpeg", PNG, 400, "unsupported_type"),
        ("image/png", b"", 400, "invalid_input"),
        ("image/png", PNG + b"x" * 1048576, 413, "too_large"),
    ],
)
async def test_refusals(
    picture_h: Harness, mime: str, content: bytes, status: int, code: str
) -> None:
    h = picture_h
    response = await upload(h, content, mime)
    assert response.status_code == status
    assert response.json()["code"] == code
    if code == "too_large":
        assert (
            response.json()["message"]
            == "This picture is larger than the limit of 1 MB."
        )
    assert not h.store.uploads and not h.publisher.events


async def test_upload_check_order_and_limit(
    picture_h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = picture_h
    h.client.headers.clear()
    assert (await upload(h, b"", "wrong")).status_code == 401
    h.client.headers["Authorization"] = f"Bearer {h.token()}"

    async def full(user: str) -> int:
        return 20

    monkeypatch.setattr(h.store, "upload_count", full)
    assert (await upload(h, b"", "wrong")).json()["code"] == "unsupported_type"
    assert (await upload(h, b"", "image/png")).json()["code"] == "upload_limit"
    assert (await upload(h, b"x" * 1048577)).status_code == 429
    monkeypatch.undo()
    assert (await upload(h, b"x" * 1048577)).json()["code"] == "unsupported_type"
    assert (await upload(h, PNG + b"x" * 1048576)).json()["code"] == "too_large"


async def test_read_stops_at_limit_plus_one(picture_h: Harness) -> None:
    seen = []

    async def chunks() -> Any:
        for chunk in (PNG, b"x" * 1048576, b"must-not-be-read"):
            seen.append(chunk)
            yield chunk

    response = await picture_h.client.post(
        "/api/uploads", content=chunks(), headers={"Content-Type": "image/png"}
    )
    assert response.status_code == 413
    assert len(seen) == 2


async def test_write_failure_is_not_recorded(
    picture_h: Harness, tmp_path: Path
) -> None:
    (tmp_path / "uploads").symlink_to(tmp_path, target_is_directory=True)
    response = await upload(picture_h)
    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"
    assert not picture_h.store.uploads and not picture_h.publisher.events


@pytest.mark.parametrize(
    "key",
    [
        "../outside",
        "/tmp/outside",
        "uploads/../outside",
        f"uploads/{uuid4()}/..",
        f"uploads/{uuid4()}/../../outside",
    ],
)
def test_write_rejects_escaping_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises((ValueError, OSError)):
        write_picture(str(tmp_path), key, PNG)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("level", ["uploads", "id", "file"])
def test_symlinks_refused(tmp_path: Path, level: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    identifier = str(uuid4())
    folder = tmp_path / "uploads" / identifier
    if level == "uploads":
        (tmp_path / "uploads").symlink_to(outside, target_is_directory=True)
    elif level == "id":
        folder.parent.mkdir()
        folder.symlink_to(outside, target_is_directory=True)
    else:
        folder.mkdir(parents=True)
        (folder / "picture.png").symlink_to(outside / "target")
    key = f"uploads/{identifier}/picture.png"
    for operation, args in [
        (write_picture, (str(tmp_path), key, PNG)),
        (read_picture, (str(tmp_path), key)),
    ]:
        with pytest.raises((OSError, ValueError)):
            operation(*args)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("value", [0, 1, 1048575, 1048577, 8388608, True, "7340032"])
async def test_invalid_upload_setting(
    value: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(ValueError, match="whole number of MiB from 1 to 7"):
        replace(SETTINGS, upload_max_bytes=value)
    formatted = [
        json.loads(JsonFormatter().format(record)) for record in caplog.records
    ]
    assert formatted[-1]["code"] == "upload_max_bytes_invalid"
    assert "whole number of MiB from 1 to 7" in formatted[-1]["message"]


async def test_nonnumeric_environment_refuses_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HA_UPLOAD_MAX_BYTES", "invalid")
    with pytest.raises(ValueError, match="HA_UPLOAD_MAX_BYTES"):
        Settings.from_env()


async def test_attach_refusals_before_store_or_paid_call(
    picture_h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = picture_h
    conversation = await h.conversation()
    own = (await upload(h)).json()["upload_id"]
    h.client.headers["Authorization"] = f"Bearer {h.token(sub='other-user')}"
    other = (await upload(h)).json()["upload_id"]
    h.client.headers["Authorization"] = f"Bearer {h.token()}"
    for identifier in (str(uuid4()), other):
        response = await h.send(conversation, upload_id=identifier, tier="auto")
        assert response.status_code == 404
        assert response.json()["code"] == "upload_not_found"
    monkeypatch.setattr("harness_api.app.may_attach", lambda user, rights: False)
    assert (await h.send(conversation, upload_id=own)).json()["code"] == "not_allowed"
    assert not h.store.rows[UUID(conversation)]["messages"]
    assert not h.gateway.called and not h.title_gateway.called


async def test_send_picture_reuse_race_history_and_missing_file(
    picture_h: Harness, tmp_path: Path
) -> None:
    h = picture_h
    conversation = await h.conversation()
    row = (await upload(h)).json()
    results = await asyncio.gather(
        *[h.send(conversation, upload_id=row["upload_id"]) for _ in range(2)]
    )
    assert sorted(result.status_code for result in results) == [200, 409]
    assert h.gateway.call_count == 1
    messages = json.loads(h.gateway.calls[0].request.content)["messages"]
    assert messages[-1]["images"] == [
        {"media_type": "image/png", "data": base64.b64encode(PNG).decode()}
    ]
    read = (await h.client.get(f"/api/conversations/{conversation}")).json()
    assert read["messages"][0]["picture"] == row
    assert read["messages"][1]["picture"] is None
    await h.send(conversation, content="Follow-up")
    assert (
        json.loads(h.gateway.calls[-1].request.content)["messages"][1]["images"]
        == messages[-1]["images"]
    )
    # Simulate an unavailable file without deleting stored data.
    path = tmp_path / "uploads" / row["upload_id"] / row["file_name"]
    path.rename(path.with_suffix(".unavailable"))
    assert (await h.client.get(f"/api/uploads/{row['upload_id']}")).status_code == 404
    assert (
        await h.send(conversation, content="Missing file follow-up")
    ).status_code == 200
    assert not any(
        item.get("images")
        for item in json.loads(h.gateway.calls[-1].request.content)["messages"]
    )


async def test_upload_audit_failure_keeps_upload_and_logs_no_picture(
    picture_h: Harness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = picture_h
    h.publisher.fail = True
    response = await upload(h, **{"X-File-Name": "private-camera.png"})
    assert response.status_code == 201
    assert h.store.uploads
    lines = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    assert "audit_publish_failed" in lines
    assert "private-camera" not in lines
    assert base64.b64encode(PNG).decode() not in lines
    assert "synthetic-picture" not in lines


async def test_unique_violation_is_upload_used(
    picture_h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = picture_h
    conversation = await h.conversation()
    identifier = (await upload(h)).json()["upload_id"]

    async def conflict(*args: Any, **kwargs: Any) -> UUID:
        raise psycopg.errors.UniqueViolation(
            "synthetic", info={ord("n"): b"messages_upload_once"}
        )

    monkeypatch.setattr(h.store, "append", conflict)
    response = await h.send(conversation, upload_id=identifier)
    assert response.status_code == 409
    assert response.json()["code"] == "upload_used"
    assert not h.gateway.called


async def test_failed_answer_picture_not_sent_again(picture_h: Harness) -> None:
    h = picture_h
    conversation = await h.conversation()
    identifier = (await upload(h)).json()["upload_id"]
    h.gateway.respond(502, json={"code": "image_refused"})
    result = await h.send(conversation, upload_id=identifier)
    assert result.status_code == 502 and result.json()["code"] == "image_refused"
    assert h.store.rows[UUID(conversation)]["messages"][-1]["outcome"] == "failed"
    h.gateway.respond(
        text=h.sse([{"type": "delta", "text": "Answer"}, h.completed()]),
        headers={"Content-Type": "text/event-stream"},
    )
    assert (await h.send(conversation, content="Another question")).status_code == 200
    assert not any(
        item.get("images")
        for item in json.loads(h.gateway.calls[-1].request.content)["messages"]
    )


@pytest.mark.parametrize("path", ["/api/uploads/bad", "/api/conversations/bad/export"])
async def test_new_get_invalid_id(h: Harness, path: str) -> None:
    assert (await h.client.get(path)).status_code == 400


@pytest.mark.parametrize(
    "path", [f"/api/uploads/{uuid4()}", f"/api/conversations/{uuid4()}/export"]
)
async def test_new_get_auth(h: Harness, path: str) -> None:
    h.client.headers.clear()
    assert (await h.client.get(path)).status_code == 401


async def test_daily_limit_serializes_simultaneous_uploads(picture_h: Harness) -> None:
    h = picture_h
    for _ in range(19):
        identifier = uuid4()
        h.store.uploads[identifier] = {"user_id": "test-user"}
    responses = await asyncio.gather(upload(h), upload(h))
    assert sorted(response.status_code for response in responses) == [201, 429]
    assert await h.store.upload_count("test-user") == 20


async def test_used_upload_is_refused_before_append(
    picture_h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = picture_h
    conversation = await h.conversation()
    identifier = (await upload(h)).json()["upload_id"]
    assert (await h.send(conversation, upload_id=identifier)).status_code == 200
    messages = list(h.store.rows[UUID(conversation)]["messages"])
    gateway_calls = h.gateway.call_count
    title_calls = h.title_gateway.call_count
    append_attempts = []
    append = h.store.append

    async def record_append(*args: Any, **kwargs: Any) -> UUID:
        append_attempts.append((args, kwargs))
        return await append(*args, **kwargs)

    monkeypatch.setattr(h.store, "append", record_append)
    response = await h.send(conversation, upload_id=identifier)
    assert response.status_code == 409
    assert response.json() == {
        "code": "upload_used",
        "message": (
            "This picture was already sent. Attach it again to send it once more."
        ),
    }
    assert h.store.rows[UUID(conversation)]["messages"] == messages
    assert h.gateway.call_count == gateway_calls
    assert h.title_gateway.call_count == title_calls
    assert append_attempts == []


@pytest.mark.parametrize("removed", [False, True], ids=["missing-row", "removed-row"])
async def test_missing_upload_row_does_not_block_followup(
    picture_h: Harness,
    removed: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = picture_h
    conversation = await h.conversation()
    row = (await upload(h, **{"X-File-Name": "private-camera.png"})).json()
    assert (await h.send(conversation, upload_id=row["upload_id"])).status_code == 200
    if removed:
        from datetime import UTC, datetime

        h.store.uploads[UUID(row["upload_id"])]["deleted_at"] = datetime.now(UTC)
    else:
        # The conversation references a row absent from this isolated fake store.
        h.store.rows[UUID(conversation)]["messages"][0]["upload_id"] = uuid4()
    response = await h.send(
        conversation, content="Follow-up without the removed picture"
    )
    assert response.status_code == 200
    messages = json.loads(h.gateway.calls[-1].request.content)["messages"]
    assert not any(item.get("images") for item in messages)
    read = await h.client.get(f"/api/conversations/{conversation}")
    assert read.status_code == 200 and read.json()["messages"][0]["picture"] is None
    assert (
        await h.client.get(f"/api/conversations/{conversation}/export")
    ).status_code == 200
    lines = [json.loads(JsonFormatter().format(record)) for record in caplog.records]
    missing = [line for line in lines if line.get("code") == "storage_unavailable"]
    assert missing and "correlation_id" in missing[-1]
    assert set(missing[-1]) == {"level", "event", "code", "correlation_id"}
    formatted = json.dumps(lines)
    assert "private-camera" not in formatted
    assert base64.b64encode(PNG).decode() not in formatted
