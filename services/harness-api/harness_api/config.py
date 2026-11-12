# SPDX-License-Identifier: AGPL-3.0-only
import os
from dataclasses import dataclass, field

DEFAULT_SYSTEM_PROMPT = (
    "You are the assistant in Open Office Harness. "
    "Always reply in the same language as the user's latest message."
)


@dataclass(frozen=True)
class Settings:
    database: str
    issuer: str
    audience: str
    client_id: str
    client_secret: str
    control_centre: str
    gateway: str
    system_prompt: str = field(default=DEFAULT_SYSTEM_PROMPT, repr=False)

    kafka_bootstrap: str = ""
    kafka_username: str = "harness-api"
    kafka_password: str = field(default="", repr=False)
    files_root: str = "/files"
    route_tier_question: str = ""
    route_tier_threshold: float = 0.5
    route_up_tier: int = 2
    route_skill_threshold: float = 0.8
    route_timeout_seconds: float = 30

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            route_timeout_seconds=float(
                os.environ.get("HA_ROUTE_TIMEOUT_SECONDS", "30")
            ),
            route_tier_question=os.environ.get("HA_ROUTE_TIER_QUESTION", ""),
            route_tier_threshold=float(
                os.environ.get("HA_ROUTE_TIER_THRESHOLD", "0.5")
            ),
            route_up_tier=int(os.environ.get("HA_ROUTE_UP_TIER", "2")),
            route_skill_threshold=float(
                os.environ.get("HA_ROUTE_SKILL_THRESHOLD", "0.8")
            ),
            kafka_bootstrap=os.environ.get("HA_KAFKA_BOOTSTRAP", ""),
            kafka_username=os.environ.get("HA_KAFKA_USERNAME", "harness-api"),
            kafka_password=os.environ.get("HA_KAFKA_PASSWORD", ""),
            files_root=os.environ.get("HA_FILES_ROOT", "/files"),
            database=os.environ["HA_DB_CONNECTION"],
            issuer=os.environ["HA_OIDC_ISSUER"].rstrip("/"),
            audience=os.environ["HA_OIDC_AUDIENCE"],
            client_id=os.environ["HA_CLIENT_ID"],
            client_secret=os.environ["HA_CLIENT_SECRET"],
            control_centre=os.environ["HA_CONTROL_CENTRE_URL"].rstrip("/"),
            gateway=os.environ["HA_GATEWAY_URL"].rstrip("/"),
            system_prompt=os.environ.get("HA_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        )
