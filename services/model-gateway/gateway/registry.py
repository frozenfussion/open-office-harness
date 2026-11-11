# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging
import time
from uuid import UUID

import httpx

from gateway.config import Config
from gateway.identity import Identity
from gateway.models import Entry, GatewayError

logger = logging.getLogger("gateway")


class Registry:
    def __init__(
        self, config: Config, client: httpx.AsyncClient, identity: Identity
    ) -> None:
        self.config, self.client, self.identity = config, client, identity
        self.entries: dict[tuple[str, int | None], tuple[float, list[Entry]]] = {}
        self.keys: dict[UUID, tuple[float, str]] = {}

    async def get(self, purpose: str, tier: int | None) -> list[Entry]:
        cache_key = purpose, tier
        cached = self.entries.get(cache_key)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        status = None
        try:
            token = await self.identity.service_token()
            params = {"purpose": purpose}
            if tier is not None:
                params["tier"] = str(tier)
            response = await self.client.get(
                self.config.registry_url + "/api/models",
                params=params,
                headers={"Authorization": "Bearer " + token},
            )
            status = response.status_code
            response.raise_for_status()
            entries = [Entry.model_validate(value) for value in response.json()]
            self.entries[cache_key] = time.monotonic() + 30, entries
            return entries
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            status = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else status
            )
            reason = (
                "unauthorized"
                if status in (401, 403)
                else "unreachable"
                if isinstance(error, httpx.RequestError)
                else "bad answer"
            )
            logger.warning(
                json.dumps(
                    {
                        "message": "registry " + reason,
                        "reason": reason,
                        "status": status,
                    }
                )
            )
            raise GatewayError(
                503, "registry_unavailable", "The model registry did not answer"
            ) from None

    async def key(self, entry: Entry) -> str:
        cached = self.keys.get(entry.id)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        status = None
        try:
            token = await self.identity.service_token()
            response = await self.client.get(
                f"{self.config.registry_url}/api/models/{entry.id}/key",
                headers={"Authorization": "Bearer " + token},
            )
            status = response.status_code
            if response.status_code == 404 and not entry.has_key:
                self.keys[entry.id] = time.monotonic() + 60, ""
                return ""
            response.raise_for_status()
            key = response.json()["api_key"]
            if not isinstance(key, str) or not key:
                raise ValueError()
            self.keys[entry.id] = time.monotonic() + 60, key
            return key
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            status = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else status
            )
            reason = (
                "unauthorized"
                if status in (401, 403)
                else "missing"
                if status == 404
                else "unreachable"
                if isinstance(error, httpx.RequestError)
                else "bad answer"
            )
            logger.warning(
                json.dumps(
                    {
                        "message": "key unavailable",
                        "model_entry_id": str(entry.id),
                        "status": status,
                        "reason": reason,
                    }
                )
            )
            raise

    async def report_health(
        self, entry: Entry, status: str, reason: str | None
    ) -> None:
        try:
            token = await self.identity.service_token()
            response = await self.client.post(
                f"{self.config.registry_url}/api/models/{entry.id}/health",
                headers={"Authorization": "Bearer " + token},
                json={"status": status, "reason": reason},
            )
            response.raise_for_status()
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            logger.warning(
                json.dumps(
                    {"message": "health_report_failed", "model_entry_id": str(entry.id)}
                )
            )
