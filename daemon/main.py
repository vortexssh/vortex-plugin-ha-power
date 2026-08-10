#!/usr/bin/env python3
"""Vortex HA Power daemon — Home Assistant plugs → Core state + daily kWh/cost."""

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

from daemon.aggregator import (  # noqa: E402
    build_device_state,
    parse_currency,
    parse_plug_state,
    parse_tariff,
    utc_today,
)
from daemon.checkpoint import CheckpointStore  # noqa: E402
from daemon.config import Settings, load_settings  # noqa: E402
from daemon.device_resolve import resolve_device_entities  # noqa: E402
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
        self.checkpoints = CheckpointStore(settings.data_dir / "checkpoints.json")

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

    async def push_daily_samples(
        self,
        client: httpx.AsyncClient,
        samples: list[dict[str, Any]],
    ) -> None:
        if not samples:
            return
        r = await client.post(
            f"{self.s.core_url}/api/v1/plugins/{self.s.install_id}/daemon/metrics/daily",
            headers=self._headers(),
            json={"samples": samples},
            timeout=30.0,
        )
        r.raise_for_status()

    async def poll_once(self, client: httpx.AsyncClient) -> dict[str, Any]:
        bindings = await self.fetch_bindings(client)
        ha_states = await self.ha.list_states(client)
        states_by_id = {
            str(s.get("entity_id", "")): s for s in ha_states if s.get("entity_id")
        }
        today = utc_today().isoformat()
        bound = 0

        for b in bindings:
            host_id = str(b.get("host_id", ""))
            cfg = b.get("config") or {}
            entity_id = str(cfg.get("entity_id", "")).strip()
            if not host_id or not entity_id:
                continue

            tariff = parse_tariff(cfg.get("tariff"))
            currency = parse_currency(cfg.get("currency"))
            devices = resolve_device_entities(entity_id, ha_states)

            try:
                # Ensure bound entity is present (list_states can race); refresh missing.
                needed = {
                    devices.bound_entity_id,
                    devices.power_id,
                    devices.energy_id,
                    devices.voltage_id,
                    devices.current_id,
                    devices.switch_id,
                }
                for eid in needed:
                    if eid and eid not in states_by_id:
                        states_by_id[eid] = await self.ha.get_state(client, eid)

                energy_entity = states_by_id.get(devices.energy_id or "")
                total = None
                if energy_entity is not None:
                    try:
                        total = float(energy_entity.get("state"))
                    except (TypeError, ValueError):
                        total = None

                today_kwh: float | None = None
                month_kwh: float | None = None
                if total is not None:
                    periods = self.checkpoints.update_from_total(host_id, total)
                    today_kwh = periods.today_kwh
                    month_kwh = periods.month_kwh
                else:
                    # Attribute-rich single entity fallback (no sibling total sensor).
                    bound_raw = states_by_id.get(entity_id)
                    if bound_raw:
                        legacy = parse_plug_state(bound_raw)
                        if legacy.get("energy_kwh_total") is not None:
                            periods = self.checkpoints.update_from_total(
                                host_id, float(legacy["energy_kwh_total"])
                            )
                            today_kwh = periods.today_kwh
                            month_kwh = periods.month_kwh
                        elif legacy.get("energy_today_kwh") is not None:
                            today_kwh = float(legacy["energy_today_kwh"])

                state = build_device_state(
                    devices=devices,
                    states_by_id=states_by_id,
                    today_kwh=today_kwh,
                    month_kwh=month_kwh,
                    tariff=tariff,
                    currency=currency,
                )
                await self.push_state(client, state, host_id=host_id)

                if today_kwh is not None:
                    push_kwh = self.checkpoints.clamp_daily_push(
                        host_id, today, float(today_kwh)
                    )
                    samples: list[dict[str, Any]] = [
                        {
                            "host_id": host_id,
                            "metric": "energy_kwh",
                            "day": today,
                            "value": round(push_kwh, 4),
                        }
                    ]
                    if tariff is not None:
                        samples.append(
                            {
                                "host_id": host_id,
                                "metric": "energy_cost",
                                "day": today,
                                "value": round(push_kwh * tariff, 4),
                                "meta": {"currency": currency} if currency else {},
                            }
                        )
                    await self.push_daily_samples(client, samples)
                    self.checkpoints.mark_pushed(host_id, today, push_kwh)

                bound += 1
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
        self.s.data_dir.mkdir(parents=True, exist_ok=True)
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
