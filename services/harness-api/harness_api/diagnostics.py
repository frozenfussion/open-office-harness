# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging

EVENTS = frozenset(
    {
        "authentication_error",
        "rights_error",
        "gateway_error",
        "database_error",
        "token_error",
        "request_error",
    }
)
CODES = frozenset(
    {
        "unauthorized",
        "rights_unavailable",
        "tier_not_allowed",
        "no_tier",
        "no_model",
        "rate_limited",
        "budget_exceeded",
        "unavailable",
        "invalid_input",
        "not_found",
        "not_built_yet",
    }
)


def failure(event: str, code: str, tier: int | None = None) -> None:
    logging.getLogger("harness_api").warning(
        "service_failure", extra={"event": event, "code": code, "tier": tier}
    )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", None)
        code = getattr(record, "code", None)
        body = {"level": record.levelname.lower(), "event": "service_log"}
        if isinstance(event, str) and event in EVENTS:
            body["event"] = event
            body["code"] = (
                code if isinstance(code, str) and code in CODES else "unavailable"
            )
            tier = getattr(record, "tier", None)
            if type(tier) is int and tier > 0:
                body["tier"] = tier
        return json.dumps(body)
