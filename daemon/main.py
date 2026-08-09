#!/usr/bin/env python3
"""Vortex HA Power daemon — Home Assistant plugs → Core state + daily kWh."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

# Allow `python -m daemon.main` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daemon.aggregator import daily_kwh_from_state, parse_plug_state, utc_today  # noqa: E402
from daemon.config import Settings, load_settings  # noqa: E402
from daemon.ha_client import HomeAssistantClient  # noqa: E402

try:
    import websockets
except ImportError:
    print("pip install -r requirements.txt", file=sys.stderr)
    raise


class HaPowerDaemon:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.ha = HomeAssistantClient(
            settings.ha_url, settings.ha_token, verify=settings.verify_tls
        )
        self._day_start_totals: dict[str, tuple[str, float]] = {}

    def _ws_url(self) -> str:
        u = urlparse(self.s.core_url)
        scheme = "wss" if u.scheme == "https" else "ws"
        return (
            f"{scheme}://{u.netloc}/ws/plugin/{self.s.install_id}"
            f"?token={self.s.daemon_token}"
        )

    def _headers(self) -> dict[str, str]:
        return {"X-Plugin-Token": self.s.daemon_token}

    async def fetch_bindings(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        r = await client.get(
            f"{self.s.core_url}/api/v1/plugins/{self.s.install_id}/daemon/bindings",
            headers=self._headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    async def push_state(
        self,
        client: httpx.AsyncClient,
        state: dict[str, Any],
        *,
        host_id: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"state": state}
        if host_id:
            body["host_id"] = host_id
            body["history_key"] = "power_w"
        r = await client.post(
            f"{self.s.core_url}/api/v1/plugins/{self.s.install_id}/daemon/state",
            headers=self._headers(),
            json=body,
            timeout=30.0,
        )
        r.raise_for_status()

    async def push_daily(
        self,
        client: httpx.AsyncClient,
        host_id: str,
        day: str,
        value: float,
    ) -> None:
        r = await client.post(
            f"{self.s.core_url}/api/v1/plugins/{self.s.install_id}/daemon/metrics/daily",
            headers=self._headers(),
            json={
                "samples": [
                    {
                        "host_id": host_id,
                        "metric": "energy_kwh",
                        "day": day,
                        "value": round(value, 4),
                    }
                ]
            },
            timeout=30.0,
        )
        r.raise_for_status()

    def _today_from_total(self, host_id: str, total: float | None) -> float | None:
        if total is None:
            return None
        day = utc_today().isoformat()
        prev = self._day_start_totals.get(host_id)
        if prev is None or prev[0] != day:
            self._day_start_totals[host_id] = (day, total)
            return 0.0
        return max(0.0, total - prev[1])

    async def poll_once(self, client: httpx.AsyncClient) -> dict[str, Any]:
        bindings = await self.fetch_bindings(client)
        today = utc_today().isoformat()
        bound = 0
        for b in bindings:
            host_id = str(b.get("host_id", ""))
            cfg = b.get("config") or {}
            entity_id = str(cfg.get("entity_id", "")).strip()
            if not host_id or not entity_id:
                continue
            try:
                raw = await self.ha.get_state(client, entity_id)
            except Exception as exc:
                print(f"HA error {entity_id}: {exc}", flush=True)
                await self.push_state(
                    client,
                    {
                        "entity_id": entity_id,
                        "online": False,
                        "error": str(exc),
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                    host_id=host_id,
                )
                continue

            parsed = parse_plug_state(raw)
            today_kwh = daily_kwh_from_state(parsed)
            if today_kwh is None:
                today_kwh = self._today_from_total(
                    host_id, parsed.get("energy_kwh_total")
                )
                if today_kwh is not None:
                    parsed["energy_today_kwh"] = round(today_kwh, 4)

            await self.push_state(client, parsed, host_id=host_id)
            if today_kwh is not None:
                await self.push_daily(client, host_id, today, float(today_kwh))
            bound += 1

        global_state = {
            "bound_count": bound,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        await self.push_state(client, global_state)
        return global_state

    async def handle_rpc(
        self,
        client: httpx.AsyncClient,
        message: dict[str, Any],
        ws: Any,
    ) -> None:
        method = message.get("method")
        request_id = message.get("request_id")
        try:
            if method == "refresh":
                result = await self.poll_once(client)
            elif method == "list_entities":
                states = await self.ha.list_states(client)
                entities = []
                for s in states:
                    eid = str(s.get("entity_id", ""))
                    if not (
                        eid.startswith("sensor.")
                        or eid.startswith("switch.")
                        or eid.startswith("light.")
                    ):
                        continue
                    if any(
                        k in eid
                        for k in ("power", "energy", "plug", "socket", "consumption")
                    ) or "power" in str((s.get("attributes") or {})).lower():
                        entities.append(
                            {
                                "entity_id": eid,
                                "state": s.get("state"),
                                "friendly_name": (s.get("attributes") or {}).get(
                                    "friendly_name"
                                ),
                            }
                        )
                result = {"count": len(entities), "entities": entities[:200]}
            else:
                await ws.send(
                    json.dumps(
                        {
                            "type": "rpc_response",
                            "request_id": request_id,
                            "error": f"unknown method: {method}",
                        }
                    )
                )
                return
            await ws.send(
                json.dumps(
                    {
                        "type": "rpc_response",
                        "request_id": request_id,
                        "result": result,
                    }
                )
            )
        except Exception as exc:
            await ws.send(
                json.dumps(
                    {
                        "type": "rpc_response",
                        "request_id": request_id,
                        "error": str(exc),
                    }
                )
            )

    async def run(self) -> None:
        async with httpx.AsyncClient(verify=self.s.verify_tls) as client:
            while True:
                try:
                    async with websockets.connect(
                        self._ws_url(),
                        ping_interval=20,
                        ping_timeout=20,
                    ) as ws:
                        print("connected to Core plugin channel", flush=True)
                        hello = json.loads(await ws.recv())
                        print("core:", hello, flush=True)

                        async def publisher() -> None:
                            while True:
                                try:
                                    await self.poll_once(client)
                                except Exception as exc:
                                    print(f"poll error: {exc}", flush=True)
                                await asyncio.sleep(self.s.poll_interval)

                        pub = asyncio.create_task(publisher())
                        try:
                            async for raw in ws:
                                try:
                                    msg = json.loads(raw)
                                except json.JSONDecodeError:
                                    continue
                                if msg.get("type") == "rpc_request":
                                    await self.handle_rpc(client, msg, ws)
                        finally:
                            pub.cancel()
                            try:
                                await pub
                            except asyncio.CancelledError:
                                pass
                except Exception as exc:
                    print(f"disconnected: {exc}; retry in 5s", flush=True)
                    await asyncio.sleep(5)


def main() -> None:
    settings = load_settings()
    asyncio.run(HaPowerDaemon(settings).run())


if __name__ == "__main__":
    main()
