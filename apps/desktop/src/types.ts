// Contract types. These mirror docs/api.md exactly; keep them in sync.
// Every unknown value is `null`, never a guess. Units are in field names.

// ---------------------------------------------------------------------------
// Vehicle service
// ---------------------------------------------------------------------------

export type LinkStats = {
  last_heartbeat_age_s: number | null;
  rssi: number | null;
  remrssi: number | null;
  packet_loss_pct: number | null;
  quality_pct: number | null;
};

export type Home = { lat: number; lon: number; alt_msl_m: number };

export type StateFrame = {
  timestamp: number; // unix seconds, source clock
  connected: boolean;
  profile: string | null;
  source: string | null; // "mavlink" | "mavros" | "replay"
  vehicle_type: string | null; // "copter" | "plane" | "rover" | ...
  mode: string | null;
  armed: boolean | null;
  lat: number | null;
  lon: number | null;
  alt_msl_m: number | null;
  alt_rel_m: number | null;
  heading_deg: number | null;
  roll_deg: number | null;
  pitch_deg: number | null;
  yaw_deg: number | null;
  airspeed_mps: number | null;
  groundspeed_mps: number | null;
  climb_mps: number | null;
  throttle_pct: number | null;
  battery_voltage_v: number | null;
  battery_current_a: number | null;
  battery_remaining_pct: number | null;
  gps_fix_type: number | null;
  gps_fix_name: string | null;
  gps_sats: number | null;
  hdop: number | null;
  link: LinkStats;
  home: Home | null;
  distance_home_m: number | null;
  bearing_home_deg: number | null;
  flight_time_s: number | null;
  mission_current_seq: number | null;
  ekf_ok: boolean | null;
};

export type MessageSummary = { name: string; rate_hz: number; age_s: number; count: number };

export type FieldValue = number | string | number[] | null;

export type MessageDetail = {
  name: string;
  timestamp: number;
  age_s: number;
  rate_hz: number;
  sysid: number;
  compid: number;
  fields: Record<string, FieldValue>; // raw MAVLink fields
};

export type EventKind =
  | "mode_change"
  | "armed"
  | "disarmed"
  | "statustext"
  | "failsafe"
  | "mission_progress"
  | "link";

export type VehicleEvent = {
  timestamp: number;
  kind: EventKind;
  message: string;
  severity?: string; // for statustext/failsafe: "EMERGENCY".."DEBUG"
  data?: Record<string, unknown>;
};
/** Alias with the contract's name (shadows the DOM `Event` only when imported). */
export type Event = VehicleEvent;

export type MissionItem = {
  seq: number;
  command: string; // "NAV_WAYPOINT", "NAV_TAKEOFF", ...
  frame: string; // "GLOBAL_RELATIVE_ALT", ...
  params: [number, number, number, number];
  lat: number | null;
  lon: number | null;
  alt_m: number | null;
};

export type MissionState = { items: MissionItem[]; current_seq: number | null };

export type Check = { name: string; ok: boolean; message: string };

export type ProposalStatus =
  | "invalid"
  | "pending"
  | "uploading"
  | "uploaded"
  | "upload_failed"
  | "rejected";

export type Estimates = {
  total_distance_m: number | null;
  flight_time_s: number | null;
  battery_required_pct: number | null;
  battery_available_pct: number | null;
};

export type UploadResult = { ok: boolean; message: string; verified: boolean; diff: string[] };

export type Proposal = {
  id: string;
  created_at: number;
  status: ProposalStatus;
  mission: Mission; // as proposed, matches shared/mission_schema.json
  items: MissionItem[]; // expanded items for the map (seq 1..N; seq 0 is home)
  validation: {
    ok: boolean;
    checks: Check[];
    estimates: Estimates;
  };
  upload: UploadResult | null;
  reject_reason: string | null;
};

export type Geofence = {
  polygon: [number, number][];
  max_alt_m: number | null;
  min_alt_m: number | null;
  max_distance_from_home_m: number | null;
};

export type VehicleHealth = {
  status: "ok";
  service: "vehicle";
  profile: string | null;
  connected: boolean;
  source: string | null;
};

export type Profile = { name: string; description: string; source: string };
export type ProfilesResponse = { active: string | null; profiles: Profile[] };
export type OkMessage = { ok: boolean; message: string };
export type ConnectResponse = { ok: boolean; profile: string; message: string };

// ---------------------------------------------------------------------------
// Mission (shared/mission_schema.json)
// ---------------------------------------------------------------------------

export type MissionCommandItem =
  | { command: "NAV_TAKEOFF"; alt_m: number }
  | { command: "NAV_WAYPOINT"; lat: number; lon: number; alt_m: number; hold_s?: number }
  | { command: "NAV_LOITER_TIME"; lat: number; lon: number; alt_m: number; time_s: number }
  | { command: "NAV_LAND"; lat?: number; lon?: number }
  | { command: "NAV_RETURN_TO_LAUNCH" }
  | { command: "DO_CHANGE_SPEED"; speed_mps: number }
  | { command: "DO_SET_SERVO"; servo: number; pwm: number }
  | { command: "DO_GRIPPER"; gripper?: number; action: "release" | "grab" }
  | { command: "DO_DIGICAM_CONTROL" };

export type Mission = {
  name: string;
  description?: string;
  items: MissionCommandItem[];
};

// ---------------------------------------------------------------------------
// Vehicle WebSocket frames
// ---------------------------------------------------------------------------

export type WsFrame =
  | { type: "state"; data: StateFrame }
  | { type: "messages"; data: MessageSummary[] }
  | { type: "message"; data: MessageDetail }
  | { type: "event"; data: VehicleEvent }
  | { type: "proposal"; data: Proposal }
  | { type: "mission"; data: MissionState }
  | { type: "command"; data: { enabled: boolean } };

export type WsClientMessage = { type: "subscribe"; names: string[] };

// ---------------------------------------------------------------------------
// Agent service
// ---------------------------------------------------------------------------

export type AgentHealth = {
  status: "ok";
  service: "agent";
  model: string | null;
  readonly_mcp: boolean;
  api_key: boolean;
};

export type ChatRequest = { session_id: string; message: string; commands_enabled: boolean };

export type ChatEvent =
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; id: string; name: string; input: unknown }
  | { type: "tool_result"; id: string; name: string; output: string; is_error: boolean }
  | { type: "proposal"; proposal: Proposal }
  | { type: "done"; stop_reason: string | null }
  | { type: "error"; message: string };
