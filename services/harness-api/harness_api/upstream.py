# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, StrictBool, StrictInt, TypeAdapter

from .auth import Auth
from .config import Settings
from .errors import ApiError, gateway_error


class Rights(BaseModel):
    chat_tiers: list[Annotated[StrictInt, Field(gt=0)]]
    skills: list[str]


class Skill(BaseModel):
    name: str
    title: str
    description: str
    input_schema: str


class Decision(BaseModel):
    allowed: StrictBool


class Usage(BaseModel):
    input_tokens: Annotated[StrictInt, Field(ge=0)]
    output_tokens: Annotated[StrictInt, Field(ge=0)]


class Delta(BaseModel):
    type: Literal["delta"]
    text: str


class ToolCall(BaseModel):
    type: Literal["tool_call"]
    id: str
    name: str
    arguments: dict[str, Any]


class Completed(BaseModel):
    type: Literal["completed"]
    model_entry_id: UUID
    model_title: str
    tier: Annotated[StrictInt, Field(gt=0)]
    usage: Usage


class ErrorBody(BaseModel):
    code: str
    message: str


class Failed(BaseModel):
    type: Literal["failed"]
    error: ErrorBody


EVENT = TypeAdapter(
    Annotated[Delta | ToolCall | Completed | Failed, Field(discriminator="type")]
)
SKILLS = TypeAdapter(list[Skill])


class GatewayStream:
    def __init__(self, response: httpx.Response, tier: int) -> None:
        self.response = response
        self.tier = tier
        self.events = self.parse()

    async def parse(self) -> AsyncIterator[dict[str, Any]]:
        data: list[str] = []
        async for line in self.response.aiter_lines():
            if not line:
                if data:
                    event = EVENT.validate_json("\n".join(data)).model_dump(mode="json")
                    data.clear()
                    if event["type"] == "completed" and event["tier"] != self.tier:
                        raise ValueError("Gateway tier differs from requested tier")
                    yield event
                continue
            if line.startswith("data:"):
                value = line[5:]
                data.append(value[1:] if value.startswith(" ") else value)
        if data:
            raise ValueError("Incomplete Gateway event")

    async def close(self) -> None:
        await self.response.aclose()


class Upstream:
    def __init__(
        self, settings: Settings, client: httpx.AsyncClient, auth: Auth
    ) -> None:
        self.settings = settings
        self.client = client
        self.auth = auth
        folder = Path(__file__).parent / "schemas"
        self.schemas = {
            file.stem: json.loads(file.read_text()) for file in folder.glob("*.json")
        }

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.auth.service_token()}"}

    async def permissions(self, user: str) -> tuple[list[int], list[Skill]]:
        try:
            headers = await self.headers()
            rights = await self.client.get(
                f"{self.settings.control_centre}/api/rights/me",
                params={"user_id": user},
                headers=headers,
            )
            rights.raise_for_status()
            body = Rights.model_validate(rights.json())
            skills = await self.client.get(
                f"{self.settings.control_centre}/api/skills",
                params={"user_id": user},
                headers=headers,
            )
            skills.raise_for_status()
            allowed = [
                skill
                for skill in SKILLS.validate_python(skills.json())
                if skill.name in body.skills
            ]
            return sorted(set(body.chat_tiers)), allowed
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise self.rights_error() from None

    @staticmethod
    def rights_error() -> ApiError:
        return ApiError(
            503, "rights_unavailable", "Rights could not be checked. Try again."
        )

    async def check(self, user: str, tier: int) -> None:
        try:
            response = await self.client.post(
                f"{self.settings.control_centre}/api/rights/check",
                headers=await self.headers(),
                json={"user_id": user, "action": "chat.tier", "target": str(tier)},
            )
            response.raise_for_status()
            allowed = Decision.model_validate(response.json()).allowed
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise self.rights_error() from None
        if not allowed:
            raise ApiError(
                403,
                "tier_not_allowed",
                f"You don't have tier {tier}. An admin can grant it.",
            )

    def tools(self, skills: list[Skill]) -> list[dict[str, Any]]:
        tools = []
        for skill in skills:
            if skill.name not in self.schemas:
                continue
            if skill.input_schema != f"contracts/skills/{skill.name}/input.schema.json":
                raise self.rights_error()
            tools.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "input_schema": self.schemas[skill.name],
                }
            )
        return tools

    async def open(
        self,
        user: str,
        tier: int,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> GatewayStream:
        response = None
        try:
            request = self.client.build_request(
                "POST",
                f"{self.settings.gateway}/v1/call",
                headers=await self.headers(),
                json={
                    "purpose": "chat",
                    "tier": tier,
                    "user_id": user,
                    "messages": messages,
                    "tools": tools,
                    "stream": True,
                },
                timeout=httpx.Timeout(10, read=910),
            )
            response = await self.client.send(request, stream=True)
            if response.status_code != 200:
                await response.aread()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Invalid Gateway error")
                code = body.get("code", "unavailable")
                raise gateway_error(code, tier)
            if (
                response.headers.get("content-type", "").split(";")[0]
                != "text/event-stream"
            ):
                raise ValueError("Gateway response is not an event stream")
            return GatewayStream(response, tier)
        except (ApiError, httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            if response is not None:
                await response.aclose()
            if isinstance(error, ApiError):
                raise
            raise gateway_error("unavailable", tier) from None
