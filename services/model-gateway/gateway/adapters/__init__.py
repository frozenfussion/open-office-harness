# SPDX-License-Identifier: AGPL-3.0-only
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from gateway.models import Call, Entry

from . import anthropic_messages, openai_chat_completions, openai_responses

ADAPTERS = {
    module.__name__.rsplit(".", 1)[1]: module.run
    for module in (openai_chat_completions, openai_responses, anthropic_messages)
}


def resolve(
    entry: Entry,
) -> (
    Callable[[httpx.AsyncClient, Entry, str, Call], AsyncIterator[dict[str, Any]]]
    | None
):
    return ADAPTERS.get(entry.api_type)
