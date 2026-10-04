# MAVMind

A desktop ground station built around an LLM. Ask questions about the vehicle's state, mission and
MAVLink traffic; let the LLM propose missions that you approve before anything uploads. It runs
alongside Mission Planner rather than replacing it.

- Live map, VFR HUD and telemetry strip
- A message inspector that lists every downlinked message and lets you pin any field to a sparkline
- A chat panel where Claude answers through **read-only** MCP tools
- A gated command path: the LLM proposes, code validates, you approve, the app uploads and verifies
- Three ways to reach the vehicle: direct MAVLink (pymavlink), MAVROS (ROS 2), or tlog replay

Parameter tuning, calibration and firmware upload stay in Mission Planner.

## Architecture

```
 ┌──────────────── laptop ────────────────┐            ┌── wherever the link is ──────────────────┐
 │                                         │            │  (Windows / WSL / companion computer)    │
 │  Desktop UI (Tauri + React)             │  REST + WS │  Vehicle service (FastAPI)               │
 │   map · HUD · inspector · chat ─────────┼───────────►│   TelemetrySource ── pymavlink / MAVROS  │
 │   Approve / Reject / Arm / Mode ────────┼───────────►│   TelemetryStore      / tlog replay      │
 │        │ /api/chat (NDJSON)             │            │   validator · proposals · audit log      │
 │        ▼                                │    MCP     │   MCP /mcp/readonly  (11 read tools)     │
 │  Agent service (FastAPI) ───────────────┼───────────►│   MCP /mcp/command   (propose_mission,   │
 │   Claude tool-use loop · API key        │ (HTTP)     │                       off by default)    │
 └─────────────────────────────────────────┘            └──────────────────────────────────────────┘
```

Three processes. The vehicle service runs wherever the link is; the UI and agent stay on the laptop and
reach it over HTTP, so every deployment shares one codebase. **Approval goes from the UI straight to
the vehicle service, never through the LLM**; the agent only sees the two MCP servers.

## Quick start (no hardware)

Python 3.11+, Node 22.12+.

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1     # bash: python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# 1. vehicle service, replaying the bundled battery-failsafe flight
python -m mavmind_vehicle --profile replay

# 2. agent service (needs an Anthropic API key)
$env:ANTHROPIC_API_KEY = "sk-ant-..."                   # bash: export ANTHROPIC_API_KEY=...
python -m mavmind_agent

