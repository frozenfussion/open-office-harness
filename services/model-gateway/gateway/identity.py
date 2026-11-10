# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import time
from typing import Any

import httpx
import jwt

from gateway.config import Config
from gateway.models import GatewayError


class Identity:
    def __init__(self, config: Config, client: httpx.AsyncClient) -> None:
        self.config, self.client = config, client
        self.keys: dict[str, Any] = {}
        self.keys_until = 0.0
        self.keys_refresh_after = 0.0
        self.keys_lock = asyncio.Lock()
        self.token = ""
        self.token_until = 0.0

    async def authenticate(self, authorization: str | None) -> dict[str, Any]:
        try:
            if not authorization or not authorization.startswith("Bearer "):
                raise ValueError()
            token = authorization[7:]
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise ValueError()
            async with self.keys_lock:
                now = time.monotonic()
                if (
                    now >= self.keys_until or header.get("kid") not in self.keys
                ) and now >= self.keys_refresh_after:
                    # Throttle attempts as well as successes, including concurrent junk tokens.
                    self.keys_refresh_after = now + 30
                    response = await self.client.get(
                        self.config.issuer + "/protocol/openid-connect/certs"
                    )
                    response.raise_for_status()
                    self.keys = {
                        key["kid"]: jwt.PyJWK.from_dict(key).key
                        for key in response.json()["keys"]
                        if key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
                    }
                    self.keys_until = time.monotonic() + 300
                if now >= self.keys_until:
                    raise ValueError()
            claims = jwt.decode(
                token,
                self.keys[header["kid"]],
                algorithms=["RS256"],
                issuer=self.config.issuer,
                audience=self.config.audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise ValueError()
            return claims
        except ValueError, KeyError, TypeError, httpx.HTTPError, jwt.PyJWTError:
            raise GatewayError(
                401, "unauthorized", "A valid service token is required"
            ) from None

    async def service_token(self) -> str:
        if time.monotonic() < self.token_until:
            return self.token
        response = await self.client.post(
            self.config.issuer + "/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
        )
        response.raise_for_status()
        value = response.json()
        self.token = value["access_token"]
        self.token_until = time.monotonic() + max(0, float(value["expires_in"]) - 30)
        return self.token
