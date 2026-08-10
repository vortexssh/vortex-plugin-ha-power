from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _dir_is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".vortex_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def resolve_data_dir(raw: str | None = None) -> Path:
    """Prefer VORTEX_DATA_DIR; fall back if the mount is not writable (EACCES)."""
    candidates: list[Path] = []
    env = (raw if raw is not None else os.environ.get("VORTEX_DATA_DIR", "")).strip()
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path("./data").resolve())
    candidates.append(Path(tempfile.gettempdir()) / "vortex-ha-power")

    for path in candidates:
        if _dir_is_writable(path):
            if env and path.resolve() != Path(env).expanduser().resolve():
                print(
                    f"VORTEX_DATA_DIR={env} not writable; using {path}",
                    flush=True,
                )
            return path

    return candidates[-1]


class Settings:
    def __init__(self) -> None:
        self.core_url = os.environ["VORTEX_CORE_URL"].rstrip("/")
        self.install_id = os.environ["VORTEX_INSTALL_ID"]
        self.daemon_token = os.environ["VORTEX_DAEMON_TOKEN"]
        self.ha_url = os.environ["HA_URL"].rstrip("/")
        self.ha_token = os.environ["HA_TOKEN"]
        self.poll_interval = int(os.environ.get("VORTEX_POLL_INTERVAL", "30"))
        self.verify_tls = os.environ.get("HA_VERIFY_TLS", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        self.data_dir = resolve_data_dir()


def load_settings() -> Settings:
    required = (
        "VORTEX_CORE_URL",
        "VORTEX_INSTALL_ID",
        "VORTEX_DAEMON_TOKEN",
        "HA_URL",
        "HA_TOKEN",
    )
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}")
    return Settings()
