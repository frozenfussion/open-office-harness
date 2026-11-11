# SPDX-License-Identifier: AGPL-3.0-only
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolCall(Strict):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class Message(Strict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning_state: dict[str, Any] | None = None
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def valid_role(self) -> Message:
        if self.role == "tool" and (not self.tool_call_id or self.content is None):
            raise ValueError("tool result requires id and content")
        if self.role != "tool" and self.tool_call_id is not None:
            raise ValueError("only tool results have tool_call_id")
        if self.role != "assistant" and (self.tool_calls or self.reasoning_state):
            raise ValueError("only assistant messages have provider state")
        if self.content is None and not self.tool_calls:
            raise ValueError("content required")
        return self


class Tool(Strict):
    name: str = Field(min_length=1)
    description: str
    input_schema: dict[str, Any]


class ToolChoice(Strict):
    name: str = Field(min_length=1)


class Call(Strict):
    purpose: str = Field(min_length=1)
    tier: int | None = Field(default=None, ge=1)
    user_id: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=1)
    tools: list[Tool] = Field(default_factory=list)
    stream: bool
    thinking: StrictBool = True
    model_entry_id: UUID | None = None
    tool_choice: ToolChoice | Literal["none"] | None = None

    @model_validator(mode="after")
    def chat_tier(self) -> Call:
        if self.purpose == "chat" and self.tier is None:
            raise ValueError("chat requires tier")
        if self.purpose != "chat" and self.tier is not None:
            raise ValueError("tier is only for chat")
        if isinstance(self.tool_choice, ToolChoice) and self.tool_choice.name not in {
            t.name for t in self.tools
        }:
            raise ValueError("chosen tool not offered")
        return self


class Classify(Strict):
    text: str = Field(min_length=1, max_length=20000)
    questions: dict[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")],
        Annotated[str, Field(min_length=1)],
    ] = Field(min_length=1, max_length=10)
    user_id: str = Field(min_length=1)
    model_entry_id: UUID | None = None


class Entry(BaseModel):
    id: UUID = Field(alias="model_entry_id")
    title: str
    purpose: str
    tier: int | None = None
    role: Literal["main", "backup"]
    priority: int = Field(default=100, ge=1, le=1000)
    created_at: datetime
    deleted_at: str | None = None
    api_type: str
    endpoint_url: str
    model_id: str
    has_key: bool = False
    rate_limit_per_minute: int = Field(ge=1)
    daily_budget: Decimal = Field(ge=0)
    input_price_per_million: Decimal = Field(default=Decimal(0), ge=0)
    output_price_per_million: Decimal = Field(default=Decimal(0), ge=0)
    timeout_seconds: int = Field(default=120, ge=10, le=900)
    request_settings: dict[str, Any] = Field(default_factory=dict)
    request_settings_thinking_off: dict[str, Any] | None = None


class GatewayError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        provider_status: int | None = None,
        provider_message: str | None = None,
    ) -> None:
        self.status, self.code, self.message = status, code, message
        self.provider_status, self.provider_message = provider_status, provider_message
        super().__init__(code)

    def body(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}
