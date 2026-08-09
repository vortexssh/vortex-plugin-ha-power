from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any


def _f(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_plug_state(entity: dict[str, Any]) -> dict[str, Any]:
    """Normalize HA state into Vortex plugin.state fields."""
    attrs = entity.get("attributes") or {}
    entity_id = str(entity.get("entity_id", ""))
    state = entity.get("state")

    power = (
        _f(attrs.get("current_power_w"))
        or _f(attrs.get("power"))
        or _f(attrs.get("power_w"))
        or _f(attrs.get("current_consumption"))
    )
    # Some entities are power sensors themselves
    if power is None and entity_id.endswith("_power"):
        power = _f(state)

    energy_total = (
        _f(attrs.get("energy"))
        or _f(attrs.get("total_consumption"))
        or _f(attrs.get("today_energy_kwh"))  # sometimes misnamed
    )
    if energy_total is None and ("energy" in entity_id or entity_id.endswith("_energy")):
        energy_total = _f(state)

    energy_today = (
        _f(attrs.get("today_energy_kwh"))
        or _f(attrs.get("energy_today"))
        or _f(attrs.get("daily_energy"))
    )

    online = str(state).lower() not in {"unavailable", "unknown", "none", ""}

    return {
        "entity_id": entity_id,
        "power_w": round(power, 2) if power is not None else None,
        "energy_kwh_total": round(energy_total, 4) if energy_total is not None else None,
        "energy_today_kwh": round(energy_today, 4) if energy_today is not None else None,
        "online": online,
        "raw_state": state,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def daily_kwh_from_state(parsed: dict[str, Any]) -> float | None:
    """Prefer today counter; else None (caller may derive from totals)."""
    if parsed.get("energy_today_kwh") is not None:
        return float(parsed["energy_today_kwh"])
    return None


def utc_today() -> date:
    return datetime.now(UTC).date()
