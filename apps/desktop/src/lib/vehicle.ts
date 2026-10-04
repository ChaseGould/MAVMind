// Vehicle-service state: a pure reducer over WebSocket frames and REST
// responses. Slices that do not change keep their identity so selectors stay
// cheap.
import type {
  Geofence,
  MessageDetail,
  MessageSummary,
  MissionState,
  ProfilesResponse,
  Proposal,
  ProposalStatus,
  StateFrame,
  VehicleEvent,
  WsFrame,
} from "../types";

export const TRACK_MAX = 2000;
export const EVENTS_MAX = 500;
export const HISTORY_MAX = 120;

export type WsStatus = "connecting" | "open" | "closed";

export type VehicleData = {
  ws: WsStatus;
  state: StateFrame | null;
  track: [number, number][];
  messages: MessageSummary[];
  details: Record<string, MessageDetail>;
  events: VehicleEvent[];
  proposals: Record<string, Proposal>;
  mission: MissionState | null;
  commandEnabled: boolean | null;
  geofence: Geofence | null;
  modes: string[];
  profiles: ProfilesResponse | null;
  /** Message types expanded in the inspector. */
  expanded: string[];
  /** Pinned numeric fields, "MESSAGE.field". */
  pins: string[];
  /** Recent numeric samples per pinned field. */
  history: Record<string, number[]>;
};

export type VehicleAction =
  | { type: "frame"; frame: WsFrame }
  | { type: "ws"; status: WsStatus }
  | { type: "proposal"; proposal: Proposal; ifAbsent?: boolean }
  | { type: "proposals"; proposals: Proposal[] }
  | { type: "mission"; mission: MissionState }
  | { type: "events"; events: VehicleEvent[] }
  | { type: "geofence"; geofence: Geofence | null }
  | { type: "command"; enabled: boolean }
  | { type: "modes"; modes: string[] }
  | { type: "profiles"; profiles: ProfilesResponse }
  | { type: "expand"; name: string; expanded: boolean }
  | { type: "pin"; key: string }
  | { type: "unpin"; key: string }
  | { type: "clearTrack" };

export function initialVehicleData(pins: string[] = []): VehicleData {
  return {
    ws: "connecting",
    state: null,
    track: [],
    messages: [],
    details: {},
    events: [],
    proposals: {},
    mission: null,
    commandEnabled: null,
    geofence: null,
    modes: [],
    profiles: null,
    expanded: [],
    pins: [...new Set(pins)],
    history: {},
  };
}

export function pinKey(message: string, field: string): string {
  return `${message}.${field}`;
}

export function splitPin(key: string): { message: string; field: string } {
  const i = key.indexOf(".");
  return i < 0 ? { message: key, field: "" } : { message: key.slice(0, i), field: key.slice(i + 1) };
}

/** Message types the inspector needs streamed: expanded types + pinned types. */
export function subscriptionNames(expanded: string[], pins: string[]): string[] {
  const set = new Set<string>(expanded);
  for (const p of pins) set.add(splitPin(p).message);
  return [...set].filter(Boolean).sort();
}

const TERMINAL: ProposalStatus[] = ["uploaded", "upload_failed", "rejected"];

/**
 * Merge an incoming proposal snapshot. Snapshots are full objects; the newest
 * one wins, except that a late "uploading" frame must not overwrite a terminal
 * result we already have (WS frames and the approve response can race).
 */
export function mergeProposal(existing: Proposal | undefined, incoming: Proposal): Proposal {
  if (!existing) return incoming;
  if (TERMINAL.includes(existing.status) && incoming.status === "uploading") return existing;
  return incoming;
}

/** Proposals newest first. */
export function sortedProposals(map: Record<string, Proposal>): Proposal[] {
  return Object.values(map).sort((a, b) => b.created_at - a.created_at);
}

const eventKey = (e: VehicleEvent) => `${e.timestamp}|${e.kind}|${e.message}`;

function appendTrack(track: [number, number][], f: StateFrame): [number, number][] {
  if (f.lat === null || f.lon === null) return track;
  const last = track[track.length - 1];
  // Skip samples that have not moved (~1 cm), so a parked vehicle does not
  // churn the trail.
  if (last && Math.abs(last[0] - f.lat) < 1e-7 && Math.abs(last[1] - f.lon) < 1e-7) return track;
  const next = track.length >= TRACK_MAX ? track.slice(track.length - TRACK_MAX + 1) : track.slice();
  next.push([f.lat, f.lon]);
  return next;
}

