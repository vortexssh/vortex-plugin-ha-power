from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from daemon.device_resolve import DeviceEntities


def _f(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _state_float(entity: dict[str, Any] | None) -> float | None:
    if not entity:
        return None
    return _f(entity.get("state"))


def _online(entity: dict[str, Any] | None) -> bool:
    if not entity:
        return False
    return str(entity.get("state")).lower() not in {"unavailable", "unknown", "none", ""}


def parse_plug_state(entity: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single HA entity (legacy / attribute-rich plugs)."""
    attrs = entity.get("attributes") or {}
    entity_id = str(entity.get("entity_id", ""))
    state = entity.get("state")

    power = (
        _f(attrs.get("current_power_w"))
        or _f(attrs.get("power"))
        or _f(attrs.get("power_w"))
        or _f(attrs.get("current_consumption"))
    )
    if power is None and entity_id.endswith("_power"):
        power = _f(state)

    energy_total = (
        _f(attrs.get("energy"))
        or _f(attrs.get("total_consumption"))
        or _f(attrs.get("today_energy_kwh"))
    )
    if energy_total is None and ("energy" in entity_id or entity_id.endswith("_energy")):
        energy_total = _f(state)

    energy_today = (
        _f(attrs.get("today_energy_kwh"))
        or _f(attrs.get("energy_today"))
        or _f(attrs.get("daily_energy"))
    )

    voltage = _f(attrs.get("voltage"))
    current = _f(attrs.get("current")) or _f(attrs.get("current_a"))

    online = str(state).lower() not in {"unavailable", "unknown", "none", ""}

    return {
        "entity_id": entity_id,
        "power_w": round(power, 2) if power is not None else None,
        "voltage_v": round(voltage, 2) if voltage is not None else None,
        "current_a": round(current, 3) if current is not None else None,
        "energy_kwh_total": round(energy_total, 4) if energy_total is not None else None,
        "energy_today_kwh": round(energy_today, 4) if energy_today is not None else None,
        "online": online,
        "raw_state": state,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def build_device_state(
    *,
    devices: DeviceEntities,
    states_by_id: dict[str, dict[str, Any]],
    today_kwh: float | None,
    month_kwh: float | None,
    tariff: float | None,
    currency: str | None,
) -> dict[str, Any]:
    """Merge sibling sensors into one host plugin.state payload."""
    power_e = states_by_id.get(devices.power_id or "")
    energy_e = states_by_id.get(devices.energy_id or "")
    voltage_e = states_by_id.get(devices.voltage_id or "")
    current_e = states_by_id.get(devices.current_id or "")
    switch_e = states_by_id.get(devices.switch_id or "")
    bound_e = states_by_id.get(devices.bound_entity_id)

    # Fallback: attributes on the bound entity (some plugs put everything there).
    legacy = parse_plug_state(bound_e) if bound_e else {}

    power = _state_float(power_e)
    if power is None:
        power = legacy.get("power_w")

    energy_total = _state_float(energy_e)
    if energy_total is None:
        energy_total = legacy.get("energy_kwh_total")

    voltage = _state_float(voltage_e)
    if voltage is None:
        voltage = legacy.get("voltage_v")

    current = _state_float(current_e)
    if current is None:
        current = legacy.get("current_a")

    if today_kwh is None:
        today_kwh = legacy.get("energy_today_kwh")

    online = any(
        _online(e) for e in (power_e, energy_e, voltage_e, current_e, switch_e, bound_e)
    )

    cost_today = None
    cost_month = None
    if tariff is not None:
        if today_kwh is not None:
            cost_today = round(float(today_kwh) * tariff, 4)
        if month_kwh is not None:
            cost_month = round(float(month_kwh) * tariff, 4)

    return {
        "entity_id": devices.bound_entity_id,
        "device_prefix": devices.prefix,
        "power_entity_id": devices.power_id,
        "energy_entity_id": devices.energy_id,
        "voltage_entity_id": devices.voltage_id,
        "current_entity_id": devices.current_id,
        "switch_entity_id": devices.switch_id,
        "power_w": round(power, 2) if power is not None else None,
        "voltage_v": round(voltage, 2) if voltage is not None else None,
        "current_a": round(current, 3) if current is not None else None,
        "energy_kwh_total": round(energy_total, 4) if energy_total is not None else None,
        "energy_today_kwh": round(today_kwh, 4) if today_kwh is not None else None,
        "energy_month_kwh": round(month_kwh, 4) if month_kwh is not None else None,
        "tariff": tariff,
        "currency": currency,
        "cost_today": cost_today,
        "cost_month": cost_month,
        "online": online,
        "switch_state": switch_e.get("state") if switch_e else None,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def daily_kwh_from_state(parsed: dict[str, Any]) -> float | None:
    """Prefer today counter from HA attributes; else None (caller derives from totals)."""
    if parsed.get("energy_today_kwh") is not None:
        return float(parsed["energy_today_kwh"])
    return None


def utc_today() -> date:
    return datetime.now(UTC).date()


def parse_tariff(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val < 0:
        return None
    return val


def parse_currency(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    return s or None