# 3. UI
cd apps/desktop; npm install; npm run dev               # browser at http://localhost:5173
npm run tauri dev                                       # or as the desktop app
```

Ask "Why did it switch to RTL?" while the replay runs. `scripts/dev.ps1` / `scripts/dev.sh` start
both services in one go.

To store the key in the OS keychain instead of the environment:
`pip install keyring` then `python -c "from mavmind_agent.keys import store_api_key; store_api_key('sk-ant-...')"`.

## Profiles

Profiles live in `config/profiles/*.yaml` and are picked from the UI or with `--profile`; switching
never requires code changes.

| Profile | Link | Vehicle service runs on | Notes |
| --- | --- | --- | --- |
| `sitl` | UDP from ArduPilot SITL | Windows or WSL | First target for development: `sim_vehicle.py -v ArduCopter --out=udp:127.0.0.1:14550` |
| `replay` | `.tlog` file | Windows | Deterministic, read-only, no hardware |
| `ground-direct` | SiK radio, pymavlink | Windows | No ROS; set the COM port |
| `ground-wsl` | SiK radio via usbipd, MAVROS | WSL, mirrored networking | Limited to SiK stream rates (SR\_ params) |
| `onboard` | MAVROS on the companion computer | Companion computer | Laptop over wifi/LTE: `MAVMIND_VEHICLE_URL=http://<companion>:8700` |

To keep Mission Planner connected, use MAVROS `gcs_url` in MAVROS profiles and mavlink-router in
pymavlink profiles. For MAVROS, confirm the raw passthrough topic for your install
(`ros2 topic list | grep mavlink`); the default is `/uas1/mavlink_source`.

## The command path

1. Turn on **Commands** in the UI (off by default; a banner shows while it's on).
2. Ask, e.g. "survey the north field at 40 m and come back".
3. Claude calls `propose_mission` with JSON matching `shared/mission_schema.json`.
4. The validator (`config/safety.yaml`) checks schema, command whitelist, altitude limits, geofence
   (points and legs), distance from home, leg length, speed/servo limits, and flight time vs battery.
   Failures go back to Claude to revise.
5. The proposal appears on the map in a second color with each check listed. You click **Approve** or
   **Reject**. Claude has no approve tool.
6. The vehicle service re-validates, uploads, downloads the mission back and diffs it.
7. You start it with the arm and mode buttons.

Whitelist: NAV_TAKEOFF, NAV_WAYPOINT, NAV_LOITER_TIME, NAV_LAND, NAV_RETURN_TO_LAUNCH, DO_CHANGE_SPEED,
DO_SET_SERVO, DO_GRIPPER, DO_DIGICAM_CONTROL.

## Read-only MCP tools

`get_vehicle_state`, `get_mission`, `list_messages`, `get_message`, `get_message_history`,
`analyze_field`, `get_statustext`, `get_events`, `get_params`, `get_link_health`, `get_home`.
Every response has `source`, `timestamp`, `age_s` and `rate_hz`; units are in field names; missing
data is `available: false` with a reason.

## Repo layout

```
CLAUDE.md                 safety rules and conventions for Claude Code
apps/desktop/             Tauri 2 + React UI (see its README)
services/vehicle/         mavmind_vehicle: sources/ (mavlink, mavros, replay), store, state,
                          mcp_readonly/, mcp_command/, validator/, proposals, api
services/agent/           mavmind_agent: Claude loop, MCP client toolbox, chat API
shared/                   mission_schema.json, units.json
config/                   profiles/*.yaml, safety.yaml, agent.yaml
docs/api.md               REST/WebSocket/NDJSON contract
scripts/                  dev launchers, tlog_to_udp.py, run_golden.py
tests/                    pytest suite, tlogs/, sitl/, fakes/, golden_questions.yaml
```

## Testing

| What | Command | Needs |
| --- | --- | --- |
| Unit + integration (store, tools, validator, MAVLink protocols against a fake copter, MCP over HTTP, WebSocket, approve→upload→readback, agent loop) | `pytest` | nothing |
| Golden questions on the battery-failsafe tlog | `pytest -m llm tests/test_golden.py` | `ANTHROPIC_API_KEY` |
| Same questions through any deployment (MAVROS, onboard) | feed the link with `scripts/tlog_to_udp.py`, then `python scripts/run_golden.py` | running services |
| HUD tracks SITL attitude; approved mission flies | `MAVMIND_SITL=1 pytest -m sitl tests/sitl` | ArduPilot SITL |
| UI | `cd apps/desktop && npm test && npm run build` | Node |

`tests/tlogs/battery_failsafe.tlog` is generated deterministically by
`tests/tlogs/generate_synthetic.py`, which also writes the facts the tests check
(`battery_failsafe.expected.json`). Drop real recorded tlogs next to it for more coverage.

## Milestones

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Scaffold: layout, Tauri window, services, profiles | Done. Health endpoints tested. Tauri window not yet launched on Windows |
| 2 | Telemetry core: MavlinkSource, ReplaySource, TelemetryStore | Done. Rates checked against the tlog, MAVLink protocols tested against a fake copter |
| 3 | Live view: WebSocket, strip, map, HUD | Done. WebSocket tested; SITL attitude test written, not yet run against SITL |
| 4 | Message inspector: all types, pinning, sparklines | Done |
| 5 | Read-only MCP server with unit tests | Done. Tool outputs match the tlog |
| 6 | Chat: agent loop, MCP client, tool-call view | Done. Loop tested with a scripted model; golden questions need an API key to run |
| 7 | MAVROS source and the ground-wsl profile | Implemented. Frame decoding tested; not yet run on ROS 2 |
| 8 | Command path: propose, validate, approve, upload, readback | Done. 32 validator rejection cases and readback over MAVLink tested; SITL flight test written |
| 9 | Onboard profile | Profile and remote binding done; not yet run on a companion computer |

Defaults for the open decisions: ROS 2; Tauri (PySide6 is the all-Python alternative); DataFlash
`.bin` analysis and offline map tiles are v2.
