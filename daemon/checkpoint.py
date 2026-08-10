from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


@dataclass
class HostCheckpoint:
    day: str
    day_start_total: float
    month: str
    month_start_total: float
    last_total: float
    last_pushed_day: str | None = None
    last_pushed_kwh: float = 0.0


@dataclass
class PeriodTotals:
    today_kwh: float
    month_kwh: float
    day: str
    month: str


class CheckpointStore:
    """Durable baselines for total_increasing energy counters."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._hosts: dict[str, HostCheckpoint] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        hosts = raw.get("hosts") if isinstance(raw, dict) else None
        if not isinstance(hosts, dict):
            return
        for host_id, row in hosts.items():
            if not isinstance(row, dict):
                continue
            try:
                self._hosts[str(host_id)] = HostCheckpoint(
                    day=str(row["day"]),
                    day_start_total=float(row["day_start_total"]),
                    month=str(row["month"]),
                    month_start_total=float(row["month_start_total"]),
                    last_total=float(row["last_total"]),
                    last_pushed_day=row.get("last_pushed_day"),
                    last_pushed_kwh=float(row.get("last_pushed_kwh") or 0.0),
                )
            except (KeyError, TypeError, ValueError):
                continue

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "updated_at": datetime.now(UTC).isoformat(),
            "hosts": {hid: asdict(cp) for hid, cp in self._hosts.items()},
        }
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            # Keep in-memory baselines; surface once so UI/RPC can show a clear hint.
            raise OSError(
                f"Cannot write checkpoints to {self._path} ({exc}). "
                "Fix volume ownership (chown 1000:1000 data/) or rebuild daemon image."
            ) from exc

    def update_from_total(self, host_id: str, total: float, *, now: date | None = None) -> PeriodTotals:
        today = now or datetime.now(UTC).date()
        day = today.isoformat()
        month = today.strftime("%Y-%m")
        cp = self._hosts.get(host_id)

        if cp is None:
            cp = HostCheckpoint(
                day=day,
                day_start_total=total,
                month=month,
                month_start_total=total,
                last_total=total,
            )
            self._hosts[host_id] = cp
            self.save()
            return PeriodTotals(today_kwh=0.0, month_kwh=0.0, day=day, month=month)

        # Counter reset / device replace: re-baseline.
        if total + 1e-9 < cp.last_total:
            cp.day = day
            cp.day_start_total = total
            cp.month = month
            cp.month_start_total = total
            cp.last_total = total
            cp.last_pushed_day = day
            cp.last_pushed_kwh = 0.0
            self.save()
            return PeriodTotals(today_kwh=0.0, month_kwh=0.0, day=day, month=month)

        if cp.day != day:
            cp.day = day
            cp.day_start_total = total
            cp.last_pushed_day = day
            cp.last_pushed_kwh = 0.0

        if cp.month != month:
            cp.month = month
            cp.month_start_total = total

        cp.last_total = total
        today_kwh = max(0.0, total - cp.day_start_total)
        month_kwh = max(0.0, total - cp.month_start_total)
        self.save()
        return PeriodTotals(
            today_kwh=today_kwh, month_kwh=month_kwh, day=day, month=month
        )

    def clamp_daily_push(self, host_id: str, day: str, today_kwh: float) -> float:
        """Never push a lower value for the same UTC day than last successful push."""
        cp = self._hosts.get(host_id)
        if cp is None:
            return today_kwh
        if cp.last_pushed_day == day:
            return max(today_kwh, cp.last_pushed_kwh)
        return today_kwh

    def mark_pushed(self, host_id: str, day: str, value: float) -> None:
        cp = self._hosts.get(host_id)
        if cp is None:
            return
        cp.last_pushed_day = day
        cp.last_pushed_kwh = value
        self.save()
