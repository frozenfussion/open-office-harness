# SPDX-License-Identifier: AGPL-3.0-only
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .errors import ApiError

MAX_THINKING_CHARS = 100_000


class Store:
    def __init__(self, connection: str) -> None:
        self.connection = connection

    async def health(self) -> None:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute("SELECT 1")

    async def create(self, user: str) -> UUID:
        identifier = uuid4()
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute(
                "INSERT INTO conversations "
                "(id,user_id,title,created_at,updated_at,created_by,updated_by) "
                "VALUES (%s,%s,'',clock_timestamp(),clock_timestamp(),%s,%s)",
                (identifier, user, user, user),
            )
        return identifier

    async def conversation(self, identifier: UUID, user: str) -> dict[str, Any]:
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            cursor = await db.execute(
                "SELECT id,title,created_at FROM conversations "
                "WHERE id=%s AND user_id=%s AND deleted_at IS NULL",
                (identifier, user),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ApiError(404, "not_found", "Conversation not found.")
            cursor = await db.execute(
                "SELECT id,role,content,tier,model_entry_id,model_title,input_tokens,"
                "output_tokens,note,outcome,created_at,thinking,routing,upload_id "
                "FROM messages "
                "WHERE conversation_id=%s ORDER BY created_at,id",
                (identifier,),
            )
            row["messages"] = await cursor.fetchall()
            for message in row["messages"]:
                upload = message.pop("upload_id")
                message["picture"] = None
                if upload:
                    picture = await self.upload(upload, user)
                    message["picture"] = self.picture(picture)
            return row

    @staticmethod
    def picture(upload: dict[str, Any]) -> dict[str, Any]:
        return {
            "upload_id": upload["id"],
            **{key: upload[key] for key in ("file_name", "mime", "size_bytes")},
        }

    async def upload_count(self, user: str) -> int:
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            cursor = await db.execute(
                "SELECT count(*) FROM uploads WHERE user_id=%s "
                "AND created_at >= date_trunc('day',now() AT TIME ZONE 'UTC') "
                "AT TIME ZONE 'UTC'",
                (user,),
            )
            return (await cursor.fetchone())["count"]

    async def upload(self, identifier: UUID, user: str) -> dict[str, Any]:
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            cursor = await db.execute(
                "SELECT u.*,EXISTS(SELECT 1 FROM messages m WHERE "
                "m.upload_id=u.id) AS used "
                "FROM uploads u WHERE u.id=%s AND u.user_id=%s AND u.deleted_at "
                "IS NULL",
                (identifier, user),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ApiError(404, "upload_not_found", "Picture not found.")
            return row

    async def save_upload(self, upload: dict[str, Any], user: str) -> None:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute(
                "INSERT INTO "
                "uploads(id,user_id,file_name,mime,size_bytes,sha256,file_key,"
                "created_by,updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    upload["id"],
                    user,
                    upload["file_name"],
                    upload["mime"],
                    upload["size_bytes"],
                    upload["sha256"],
                    upload["file_key"],
                    user,
                    user,
                ),
            )

    async def listing(
        self, user: str, limit: int, before: UUID | None
    ) -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            params: list[Any] = [user]
            boundary = ""
            if before is not None:
                cursor = await db.execute(
                    "SELECT updated_at,id FROM conversations "
                    "WHERE id=%s AND user_id=%s AND deleted_at IS NULL",
                    (before, user),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ApiError(404, "not_found", "Conversation not found.")
                boundary = "AND (updated_at,id) < (%s,%s) "
                params.extend([row["updated_at"], row["id"]])
            params.append(limit)
            cursor = await db.execute(
                "SELECT id,title,updated_at FROM conversations "
                "WHERE user_id=%s AND deleted_at IS NULL "
                + boundary
                + "ORDER BY updated_at DESC,id DESC LIMIT %s",
                params,
            )
            return await cursor.fetchall()

    async def history(self, identifier: UUID) -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            cursor = await db.execute(
                "WITH all_rows AS (SELECT *,lead(outcome) OVER (ORDER BY "
                "created_at,id) "
                "AS answer_outcome FROM messages WHERE conversation_id=%s) "
                "SELECT role,content,reasoning_state,upload_id,answer_outcome "
                "FROM (SELECT "
                "id,role,content,created_at,reasoning_state,upload_id,answer_outcome "
                "FROM all_rows WHERE true "
                "AND outcome='completed' AND content<>'' "
                "ORDER BY created_at DESC,id DESC LIMIT 20) recent "
                "ORDER BY created_at,id",
                (identifier,),
            )
            rows = await cursor.fetchall()
        for row in rows:
            upload = row.pop("upload_id")
            answer = row.pop("answer_outcome")
            if row["role"] == "user" and upload:
                row["upload_id"] = upload
                row["picture_completed"] = answer == "completed"
            if row["role"] != "assistant" or row["reasoning_state"] is None:
                row.pop("reasoning_state")
        while rows and rows[0]["role"] != "user":
            rows.pop(0)
        return rows

    async def title_source(
        self, identifier: UUID, user: str, message_id: UUID
    ) -> dict[str, str] | None:
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            cursor = await db.execute(
                "SELECT question.content AS question, answer.content AS answer "
                "FROM conversations c "
                "JOIN LATERAL (SELECT id,content FROM messages "
                "WHERE conversation_id=c.id AND role='assistant' "
                "AND outcome='completed' ORDER BY created_at,id LIMIT 1) "
                "answer ON answer.id=%s "
                "JOIN LATERAL (SELECT content FROM messages "
                "WHERE conversation_id=c.id AND role='user' "
                "ORDER BY created_at,id LIMIT 1) question ON true "
                "WHERE c.id=%s AND c.user_id=%s AND c.deleted_at IS NULL "
                "AND c.title=left(question.content,60)",
                (message_id, identifier, user),
            )
            return await cursor.fetchone()

    async def set_title(
        self, identifier: UUID, user: str, title: str, default_title: str
    ) -> bool:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            cursor = await db.execute(
                "UPDATE conversations SET title=%s,updated_by=%s "
                "WHERE id=%s AND user_id=%s AND deleted_at IS NULL AND title=%s",
                (title, user, identifier, user, default_title),
            )
            return cursor.rowcount == 1

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
        thinking: str | None = None,
        upload_id: UUID | None = None,
    ) -> UUID:
        metadata = metadata or {}
        thinking = thinking[:MAX_THINKING_CHARS] if thinking else None
        usage = metadata.get("usage", {})
        message_id = uuid4()
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            # Monotonic conversation timestamps preserve message order across streams.
            await db.execute(
                "UPDATE conversations SET updated_at=greatest(clock_timestamp(),"
                "updated_at + interval '1 microsecond'),updated_by=%s,"
                "title=CASE WHEN title='' AND %s='user' THEN %s ELSE title END "
                "WHERE id=%s AND user_id=%s AND deleted_at IS NULL",
                (user, role, content[:60], identifier, user),
            )
            await db.execute(
                "INSERT INTO messages (id,conversation_id,role,content,thinking,tier,"
                "model_entry_id,model_title,input_tokens,output_tokens,note,outcome,reasoning_state,routing,"
                "created_at,created_by,upload_id) SELECT %s,id,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,"
                "updated_at,%s,%s FROM conversations WHERE id=%s AND user_id=%s "
                "AND deleted_at IS NULL",
                (
                    message_id,
                    role,
                    content,
                    thinking,
                    tier,
                    metadata.get("model_entry_id"),
                    metadata.get("model_title"),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    note,
                    outcome,
                    Jsonb(metadata.get("reasoning_state"))
                    if role == "assistant"
                    else None,
                    Jsonb(metadata.get("routing")),
                    user,
                    upload_id,
                    identifier,
                    user,
                ),
            )
        return message_id
