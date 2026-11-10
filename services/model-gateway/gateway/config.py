# SPDX-License-Identifier: AGPL-3.0-only
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    db: str
    issuer: str
    audience: str
    client_id: str
    client_secret: str
    registry_url: str

    @classmethod
    def environment(cls) -> Config:
        return cls(
            *(
                os.environ[name]
                for name in (
                    "GW_DB_CONNECTION",
                    "GW_OIDC_ISSUER",
                    "GW_OIDC_AUDIENCE",
                    "GW_CLIENT_ID",
                    "GW_CLIENT_SECRET",
                    "GW_CONTROL_CENTRE_URL",
                )
            )
        )
