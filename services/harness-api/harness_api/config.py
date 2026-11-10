# SPDX-License-Identifier: AGPL-3.0-only
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database: str
    issuer: str
    audience: str
    client_id: str
    client_secret: str
    control_centre: str
    gateway: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database=os.environ["HA_DB_CONNECTION"],
            issuer=os.environ["HA_OIDC_ISSUER"].rstrip("/"),
            audience=os.environ["HA_OIDC_AUDIENCE"],
            client_id=os.environ["HA_CLIENT_ID"],
            client_secret=os.environ["HA_CLIENT_SECRET"],
            control_centre=os.environ["HA_CONTROL_CENTRE_URL"].rstrip("/"),
            gateway=os.environ["HA_GATEWAY_URL"].rstrip("/"),
        )
