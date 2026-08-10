# Agent handoff: vortex-plugin-ha-power

This file is the **context dump** for a new agent working on this plugin.
Do not ask the user to re-explain the platform — read this + the linked Core/Web docs.

Sibling repos (same parent folder `VortexSSH/`):

| Repo | Path | Role |
|------|------|------|
| This plugin | `/home/timant32/VortexSSH/vortex-plugin-ha-power` | HA daemon + `vortex-plugin.json` |
| Vortex Core | `/home/timant32/VortexSSH/VortexCore` | FastAPI API, PG, Redis, plugin platform |
| Vortex Web | `/home/timant32/VortexSSH/VortexWeb` | React UI, declarative plugin renderer, public `/u/:slug` |

Canonical specs in Core (source of truth for the platform):

- [`../VortexCore/PLUGIN_SPEC.md`](../VortexCore/PLUGIN_SPEC.md)
- [`../VortexCore/docs/DAEMON_CREATORS.md`](../VortexCore/docs/DAEMON_CREATORS.md)
- Core `.cursorrules`: zero-trust (no SSH passwords/keys in Core), 2FA for agent-facing user ops, **live telemetry → Redis only**, daily aggregates → PG.

---

## What this product is

**VortexSSH**: cloud notebook of host metadata + WebSocket tunnel to Go host-agents + Web/TUI clients.

**Plugin platform (v1)**: out-of-process **daemons** + **declarative UI** in the Web.

- User installs a plugin **per-user** (`plugin_installs`, unique `(user_id, plugin_id)`).
- Core stores the **manifest** (UI contributions, permissions, schemas).
- Daemon authenticates with one-time `vxp_…` token (`X-Plugin-Token` / WS query).
- Live state: Redis keys `plugin:{install_id}:state` / `plugin:{install_id}:host:{host_id}:state`.
- **Daily metrics** (calendars / public page): PostgreSQL `plugin_daily_metrics` (generic, not HA-specific).

**This plugin** (`com.vortex.ha_power`): Home Assistant power/energy sensors → Vortex hosts.

- Binding: **1 HA device entity ↔ 1 Vortex host** via `plugin_host_bindings.config` (`entity_id`, optional `tariff`, `currency`).
- Daemon resolves sibling sensors (`*_power`, `*_total_energy`, `*_voltage`, `*_current`) by device prefix.
- Period kWh = durable delta from `total_increasing` energy (local `VORTEX_DATA_DIR/checkpoints.json`).
- Cost today/month computed on the daemon (`kWh × tariff`); Core only stores results.
- `HA_TOKEN` stays on the daemon machine only (env). Never put HA secrets in `install.config`.

```text
Home Assistant ──poll──► this daemon ──POST state──► Core Redis
                              │
                              └──POST daily samples──► Core PG (plugin_daily_metrics)
Web (auth) ──JWT──► Core (state + GET metrics/daily)
Public /u/:slug ──no auth──► Core (billing + energy calendar for non-hidden hosts)
```

---

## Decisions already locked

1. History = **daily aggregates in Core PG** + live in Redis (not HA-specific tables).
2. Plugin repo is **local** (this tree); may or may not be on GitHub yet.
3. Public `/u/:slug`: billing (if enabled on host) + energy calendar; **no IP**; **billing notes not public** by default.
4. Install UX: **ZIP upload** in Web (not paste JSON). Core endpoint materializes package.
5. Energy calendar in Web is **native React** (`EnergyCalendar`), not declarative DSL — DSL is weak for month grids. Declarative UI covers live metrics/buttons.

---

## This repo layout

```text
vortex-plugin-ha-power/
  AGENTS.md                 ← you are here
  README.md                 ← human install / run
  Dockerfile                ← daemon image
  docker-compose.yml        ← restart + env_file + ./data volume
  .env.example              ← VORTEX_* + HA_* template
  vortex-plugin.json        ← manifest (views mostly inlined)
  schemas/
    settings.json           ← install config schema (interval; no token)
    host_binding.json       ← { entity_id, tariff?, currency? }
  requirements.txt
  daemon/
    main.py                 ← poll loop, WS RPC, Core HTTP
    config.py               ← env
    ha_client.py            ← HA REST
    device_resolve.py       ← sibling entity discovery by prefix
    checkpoint.py           ← durable day/month baselines
    aggregator.py           ← parse state → period kWh + cost
```

Daemon env:

- `VORTEX_CORE_URL`, `VORTEX_INSTALL_ID`, `VORTEX_DAEMON_TOKEN`
- `HA_URL`, `HA_TOKEN`
- optional: `VORTEX_POLL_INTERVAL`, `HA_VERIFY_TLS`, `VORTEX_DATA_DIR` (default `./data`)

RPC methods (manifest + daemon): `refresh`, `list_entities`.

Live host state shape (approx):  
`{ power_w, voltage_v, current_a, energy_kwh_total, energy_today_kwh, energy_month_kwh, cost_today, cost_month, tariff, currency, online, entity_id }`.

Daily metrics: **`energy_kwh`** and **`energy_cost`** (upsert per host per UTC day).
---

## Core APIs this plugin uses

