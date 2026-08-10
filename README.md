# vortex-plugin-ha-power

Out-of-process Vortex plugin: **Home Assistant smart plugs → per-host power/energy** on Vortex Core / Web.

- Live state → Redis (`power_w`, `voltage_v`, `current_a`, `energy_*`, `cost_*`, …)
- Daily → Core PostgreSQL (`energy_kwh`, `energy_cost`)
- Binding: **one HA device entity ↔ one Vortex host** + optional per-host `tariff` / `currency`

Follows [`VortexCore/docs/DAEMON_CREATORS.md`](../VortexCore/docs/DAEMON_CREATORS.md).

**For agents:** full platform + handoff context → [`AGENTS.md`](./AGENTS.md).

## Install (Vortex Web)

Pack a ZIP (daemon code optional — Core ignores it):

```bash
cd vortex-plugin-ha-power
zip -r ../ha-power-plugin.zip vortex-plugin.json schemas/
# if you split UI out of the manifest later, also include ui/
```

1. Settings → **Plugins** → choose `ha-power-plugin.zip` → Install.
2. Copy one-time `vxp_…` daemon token and note `install_id`.
3. Edit each host → set **HA entity** (any sibling from the plug: `…_total_energy`, `…_power`, …) plus **tariff / currency**.

## Run daemon

### Docker (recommended)

```bash
cd vortex-plugin-ha-power
cp .env.example .env
# fill VORTEX_* and HA_* in .env

docker compose up -d --build
docker compose logs -f
```

Persists day/month baselines in `./data/checkpoints.json` (compose mounts `./data:/data`). Keep this volume across restarts so daily stats are not reset.

If Home Assistant runs on the same host, set `HA_URL=http://host.docker.internal:8123` (compose already maps `host.docker.internal`). For LAN-only HA, use its IP/`homeassistant.local`, or uncomment `network_mode: host` in `docker-compose.yml`.

### Local venv

```bash
cd vortex-plugin-ha-power
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export VORTEX_CORE_URL=https://api.vortex.example
export VORTEX_INSTALL_ID=<uuid>
export VORTEX_DAEMON_TOKEN=vxp_…
export HA_URL=http://homeassistant.local:8123
export HA_TOKEN=<long-lived-access-token>
# optional
export VORTEX_POLL_INTERVAL=30
export VORTEX_DATA_DIR=./data
# export HA_VERIFY_TLS=false

python -m daemon.main
```

Long-lived token: HA → Profile → Security → Long-Lived Access Tokens.

## Entities

Typical Zigbee/Tuya plug (separate sensors):

- `sensor.*_power` (W)
- `sensor.*_total_energy` (kWh, `total_increasing`) — source for today/month via durable delta
- `sensor.*_voltage` / `sensor.*_current`
- `switch.*_socket_*` (on/off)

Bind any of them; daemon resolves siblings by device prefix. Period kWh is derived from the lifetime counter (not `∫P·dt`), so downtime is recovered when the daemon resumes.

Per-host electricity cost: `cost = kWh × tariff` (independent of host rental billing).

RPC:

- `refresh` — poll all bindings now
- `list_entities` — search HA for power/energy-related entities

## Public page

Non-hidden hosts on `/u/:slug` show billing (if enabled) and the month energy calendar from Core daily metrics (daemon does not need to be online for calendar reads).
