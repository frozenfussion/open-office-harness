# SPDX-License-Identifier: AGPL-3.0-only
import builtins
import json
import logging
import re
import sys

import uvicorn

from consumer.app import create_app

BUILTIN_EXCEPTIONS = frozenset(
    name
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if record.name == "consumer":
            return record.getMessage()
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
        return json.dumps(
            {
                "level": record.levelname,
                "logger": record.name,
                "message_class": message_class,
                "exception_type": exception,
            }
        )


def main() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    if not sys.argv[1:]:
        uvicorn.run(
            create_app(), host="0.0.0.0", port=8080, access_log=False, log_config=None
        )
    else:
        raise SystemExit("usage: python -m consumer [migrate]")


if __name__ == "__main__":
    main()