Auth daemon: header `X-Plugin-Token: vxp_…`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/plugins/{install_id}/daemon/bindings` | `{ host_id, config }` list |
| POST | `/api/v1/plugins/{install_id}/daemon/state` | Redis live state |
| POST | `/api/v1/plugins/{install_id}/daemon/metrics/daily` | PG upsert samples |
| WS | `/ws/plugin/{install_id}?token=vxp_…` | RPC from Web |

User JWT:

| Method | Path |
|--------|------|
| GET | `/api/v1/plugins/{install_id}/metrics/daily?from=&to=&metric=energy_kwh&host_id=` |
| POST | `/api/v1/plugins` JSON install |
| POST | `/api/v1/plugins/install-package` multipart ZIP (optional; Core may lag) |

Web install: always unpacks ZIP in-browser (`materializePluginZip.ts`) → `POST /plugins` JSON. Does **not** depend on Core `/install-package`.

ZIP install (`app/services/plugin_package.py`):

- Requires `vortex-plugin.json` at root or one folder deep.
- Inlines `ui/**/*.json` → `manifest.views`, `schemas/**/*.json` → `manifest.schemas`.
- Daemon sources in the ZIP are **ignored**.
- Limits: ~2 MiB zip, path traversal rejected.

Migration: `alembic/versions/0009_plugin_daily_metrics.py` → table `plugin_daily_metrics`.

Public payload: `app/schemas/public.py` / `app/services/public.py` — host `billing` + `energy` (`today_kwh`, `month_kwh`, `calendar[{day,value}]`).

Key Core files:

- `app/api/v1/plugins.py`
- `app/services/plugin.py`, `plugin_package.py`, `plugin_manifest.py`, `plugin_state.py`
- `app/models/plugin.py` (`PluginInstall`, `PluginHostBinding`, `PluginDailyMetric`)
- `app/repositories/plugin_metrics.py`
- `app/websocket/routes.py` (plugin WS)

---

## Web touchpoints

| Area | Path |
|------|------|
| Install ZIP UI | `VortexWeb/src/plugins/PluginsManager.tsx` |
| API client | `…/services/pluginsApi.ts` (`installPackage`, `dailyMetrics`) |
| FormData support | `…/services/apiClient.ts` |
| Energy calendar | `…/plugins/EnergyCalendar.tsx` |
| Hosts expand | `…/plugins/HostPluginPanels.tsx` + `…/features/hosts/HostsPage.tsx` (HA entity field) |
| Plugin route | `…/plugins/PluginPage.tsx` (hardcodes `com.vortex.ha_power` for calendar) |
| Public page | `…/features/status/PublicStatusPage.tsx` |
| Declarative renderer | `…/plugins/*` (ViewTree, bindings, slots) |

Hardcoded plugin id in Web: **`com.vortex.ha_power`** — if you rename the plugin id, update Web too.

---

## Install / run (quick)

```bash
# Package for Web
cd /home/timant32/VortexSSH/vortex-plugin-ha-power
zip -r ../ha-power-plugin.zip vortex-plugin.json schemas/

# Web: Settings → Plugins → upload zip → copy vxp_ token + install_id

# Daemon (Docker)
cp .env.example .env   # fill VORTEX_* + HA_*
docker compose up -d --build

# Daemon (venv)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export VORTEX_CORE_URL=… VORTEX_INSTALL_ID=… VORTEX_DAEMON_TOKEN=vxp_…
export HA_URL=… HA_TOKEN=…
python -m daemon.main
```

Deploy reminder for ops: Core needs migration **0008/0009** (entrypoint runs `alembic upgrade head`); Web rebuild for ZIP install + EnergyCalendar + public billing/energy.

**Prod gotcha (2026-08):** if `GET /api/v1/plugins` → 404 while `/me` works, Core on the VPS is stale. CI `git pull` used to fail on dirty `/opt/vortex-core` (local hotfixes). Fix: `git fetch && git reset --hard origin/master && docker compose up -d --build` (now in Core deploy workflow).

---

## Security rules (do not violate)

- Never send HA / SSH secrets to Core or store them in PG.
- Never teach Core to hold user SSH private keys or host passwords.
- Live plugin metrics stay in Redis; only day buckets go to PG via the generic daily-metrics API.
- Public page: no host IPs; billing notes stay private unless product explicitly opens them.

---

## Likely next work (not necessarily done)

- Day-boundary correctness across timezones (currently UTC-oriented).
- Remove Web hardcoding of `com.vortex.ha_power` if more energy plugins appear (capability flag / metric convention).
- GitHub publish of this repo; CI for daemon lint/tests.
- Example ZIP in repo releases; systemd unit sample for the daemon.
- Public page `?month=YYYY-MM` if needed (Core currently “current month”).
- Show `energy_cost` on calendar / public page (metric already written by daemon).
---

## How to work here

1. Prefer changing **this daemon + manifest** for HA-specific logic.
2. Change **VortexCore** only for platform APIs / schemas / public payload.
3. Change **VortexWeb** for native UI (calendar, install UX) and wiring.
4. Keep manifests installable as ZIP; if you add loose `ui/*.json` files, include them in the zip and/or keep inlined `views` in `vortex-plugin.json`.
5. After Core API changes, update `PLUGIN_SPEC.md` / `DAEMON_CREATORS.md` in Core, not only this file.
6. Do not edit plan files under `~/.cursor/plans/` unless the user asks.

Success criterion (from original plan): user installs ZIP → runs daemon with `HA_TOKEN` → sets `entity_id` on host → live W/kWh on Hosts → daily kWh in PG → `/u/:slug` shows billing + energy calendar per public host.
