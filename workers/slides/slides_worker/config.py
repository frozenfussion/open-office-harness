# SPDX-License-Identifier: AGPL-3.0-only
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap: str
    kafka_username: str
    kafka_password: str = field(repr=False)
    issuer: str
    client_id: str
    client_secret: str = field(repr=False)
    gateway_url: str
    files_root: str = "/files"
    purpose: str = "chat"
    tier: int = 1

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            kafka_bootstrap=os.environ["SW_KAFKA_BOOTSTRAP"],
            kafka_username=os.environ["SW_KAFKA_USERNAME"],
            kafka_password=os.environ["SW_KAFKA_PASSWORD"],
            issuer=os.environ["SW_OIDC_ISSUER"].rstrip("/"),
            client_id=os.environ["SW_CLIENT_ID"],
            client_secret=os.environ["SW_CLIENT_SECRET"],
            gateway_url=os.environ["SW_GATEWAY_URL"].rstrip("/"),
            files_root=os.environ.get("SW_FILES_ROOT", "/files"),
            purpose=os.environ.get("SW_PURPOSE", "chat"),
            tier=int(os.environ.get("SW_TIER", "1")),
        )
