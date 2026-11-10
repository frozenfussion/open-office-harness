# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import time
from typing import Any

import httpx
import jwt

from .config import Settings
from .diagnostics import failure
from .errors import ApiError


class Auth:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client
        self.keys: dict[str, Any] = {}
        self.keys_until = 0.0
        self.keys_refresh_after = 0.0
        self.keys_lock = asyncio.Lock()
        self.token = ""
        self.token_until = 0.0

    async def verify(self, authorization: str | None) -> dict[str, Any]:
        try:
            if not authorization or not authorization.startswith("Bearer "):
                raise ValueError
            token = authorization[7:]
            header = jwt.get_unverified_header(token)
            kid = header["kid"]
            if not isinstance(kid, str) or not kid or header.get("alg") != "RS256":
                raise ValueError
            await self.refresh_keys(kid)
            if time.monotonic() >= self.keys_until:
                raise ValueError
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
            return claims
        except ValueError, KeyError, TypeError, jwt.PyJWTError, httpx.HTTPError:
            raise ApiError(401, "unauthorized", "Sign in to continue.") from None

    async def refresh_keys(self, kid: str) -> None:
        async with self.keys_lock:
            now = time.monotonic()
            if now < self.keys_refresh_after:
                return
            if now < self.keys_until and kid in self.keys:
                return
            # Throttle failed fetches too; untrusted kids must not flood Keycloak.
            self.keys_refresh_after = now + 30
            response = await self.client.get(
                f"{self.settings.issuer}/protocol/openid-connect/certs"
            )
            response.raise_for_status()
            keys = jwt.PyJWKSet.from_dict(response.json())
            self.keys = {key.key_id: key.key for key in keys.keys}
            self.keys_until = time.monotonic() + 300

    async def service_token(self) -> str:
        if time.monotonic() < self.token_until:
            return self.token
        try:
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
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            failure("token_error", "unavailable")
            raise
