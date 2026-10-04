# MAVMind desktop

The desktop ground-station UI for MAVMind: a Tauri 2 shell around a React 18,
TypeScript and Vite app. It talks to the two Python services described in
[`docs/api.md`](../../docs/api.md):

| Service | Default URL | Used for |
| --- | --- | --- |
| vehicle | `http://127.0.0.1:8700` | REST, the `/ws` telemetry stream, arm/mode, approve/reject |
| agent | `http://127.0.0.1:8701` | `/api/chat` (NDJSON stream), `/api/chat/reset` |

The app does not start these services. Start them separately (see the repo
root). It can run alongside Mission Planner.

## Requirements

- Node.js 22.12 or newer, with npm
- To build the desktop app: Rust (stable) and the
  [Tauri 2 prerequisites](https://v2.tauri.app/start/prerequisites/). On
  Windows these are the MSVC build tools and WebView2, which ships with
  Windows 10 and 11.

```sh
cd apps/desktop
npm install
```

## Run in a browser (fastest dev loop)

```sh
npm run dev          # http://localhost:5173
```

Open http://localhost:5173 in Chrome or Edge. When the services are not
running, the UI still loads and the status pills show them as offline.

## Run as a desktop app (Tauri dev)

```sh
npm run tauri dev
```

This starts Vite (`beforeDevCommand`) and opens a 1600×1000 MAVMind window
with hot reload.

## Build the Windows installer

```sh
npm run tauri build
```

The output goes to `src-tauri/target/release/bundle/`:

- `nsis/MAVMind_<version>_x64-setup.exe`
- `msi/MAVMind_<version>_x64_en-US.msi`

Build on Windows. Cross-compiling the installer from Linux or macOS is not
supported by this setup.

## Configure service URLs

There are three ways to set the URLs. Each one overrides the one before it.

1. **Built-in defaults**: `http://127.0.0.1:8700` and `http://127.0.0.1:8701`.
2. **Build-time environment**: set `VITE_VEHICLE_URL` / `VITE_AGENT_URL` when
   running `npm run dev`, `npm run build` or `npm run tauri build`, or put
   them in `apps/desktop/.env.local`:
   ```
   VITE_VEHICLE_URL=http://192.168.1.50:8700
   VITE_AGENT_URL=http://192.168.1.50:8701
   ```
3. **At runtime**: the gear button (top right) edits both URLs. They are saved
   in the app's localStorage. "Reset to defaults" goes back to option 2 or 1.

The WebSocket URL comes from the vehicle URL: `http://host:port` becomes
`ws://host:port/ws`, and `https` becomes `wss`.

The services must allow CORS from the UI's origin:

- `http://localhost:5173` for dev
- `http://tauri.localhost` for the Tauri app on Windows
- `tauri://localhost` for the Tauri app on macOS and Linux

## Scripts

| Script | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on port 5173 |
| `npm run build` | Type-check, then build to `dist/` |
| `npm run typecheck` | `tsc --noEmit` for the app and the Vite config |
| `npm test` | Vitest unit tests (`src/lib/**/*.test.ts`) |
| `npm run tauri <cmd>` | Tauri CLI (`dev`, `build`, `icon`, `info`, …) |

## Layout

```
src/
  types.ts            contract types (mirror docs/api.md exactly)
  lib/                pure logic + unit tests
    ndjson.ts         NDJSON splitter / stream reader (chat)
    vehicle.ts        reducer for WS frames + REST snapshots, pins, history
    store.ts          tiny external store + useSyncExternalStore hook
    ws.ts             auto-reconnecting WebSocket with backoff
    chat.ts           chat transcript reducer
    api.ts            typed REST clients (vehicle, agent)
    hud.ts            HUD math (wrap360, pitch→px, heading tape ticks…)
    sparkline.ts      SVG path builder with min/max downsampling
    markdown.ts       safe markdown-subset parser (rendered without innerHTML)
    format.ts         null → "--", durations, distances…
    url.ts, settings.ts, mapgeo.ts
  state/              React context, health polling, map focus bus
  components/         TopBar, MapView, Hud (canvas), TelemetryStrip, EventLog,
                      Inspector, WatchPanel, Chat, ProposalCard, …
src-tauri/            Tauri 2 shell (Rust), config, capabilities, icons
scripts/gen_icon.py   regenerates the app icon (stdlib only); then run
                      `npx tauri icon app-icon.png`
```

## Safety model in the UI

- The LLM never arms, disarms, changes mode or uploads. Those actions are
  buttons that call the vehicle service directly. Arm/disarm asks for
  confirmation first.
- **Approve** and **Reject** on a proposal card go straight to
  `POST {vehicle}/api/proposals/{id}/approve|reject`, never through the agent.
  Approve is enabled only when the status is `pending`, and it asks for
  confirmation.
- The **Commands** toggle (`POST /api/command`) is off by default. When it is
  on, a warning banner reads "COMMAND MODE ON — LLM may propose missions".
  Chat requests send `commands_enabled` to match the toggle.
