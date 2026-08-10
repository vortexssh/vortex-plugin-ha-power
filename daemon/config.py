from __future__ import annotations

import os
from pathlib import Path


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
        self.data_dir = Path(os.environ.get("VORTEX_DATA_DIR", "./data")).expanduser()


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
