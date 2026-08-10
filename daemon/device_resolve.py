from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SOCKET_RE = re.compile(r"_socket_\d+$")
_SUFFIXES = (
    "_total_energy",
    "_energy",
    "_power",
    "_voltage",
    "_current",
)


def entity_local_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[-1]


def device_prefix(entity_id: str) -> str:
    """Derive shared device stem: sensor.bedroom_server_power → bedroom_server."""
    local = entity_local_id(entity_id)
    local = _SOCKET_RE.sub("", local)
    for suffix in _SUFFIXES:
        if local.endswith(suffix):
            return local[: -len(suffix)]
    return local


@dataclass
class DeviceEntities:
    prefix: str
    bound_entity_id: str
    power_id: str | None = None
    energy_id: str | None = None
    voltage_id: str | None = None
    current_id: str | None = None
    switch_id: str | None = None


def resolve_device_entities(
    bound_entity_id: str, states: list[dict[str, Any]]
) -> DeviceEntities:
    prefix = device_prefix(bound_entity_id)
    by_id = {str(s.get("entity_id", "")): s for s in states if s.get("entity_id")}

    def pick(*candidates: str) -> str | None:
        for eid in candidates:
            if eid in by_id:
                return eid
        return None

    out = DeviceEntities(prefix=prefix, bound_entity_id=bound_entity_id)
    out.power_id = pick(f"sensor.{prefix}_power")
    out.energy_id = pick(
        f"sensor.{prefix}_total_energy",
        f"sensor.{prefix}_energy",
    )
    out.voltage_id = pick(f"sensor.{prefix}_voltage")
    out.current_id = pick(f"sensor.{prefix}_current")

    # Prefer numbered socket switch, else any switch with prefix.
    socket = pick(f"switch.{prefix}_socket_1", f"switch.{prefix}")
    if socket is None:
        for eid in by_id:
            if eid.startswith("switch.") and entity_local_id(eid).startswith(prefix):
                socket = eid
                break
    out.switch_id = socket

    # If user bound the energy/power sensor itself, keep it even if naming differs.
    bound = bound_entity_id
    if bound.startswith("sensor.") and out.energy_id is None:
        attrs = (by_id.get(bound) or {}).get("attributes") or {}
        if attrs.get("device_class") == "energy" or "energy" in bound:
            out.energy_id = bound
    if bound.startswith("sensor.") and out.power_id is None:
        attrs = (by_id.get(bound) or {}).get("attributes") or {}
        if attrs.get("device_class") == "power" or bound.endswith("_power"):
            out.power_id = bound

    return out
