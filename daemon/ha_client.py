from __future__ import annotations

from typing import Any

import httpx


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, *, verify: bool = True) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._verify = verify

    async def get_state(self, client: httpx.AsyncClient, entity_id: str) -> dict[str, Any]:
        r = await client.get(
            f"{self._base}/api/states/{entity_id}",
            headers=self._headers,
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()

    async def list_states(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        r = await client.get(
            f"{self._base}/api/states",
            headers=self._headers,
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    async def history_period(
        self,
        client: httpx.AsyncClient,
        entity_id: str,
        start_iso: str,
    ) -> list[Any]:
        r = await client.get(
            f"{self._base}/api/history/period/{start_iso}",
            params={"filter_entity_id": entity_id, "minimal_response": "true"},
            headers=self._headers,
            timeout=60.0,
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
