# SPDX-License-Identifier: AGPL-3.0-only
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Config:
    prefix: str = "CM"
    name: str = "cost-meter"
    issuer: str = ""
    audience: str = "ooh-cost-meter"
    client_id: str = "ooh-cost-meter"
    client_secret: str = field(default="", repr=False)
    db: str = field(default="", repr=False)
    bootstrap: str = ""
    username: str = "cost-meter"
    password: str = field(default="", repr=False)
    gateway_url: str = ""
    questions: dict[str, str] = field(default_factory=dict)
    threshold: float = 0.8

    @classmethod
    def environment(cls) -> Config:
        prefix = "CM"
        values: dict[str, Any] = {
            "issuer": os.environ[prefix + "_OIDC_ISSUER"],
            "bootstrap": os.environ[prefix + "_KAFKA_BOOTSTRAP"],
            "username": os.environ[prefix + "_KAFKA_USERNAME"],
            "password": os.environ[prefix + "_KAFKA_PASSWORD"],
        }
        if prefix == "SF":
            questions = json.loads(os.environ["SF_QUESTIONS"])
            threshold = float(os.environ.get("SF_THRESHOLD", "0.8"))
            if (
                not isinstance(questions, dict)
                or not 1 <= len(questions) <= 10
                or any(
                    not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", k)
                    or not isinstance(v, str)
                    or not v
                    for k, v in questions.items()
                )
                or not math.isfinite(threshold)
                or not 0 <= threshold <= 1
            ):
                raise ValueError("invalid safety settings")
            values.update(
                questions=questions,
                threshold=threshold,
                gateway_url=os.environ["SF_GATEWAY_URL"],
                client_secret=os.environ["SF_CLIENT_SECRET"],
            )
        else:
            values["db"] = os.environ[prefix + "_DB_CONNECTION"]
        return cls(**values)
