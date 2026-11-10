# SPDX-License-Identifier: AGPL-3.0-only
import time
from typing import Any

import httpx
import jwt

from .config import Settings
from .errors import ApiError


class Auth:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client
        self.keys: dict[str, Any] = {}
        self.keys_until = 0.0
        self.token = ""
        self.token_until = 0.0

    async def verify(self, authorization: str | None) -> dict[str, Any]:
        try:
            if not authorization or not authorization.startswith("Bearer "):
                raise ValueError
            token = authorization[7:]
            header = jwt.get_unverified_header(token)
            kid = header["kid"]
            if time.monotonic() >= self.keys_until or kid not in self.keys:
                response = await self.client.get(
                    f"{self.settings.issuer}/protocol/openid-connect/certs"
                )
                response.raise_for_status()
                keys = jwt.PyJWKSet.from_dict(response.json())
                self.keys = {key.key_id: key.key for key in keys.keys}
                self.keys_until = time.monotonic() + 300
            claims = jwt.decode(
                token,
                self.keys[kid],
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=self.settings.audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            if not isinstance(claims["sub"], str) or not claims["sub"].strip():
                raise ValueError
            # Only interactive users may use the browser API.
            if claims.get("azp") != "ooh-workspace":
                raise ValueError
            return claims
        except ValueError, KeyError, TypeError, jwt.PyJWTError, httpx.HTTPError:
            raise ApiError(401, "unauthorized", "Sign in to continue.") from None

    async def service_token(self) -> str:
        if time.monotonic() < self.token_until:
            return self.token
        response = await self.client.post(
            f"{self.settings.issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
            },
        )
        response.raise_for_status()
        body = response.json()
        self.token = body["access_token"]
        if not isinstance(self.token, str) or not self.token:
            raise ValueError
        self.token_until = time.monotonic() + max(0, int(body["expires_in"]) - 30)
        return self.token