function recordHistory(
  history: Record<string, number[]>,
  pins: string[],
  detail: MessageDetail,
): Record<string, number[]> {
  let next = history;
  const prefix = `${detail.name}.`;
  for (const key of pins) {
    if (!key.startsWith(prefix)) continue;
    const v = detail.fields[key.slice(prefix.length)];
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    if (next === history) next = { ...history };
    const prev = next[key] ?? [];
    const arr = prev.length >= HISTORY_MAX ? prev.slice(prev.length - HISTORY_MAX + 1) : prev.slice();
    arr.push(v);
    next[key] = arr;
  }
  return next;
}

function reduceFrame(s: VehicleData, frame: WsFrame): VehicleData {
  switch (frame.type) {
    case "state": {
      const f = frame.data;
      const profileChanged = !!s.state && s.state.profile !== f.profile;
      const track = appendTrack(profileChanged ? [] : s.track, f);
      return { ...s, state: f, track };
    }
    case "messages":
      return { ...s, messages: frame.data };
    case "message": {
      const d = frame.data;
      return {
        ...s,
        details: { ...s.details, [d.name]: d },
        history: recordHistory(s.history, s.pins, d),
      };
    }
    case "event":
      return reduceVehicle(s, { type: "events", events: [frame.data] });
    case "proposal":
      return reduceVehicle(s, { type: "proposal", proposal: frame.data });
    case "mission":
      return { ...s, mission: frame.data };
    case "command":
      return { ...s, commandEnabled: !!frame.data.enabled };
    default:
      return s;
  }
}

export function reduceVehicle(s: VehicleData, a: VehicleAction): VehicleData {
  switch (a.type) {
    case "frame":
      return reduceFrame(s, a.frame);
    case "ws":
      return s.ws === a.status ? s : { ...s, ws: a.status };
    case "proposal": {
      const existing = s.proposals[a.proposal.id];
      if (a.ifAbsent && existing) return s;
      const merged = mergeProposal(existing, a.proposal);
      if (merged === existing) return s;
      return { ...s, proposals: { ...s.proposals, [merged.id]: merged } };
    }
    case "proposals": {
      const proposals = { ...s.proposals };
      for (const p of a.proposals) proposals[p.id] = mergeProposal(proposals[p.id], p);
      return { ...s, proposals };
    }
    case "mission":
      return { ...s, mission: a.mission };
    case "events": {
      if (a.events.length === 0) return s;
      const seen = new Set(s.events.map(eventKey));
      const fresh = a.events.filter((e) => {
        const k = eventKey(e);
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
      if (fresh.length === 0) return s;
      let events = [...s.events, ...fresh];
      // Bulk loads may be out of order; keep chronological order.
      if (fresh.length > 1 || (s.events.length && fresh[0].timestamp < s.events[s.events.length - 1].timestamp)) {
        events.sort((x, y) => x.timestamp - y.timestamp);
      }
      if (events.length > EVENTS_MAX) events = events.slice(events.length - EVENTS_MAX);
      return { ...s, events };
    }
    case "geofence":
      return { ...s, geofence: a.geofence };
    case "command":
      return s.commandEnabled === a.enabled ? s : { ...s, commandEnabled: a.enabled };
    case "modes":
      return { ...s, modes: a.modes };
    case "profiles":
      return { ...s, profiles: a.profiles };
    case "expand": {
      const has = s.expanded.includes(a.name);
      if (has === a.expanded) return s;
      return {
        ...s,
        expanded: a.expanded ? [...s.expanded, a.name] : s.expanded.filter((n) => n !== a.name),
      };
    }
    case "pin": {
      if (s.pins.includes(a.key)) return s;
      return { ...s, pins: [...s.pins, a.key] };
    }
    case "unpin": {
      if (!s.pins.includes(a.key)) return s;
      const history = { ...s.history };
      delete history[a.key];
      return { ...s, pins: s.pins.filter((p) => p !== a.key), history };
    }
    case "clearTrack":
      return s.track.length ? { ...s, track: [] } : s;
    default:
      return s;
  }
}

/** Parse one WebSocket text frame; returns null for anything malformed. */
export function parseWsFrame(text: string): WsFrame | null {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object") return null;
  const { type, data } = obj as { type?: unknown; data?: unknown };
  if (typeof type !== "string" || data === undefined || data === null) return null;
  switch (type) {
    case "state":
    case "message":
    case "event":
    case "proposal":
    case "mission":
    case "command":
      return typeof data === "object" && !Array.isArray(data) ? ({ type, data } as WsFrame) : null;
    case "messages":
      return Array.isArray(data) ? ({ type, data } as WsFrame) : null;
    default:
      return null;
  }
}
