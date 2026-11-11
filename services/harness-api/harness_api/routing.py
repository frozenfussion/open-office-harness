# SPDX-License-Identifier: AGPL-3.0-only
import math
from typing import Any
from uuid import UUID

import httpx

from .errors import ApiError
from .upstream import Skill, Upstream


async def route(
    upstream: Upstream,
    user: str,
    text: str,
    lowest: int,
    skills: list[Skill],
    correlation: UUID,
) -> dict[str, Any]:
    settings = upstream.settings
    result: dict[str, Any] = {"tier": lowest, "scores": {}}
    questions = {"needs_tier2": settings.route_tier_question}
    questions.update(
        {
            "wants_" + skill.name.replace("-", "_"): (
                f"Is the user asking for this: {skill.description}?"
            )
            for skill in skills
        }
    )
    try:
        if not settings.route_tier_question:
            raise ValueError("Routing question is not configured")
        response = await upstream.client.post(
            f"{settings.gateway}/v1/classify",
            headers={
                **await upstream.headers(),
                "X-Correlation-Id": str(correlation),
            },
            json={"text": text, "questions": questions, "user_id": user},
            timeout=httpx.Timeout(10, read=910),
        )
        response.raise_for_status()
        scores = response.json()["scores"]
        if not isinstance(scores, dict) or any(
            type(scores.get(key)) not in (int, float)
            or not math.isfinite(scores[key])
            or not 0 <= scores[key] <= 1
            for key in questions
        ):
            raise ValueError("Invalid routing scores")
        result["scores"] = {key: scores[key] for key in questions}
    except httpx.HTTPError, ApiError, ValueError, KeyError, TypeError:
        result["note"] = f"Routing is unavailable; answered with tier {lowest}."
        return result
    if scores["needs_tier2"] >= settings.route_tier_threshold:
        try:
            await upstream.check(user, settings.route_up_tier)
            result["tier"] = settings.route_up_tier
        except ApiError:
            result["note"] = (
                f"This question may need tier {settings.route_up_tier}. "
                f"An admin can give you tier {settings.route_up_tier}."
            )
    if skills:
        skill = max(
            skills, key=lambda item: scores["wants_" + item.name.replace("-", "_")]
        )
        if (
            scores["wants_" + skill.name.replace("-", "_")]
            >= settings.route_skill_threshold
        ):
            result["skill"] = skill.name
    return result
