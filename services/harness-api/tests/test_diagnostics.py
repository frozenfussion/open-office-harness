# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging
from typing import Any

import pytest

from harness_api.diagnostics import JsonFormatter

PRIVATE = "synthetic-private-chat-token-value"


@pytest.mark.parametrize(
    "message,exc_info,category,exception",
    [
        (
            "Exception in ASGI application %s",
            (RuntimeError, RuntimeError(PRIVATE), None),
            "unhandled_exception",
            "RuntimeError",
        ),
        (OSError(PRIVATE), None, "startup_error", "OSError"),
        (
            f"Traceback (most recent call last):\n  {PRIVATE}\nKeyError: {PRIVATE}\n",
            None,
            "lifecycle_failed",
            "KeyError",
        ),
        (
            f"Traceback (most recent call last):\n{PRIVATE}: {PRIVATE}\n",
            None,
            "lifecycle_failed",
            None,
        ),
        (f"Application startup failed {PRIVATE}", None, "startup_failed", None),
        (f"Started server process {PRIVATE}", None, "server_started", None),
        (f"Unexpected server text {PRIVATE}", None, "server_event", None),
    ],
)
def test_server_logs_preserve_safe_diagnostics(
    message: Any, exc_info: Any, category: str, exception: str | None
) -> None:
    record = logging.LogRecord(
        "uvicorn.error", logging.ERROR, PRIVATE, 1, message, (), exc_info
    )
    record.stack_info = PRIVATE
    record.exc_text = PRIVATE
    encoded = JsonFormatter().format(record)
    assert json.loads(encoded) == {
        "level": "error",
        "event": "service_log",
        "logger": "uvicorn.error",
        "message_class": category,
        "exception_type": exception,
    }
    assert PRIVATE not in encoded
