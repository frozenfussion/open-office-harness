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

TITLE_PROMPT = (
    "Write a short title (3 to 6 words) for this conversation. "
    "Reply with the title only, no quotes, no full stop."
)


class TitleContent(BaseModel):
    content: str


class AccessStatus(BaseModel):
    status: Literal["approved", "pending", "rejected", "closed"]


class RequestableTier(BaseModel):
    tier: Annotated[StrictInt, Field(gt=0)]
    title: str
    requested: Literal["pending", "rejected"] | None


class TierRequestResult(BaseModel):
    id: UUID
    status: Literal["pending"]


class Rights(BaseModel):
    chat_tiers: list[Annotated[StrictInt, Field(gt=0)]]
    skills: list[str]
    chat_tier_titles: dict[str, str] = Field(default_factory=dict)
    chat_tier_thinking_switch: dict[str, StrictBool] = Field(default_factory=dict)
    requestable_tiers: list[RequestableTier] = Field(default_factory=list)


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


class Thinking(BaseModel):
    type: Literal["thinking"]
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
    thinking_applied: StrictBool


class ErrorBody(BaseModel):
    code: str
    message: str


class Failed(BaseModel):
    type: Literal["failed"]
    error: ErrorBody


EVENT = TypeAdapter(
    Annotated[
        Delta | Thinking | ToolCall | Completed | Failed, Field(discriminator="type")
    ]
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
                    body = json.loads("\n".join(data))
                    data.clear()
                    if (
                        isinstance(body, dict)
                        and isinstance(body.get("type"), str)
                        and body["type"]
                        not in {"delta", "thinking", "tool_call", "completed", "failed"}
                    ):
                        continue
                    try:
                        event = EVENT.validate_python(body).model_dump(mode="json")
                    except ValueError:
                        raise ValueError("Unexpected Gateway event") from None
                    if event["type"] == "thinking" and event["text"] == "":
                        continue
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

    async def observe(self, claims: dict[str, Any]) -> str:
        body: dict[str, Any] = {"user_id": claims["sub"]}
        for field, limit in (
            ("name", 200),
            ("email", 320),
            ("organisation", 100),
            ("access_reason", 300),
        ):
            value = claims.get(field)
            body[field] = value.strip()[:limit] if isinstance(value, str) else None
        realm = claims.get("realm_access")
        roles = realm.get("roles") if isinstance(realm, dict) else None
        body["is_admin"] = isinstance(roles, list) and "ooh-admin" in roles
        try:
            response = await self.client.post(
                f"{self.settings.control_centre}/api/access/observe",
                headers=await self.headers(),
                json=body,
            )
            response.raise_for_status()
            return AccessStatus.model_validate(response.json()).status
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise self.rights_error() from None

    async def permissions(self, user: str) -> tuple[Rights, list[Skill]]:
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
            body.chat_tiers = sorted(set(body.chat_tiers))
            return body, allowed
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

    async def request_tier(
        self, user: str, tier: int, reason: str | None
    ) -> dict[str, Any]:
        try:
            response = await self.client.post(
                f"{self.settings.control_centre}/api/tier-requests",
                headers=await self.headers(),
                json={"user_id": user, "tier": tier, "reason": reason},
            )
            if response.status_code == 201:
                return TierRequestResult.model_validate(response.json()).model_dump(
                    mode="json"
                )
            errors = {
                (
                    403,
                    "not_approved",
                ): "Your access must be approved before requesting a model.",
                (400, "tier_not_requestable"): "This tier cannot be requested.",
                (409, "already_requested"): "You have already requested this tier.",
                (409, "too_soon"): (
                    "You can ask for this model again 7 days after the last answer."
                ),
                (
                    429,
                    "too_many_requests",
                ): "You already have 20 pending model requests.",
            }
            body = response.json()
            code = body.get("code") if isinstance(body, dict) else None
            if not isinstance(code, str) or (response.status_code, code) not in errors:
                raise ValueError("Unexpected tier request response")
            raise ApiError(
                response.status_code, code, errors[(response.status_code, code)]
            )
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise self.rights_error() from None

    async def title(self, user: str, tier: int, question: str, answer: str) -> str:
        response = await self.client.post(
            f"{self.settings.gateway}/v1/call",
            headers=await self.headers(),
            json={
                "purpose": "chat",
                "tier": tier,
                "user_id": f"title-{user}",
                "messages": [
                    {"role": "system", "content": TITLE_PROMPT},
                    {"role": "user", "content": question[:2000]},
                    {"role": "assistant", "content": answer[:2000]},
                ],
                "tools": [],
                "stream": False,
                "thinking": False,
            },
            timeout=httpx.Timeout(20),
        )
        if response.status_code != 200:
            body = response.json()
            code = (
                body.get("code", "unavailable")
                if isinstance(body, dict)
                else "unavailable"
            )
            if not isinstance(code, str):
                code = "unavailable"
            raise ApiError(response.status_code, code, "Title could not be made.")
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("content"), str):
            raise ValueError("Unexpected title answer")
        content = TitleContent.model_validate({"content": body["content"]}).content
        title = (
            content.strip()
            .strip("\"'“”‘’")
            .strip()
            .removesuffix(".")
            .strip()
            .strip("\"'“”‘’")
            .strip()[:60]
        )
        if not title:
            raise ValueError("Empty title")
        return title

    async def open(
        self,
        user: str,
        tier: int,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        thinking: bool = True,
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
                    "messages": (
                        [{"role": "system", "content": self.settings.system_prompt}]
                        if self.settings.system_prompt
                        else []
                    )
                    + messages,
                    "tools": tools,
                    "stream": True,
                    "thinking": thinking,
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
