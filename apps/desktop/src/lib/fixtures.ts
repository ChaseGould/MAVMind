// Test fixtures (imported by *.test.ts only).
import type { MessageDetail, Proposal, StateFrame } from "../types";

export function stateFrame(over: Partial<StateFrame> = {}): StateFrame {
  return {
    timestamp: 1000,
    connected: true,
    profile: "sitl",
    source: "mavlink",
    vehicle_type: "copter",
    mode: "GUIDED",
    armed: false,
    lat: -35.36,
    lon: 149.16,
    alt_msl_m: 600,
    alt_rel_m: 10,
    heading_deg: 90,
    roll_deg: 0,
    pitch_deg: 0,
    yaw_deg: 90,
    airspeed_mps: null,
    groundspeed_mps: 0,
    climb_mps: 0,
    throttle_pct: 0,
    battery_voltage_v: 12.6,
    battery_current_a: 1.2,
    battery_remaining_pct: 99,
    gps_fix_type: 3,
    gps_fix_name: "3D",
    gps_sats: 10,
    hdop: 0.8,
    link: { last_heartbeat_age_s: 0.2, rssi: null, remrssi: null, packet_loss_pct: 0, quality_pct: null },
    home: { lat: -35.36, lon: 149.16, alt_msl_m: 590 },
    distance_home_m: 0,
    bearing_home_deg: null,
    flight_time_s: 0,
    mission_current_seq: null,
    ekf_ok: true,
    ...over,
  };
}

export function detail(name: string, fields: MessageDetail["fields"]): MessageDetail {
  return { name, timestamp: 1, age_s: 0, rate_hz: 10, sysid: 1, compid: 1, fields };
}

export function proposal(over: Partial<Proposal> = {}): Proposal {
  return {
    id: "p1",
    created_at: 100,
    status: "pending",
    mission: { name: "Box", items: [{ command: "NAV_TAKEOFF", alt_m: 20 }] },
    items: [
      { seq: 1, command: "NAV_TAKEOFF", frame: "GLOBAL_RELATIVE_ALT", params: [0, 0, 0, 0], lat: null, lon: null, alt_m: 20 },
    ],
    validation: {
      ok: true,
      checks: [{ name: "geofence", ok: true, message: "inside" }],
      estimates: { total_distance_m: 100, flight_time_s: 60, battery_required_pct: 5, battery_available_pct: 90 },
    },
    upload: null,
    reject_reason: null,
    ...over,
  };
}
