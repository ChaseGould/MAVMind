# Service API contract

Two HTTP services back the desktop UI. Both speak JSON, allow CORS from the
desktop origins, and expose `GET /health`.

| Service | Default URL | Owns |
| --- | --- | --- |
| vehicle | `http://127.0.0.1:8700` | the link, TelemetryStore, MCP servers, proposals, uploads |
| agent | `http://127.0.0.1:8701` | the LLM loop and MCP client; holds the API key |

The UI talks to both. Approve/Reject and the arm/mode buttons go from the UI
**straight to the vehicle service**; the agent never sees those endpoints.

Every value that is unknown is `null`, never a guess. Units are in field names.

---

## Vehicle service

### REST

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/health` | | `{status:"ok", service:"vehicle", profile, connected, source, error}` |
| GET | `/api/profiles` | | `{active: string\|null, profiles: [{name, description, source}]}` |
| POST | `/api/connect` | `{profile}` | `{ok, profile, message}` |
| POST | `/api/disconnect` | | `{ok}` |
| GET | `/api/state` | | `StateFrame` |
| GET | `/api/messages` | | `{messages: MessageSummary[]}` |
| GET | `/api/messages/{name}` | | `MessageDetail` (404 if never seen) |
| GET | `/api/mission` | | `{items: MissionItem[], current_seq}` |
| POST | `/api/mission/refresh` | | `{items, current_seq}` (downloads from vehicle) |
| GET | `/api/geofence` | | `{enabled, polygon: [[lat, lon], ...], max_alt_m, min_alt_m, max_distance_from_home_m}` |
| GET | `/api/events?since=<unix_s>` | | `{events: Event[]}` |
| GET | `/api/modes` | | `{modes: string[]}` for the connected vehicle type |
| POST | `/api/actions/arm` | `{armed: bool}` | `{ok, message}` |
| POST | `/api/actions/mode` | `{mode: string}` | `{ok, message}` |
| GET | `/api/command` | | `{enabled: bool}` |
| POST | `/api/command` | `{enabled: bool}` | `{enabled: bool}` |
| GET | `/api/proposals` | | `{proposals: Proposal[]}` newest first |
| GET | `/api/proposals/{id}` | | `Proposal` |
| POST | `/api/proposals/{id}/approve` | | `Proposal` (after upload + readback) |
| POST | `/api/proposals/{id}/reject` | `{reason?: string}` | `Proposal` |
| GET | `/api/audit?limit=200` | | `{records: [...]}` latest vehicle audit-log records |

The MCP servers are mounted at `/mcp/readonly/` and `/mcp/command/`
(streamable HTTP; trailing slash matters).

### WebSocket `/ws`

Server → client, each frame is `{type, data}`:

| type | rate | data |
| --- | --- | --- |
| `state` | 10 Hz | `StateFrame` |
| `messages` | 1 Hz | `MessageSummary[]` |
| `message` | ≤10 Hz per type, only subscribed types | `MessageDetail` |
| `event` | as they happen | `Event` |
| `proposal` | on create/update | `Proposal` |
| `mission` | on change | `{items: MissionItem[], current_seq}` |
| `command` | on change | `{enabled: bool}` |

Client → server:

```json
{"type": "subscribe", "names": ["ATTITUDE", "VFR_HUD"]}
```

replaces the inspector subscription set (empty list = none).

### Types

```ts
type StateFrame = {
  timestamp: number;            // unix seconds, source clock
  connected: boolean;
  profile: string | null;
  source: string | null;        // "mavlink" | "mavros" | "replay"
  vehicle_type: string | null;  // "copter" | "plane" | "rover" | ...
  mode: string | null;
  armed: boolean | null;
  lat: number | null; lon: number | null;
  alt_msl_m: number | null; alt_rel_m: number | null;
  heading_deg: number | null;
  roll_deg: number | null; pitch_deg: number | null; yaw_deg: number | null;
  airspeed_mps: number | null; groundspeed_mps: number | null;
  climb_mps: number | null; throttle_pct: number | null;
  battery_voltage_v: number | null; battery_current_a: number | null;
  battery_remaining_pct: number | null;
  gps_fix_type: number | null; gps_fix_name: string | null;
  gps_sats: number | null; hdop: number | null;
  link: {
    last_heartbeat_age_s: number | null;
    rssi: number | null; remrssi: number | null;
    packet_loss_pct: number | null; quality_pct: number | null;
  };
  home: { lat: number; lon: number; alt_msl_m: number } | null;
  distance_home_m: number | null; bearing_home_deg: number | null;
  flight_time_s: number | null;
  mission_current_seq: number | null;
  ekf_ok: boolean | null;
};

type MessageSummary = { name: string; rate_hz: number; age_s: number; count: number };

type MessageDetail = {
  name: string; timestamp: number; age_s: number; rate_hz: number;
  sysid: number; compid: number;
  fields: Record<string, number | string | number[] | null>;     // raw MAVLink fields
  converted?: Record<string, number | string | (number | null)[] | null>;  // unit-suffixed (shared/units.json)
};

type Event = {
  timestamp: number;
  kind: "mode_change" | "armed" | "disarmed" | "statustext" | "failsafe" | "mission_progress" | "link";
  message: string;
  severity?: string;            // for statustext/failsafe: "EMERGENCY".."DEBUG"
  data?: Record<string, unknown>;
};

type MissionItem = {
  seq: number;
  command: string;              // "NAV_WAYPOINT", "NAV_TAKEOFF", ...
  frame: string;                // "GLOBAL_RELATIVE_ALT", ...
  params: [number, number, number, number];
  lat: number | null; lon: number | null; alt_m: number | null;
};

type Check = { name: string; ok: boolean; message: string };

type Proposal = {
  id: string;
  created_at: number;
  status: "invalid" | "pending" | "uploading" | "uploaded" | "upload_failed" | "rejected";
  mission: Mission;             // as proposed, matches shared/mission_schema.json
  items: MissionItem[];         // expanded items for the map (seq 1..N; seq 0 is home)
  validation: {
    ok: boolean;
    checks: Check[];
    estimates: {
      total_distance_m: number | null;
      flight_time_s: number | null;
      battery_required_pct: number | null;
      battery_available_pct: number | null;
    };
  };
  upload: { ok: boolean; message: string; verified: boolean; diff: string[] } | null;
  reject_reason: string | null;
};
```

`Mission` is defined by [`shared/mission_schema.json`](../shared/mission_schema.json).

---

## Agent service

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/health` | | `{status:"ok", service:"agent", model, vehicle_url, readonly_mcp: bool, api_key: bool}` |
| POST | `/api/chat` | `{session_id, message, commands_enabled}` | NDJSON stream (below) |
| POST | `/api/chat/reset` | `{session_id}` | `{ok}` |

`/api/chat` responds with `application/x-ndjson`, one JSON object per line:

```json
{"type": "text_delta", "text": "The vehicle is in "}
{"type": "tool_call", "id": "toolu_1", "name": "get_vehicle_state", "input": {}}
{"type": "tool_result", "id": "toolu_1", "name": "get_vehicle_state", "output": "{...json...}", "is_error": false}
{"type": "proposal", "proposal": { /* Proposal */ }}
{"type": "done", "stop_reason": "end_turn"}
{"type": "error", "message": "..."}
{"type": "notice", "message": "retrying the model turn"}
```

A failed turn ends with an `error` event (and is rolled back from the session history).
Unknown event types should be ignored.

`commands_enabled` only takes effect when the vehicle service also has the
command server enabled (`POST /api/command`). The UI sets both.
