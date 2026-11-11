# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from jsonschema import Draft202012Validator
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .errors import ApiError
from .events import JobEvents, Publisher, envelope
from .upstream import Upstream


class Jobs:
    def __init__(
        self,
        connection: str,
        upstream: Upstream,
        publisher: Publisher,
        events: JobEvents,
    ) -> None:
        self.connection = connection
        self.upstream = upstream
        self.publisher = publisher
        self.events = events

    @staticmethod
    def view(row: dict[str, Any], title: str) -> dict[str, Any]:
        return {
            "job_id": str(row["id"]),
            "skill": row["skill"],
            "title": title,
            "label": row["input"].get("topic", title)[:80],
            **{
                key: row[key]
                for key in ("status", "created_at", "updated_at", "output", "error")
            },
        }

    async def start(
        self, user: str, conversation: UUID, tool: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            _, skills = await self.upstream.permissions(user)
        except ApiError:
            return {"error": "Rights could not be checked."}, None
        skill = next((value for value in skills if value.name == tool["name"]), None)
        if skill is None or skill.name not in self.upstream.schemas:
            return {"error": "This skill is not allowed."}, None
        if not Draft202012Validator(self.upstream.schemas[skill.name]).is_valid(
            tool["arguments"]
        ):
            return {"error": "The skill arguments are invalid."}, None
        identifier = uuid4()
        status = "awaiting_approval" if skill.needs_approval else "queued"
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute(
                "INSERT INTO "
                "jobs(id,user_id,conversation_id,skill,skill_version,"
                "input,status,created_by,updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    identifier,
                    user,
                    conversation,
                    skill.name,
                    skill.version,
                    Jsonb(tool["arguments"]),
                    status,
                    user,
                    user,
                ),
            )
        try:
            await self.publisher.publish(
                "audit.events",
                envelope(
                    "audit.event",
                    str(identifier),
                    user,
                    {
                        "actor": user,
                        "action": "rights.check",
                        "target": "skill." + skill.name,
                        "outcome": "allowed",
                    },
                ),
            )
            if skill.needs_approval:
                topic, kind, payload = (
                    "approvals.requested",
                    "approval.requested",
                    {
                        "action": "skill." + skill.name,
                        "details": {"skill": skill.name, "input": tool["arguments"]},
                        "risk": "skill",
                        "requested_by": user,
                    },
                )
            else:
                topic, kind, payload = (
                    skill.topic,
                    "skill.requested",
                    {
                        "skill": skill.name,
                        "skill_version": skill.version,
                        "input": tool["arguments"],
                    },
                )
            await self.publisher.publish(
                topic, envelope(kind, str(identifier), user, payload)
            )
            await self.publisher.publish(
                "audit.events",
                envelope(
                    "audit.event",
                    str(identifier),
                    user,
                    {
                        "actor": user,
                        "action": "skill."
                        + (
                            "awaiting_approval" if skill.needs_approval else "requested"
                        ),
                        "target": skill.name,
                        "outcome": status,
                    },
                ),
            )
            result = {
                "job_id": str(identifier),
                "status": status,
                "message": "The job has started; the person will see it in "
                "their Jobs panel.",
            }
        except Exception:
            status = "failed"
            error = {
                "code": "queue_unavailable",
                "message": "The job could not be started. Try again.",
            }
            async with await psycopg.AsyncConnection.connect(self.connection) as db:
                await db.execute(
                    "UPDATE jobs SET "
                    "status='failed',error=%s,updated_at=clock_timestamp() WHERE id=%s",
                    (Jsonb(error), identifier),
                )
            result = {"error": "The job could not be started."}
        event = {
            "type": "job",
            "job_id": str(identifier),
            "skill": skill.name,
            "title": skill.title,
            "label": tool["arguments"].get("topic", skill.title)[:80],
            "status": status,
        }
        if status == "failed":
            event["error"] = error
        self.events.emit(
            user,
            {
                "type": "job." + status,
                "correlation_id": str(identifier),
                "skill": skill.name,
                "output": None,
                "error": event.get("error"),
            },
        )
        return result, event

    async def attach(self, identifiers: list[str], message_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute(
                "UPDATE jobs SET message_id=%s WHERE id=ANY(%s)",
                (message_id, [UUID(value) for value in identifiers]),
            )

    async def get(self, identifier: UUID, user: str) -> dict[str, Any]:
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE id=%s AND user_id=%s AND deleted_at IS NULL",
                (identifier, user),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ApiError(404, "not_found", "Job not found.")
        return row

    async def listing(
        self, user: str, limit: int, before: UUID | None
    ) -> list[dict[str, Any]]:
        boundary = await self.get(before, user) if before else None
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            params: list[Any] = [user]
            where = ""
            if boundary:
                where = " AND (created_at,id)<(%s,%s)"
                params.extend([boundary["created_at"], boundary["id"]])
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE user_id=%s AND deleted_at IS NULL"
                + where
                + " ORDER BY created_at DESC,id DESC LIMIT %s",
                [*params, limit],
            )
            rows = await cursor.fetchall()
        try:
            _, skills = await self.upstream.permissions(user)
        except ApiError:
            skills = []
        titles = {
            name: manifest["title"]
            for name, manifest in self.upstream.manifests.items()
        }
        titles.update({skill.name: skill.title for skill in skills})
        return [self.view(row, titles.get(row["skill"], row["skill"])) for row in rows]

    async def handle(self, topic: str, event: dict[str, Any]) -> None:
        notification = None
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            cursor = await db.execute(
                "INSERT INTO processed_events(event_id,topic) VALUES "
                "(%s,%s) ON CONFLICT DO NOTHING RETURNING event_id",
                (event["event_id"], topic),
            )
            if await cursor.fetchone() is None:
                return
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE id=%s AND deleted_at IS NULL FOR UPDATE",
                (event["correlation_id"],),
            )
            job = await cursor.fetchone()
            if job is None or job["status"] in {"completed", "failed", "rejected"}:
                return
            payload = event["payload"]
            status, output, error = job["status"], None, None
            if topic == "skill.results":
                if payload["skill"] != job["skill"]:
                    return
                status, output, error = (
                    payload["status"],
                    payload["output"],
                    payload["error"],
                )
            elif job["status"] == "awaiting_approval":
                if not payload["approved"]:
                    status, error = (
                        "rejected",
                        {
                            "code": "approval_rejected",
                            "message": "An admin did not approve this job.",
                        },
                    )
                else:
                    try:
                        _, skills = await self.upstream.permissions(job["user_id"])
                        skill = next(
                            (value for value in skills if value.name == job["skill"]),
                            None,
                        )
                        if skill is None:
                            status, error = (
                                "failed",
                                {
                                    "code": "right_removed",
                                    "message": "The skill right was removed.",
                                },
                            )
                        else:
                            await self.publisher.publish(
                                skill.topic,
                                envelope(
                                    "skill.requested",
                                    str(job["id"]),
                                    job["user_id"],
                                    {
                                        "skill": job["skill"],
                                        "skill_version": job["skill_version"],
                                        "input": job["input"],
                                    },
                                    event["event_id"],
                                ),
                            )
                            status = "queued"
                    except ApiError:
                        status, error = (
                            "failed",
                            {
                                "code": "rights_unavailable",
                                "message": "Rights could not be checked.",
                            },
                        )
            else:
                return
            await db.execute(
                "UPDATE jobs SET "
                "status=%s,output=%s,error=%s,updated_at=clock_timestamp(),"
                "updated_by='harness-api' WHERE id=%s",
                (status, Jsonb(output), Jsonb(error), job["id"]),
            )
            notification = {
                "type": "job." + ("failed" if status == "rejected" else status),
                "correlation_id": str(job["id"]),
                "skill": job["skill"],
                "output": output,
                "error": error,
            }
        if notification:
            self.events.emit(job["user_id"], notification)


def download_path(root: str, job: dict[str, Any]) -> Path:
    if job["status"] != "completed" or not isinstance(job["output"], dict):
        raise ApiError(404, "not_found", "File not found.")
    base = (Path(root) / "outputs").resolve()
    path = (Path(root) / job["output"]["file_key"]).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ApiError(404, "not_found", "File not found.")
    return path
