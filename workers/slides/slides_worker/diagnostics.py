# SPDX-License-Identifier: AGPL-3.0-only
import builtins
import json
import logging
import re

BUILTIN_EXCEPTIONS = frozenset(
    name
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
)


EVENTS = frozenset(
    {
        "authentication_error",
        "rights_error",
        "gateway_error",
        "database_error",
        "token_error",
        "request_error",
        "title_failed",
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
        "registry_unavailable",
        "forbidden",
        "not_approved",
        "tier_not_requestable",
        "already_requested",
        "too_soon",
        "too_many_requests",
    }
)


def failure(event: str, code: str, tier: int | None = None) -> None:
    logging.getLogger("harness_api").warning(
        "service_failure",
        extra={
            "event": event,
            "code": code if code in CODES else "unavailable",
            "tier": tier,
        },
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
        else:
            exception = (
                record.exc_info[0].__name__
                if record.exc_info and record.exc_info[0]
                else None
            )
            message_class = "server_event"
            if isinstance(record.msg, BaseException):
                exception = type(record.msg).__name__
                message_class = "startup_error"
            elif record.exc_info:
                message_class = "unhandled_exception"
            elif isinstance(record.msg, str):
                if record.msg.startswith("Traceback (most recent call last):"):
                    message_class = "lifecycle_failed"
                    matches = re.findall(
                        r"^([A-Za-z_][A-Za-z0-9_.]{0,63}):", record.msg, re.MULTILINE
                    )
                    known = [name for name in matches if name in BUILTIN_EXCEPTIONS]
                    exception = known[-1] if known else None
                else:
                    for prefix, category in (
                        ("Started server process", "server_started"),
                        ("Waiting for application startup", "startup_wait"),
                        ("Application startup complete", "startup_completed"),
                        ("Application startup failed", "startup_failed"),
                        ("Exception in ASGI application", "request_failed"),
                        ("Shutting down", "shutdown"),
                    ):
                        if record.msg.startswith(prefix):
                            message_class = category
                            break
            body.update(
                logger=record.name,
                message_class=message_class,
                exception_type=exception,
            )
        return json.dumps(body)
