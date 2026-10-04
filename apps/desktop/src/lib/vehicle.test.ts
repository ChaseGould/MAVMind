import { describe, expect, it } from "vitest";
import { detail, proposal, stateFrame } from "./fixtures";
import {
  EVENTS_MAX,
  HISTORY_MAX,
  TRACK_MAX,
  initialVehicleData,
  mergeProposal,
  parseWsFrame,
  reduceVehicle,
  sortedProposals,
  splitPin,
  subscriptionNames,
  type VehicleAction,
  type VehicleData,
} from "./vehicle";
import type { WsFrame } from "../types";

const frame = (s: VehicleData, f: WsFrame) => reduceVehicle(s, { type: "frame", frame: f });
const run = (s: VehicleData, actions: VehicleAction[]) => actions.reduce(reduceVehicle, s);

describe("state frames", () => {
  it("stores the latest frame and appends the track", () => {
    let s = initialVehicleData();
    s = frame(s, { type: "state", data: stateFrame({ lat: 1, lon: 2 }) });
    s = frame(s, { type: "state", data: stateFrame({ lat: 1, lon: 2 }) }); // unchanged position
    s = frame(s, { type: "state", data: stateFrame({ lat: 1.001, lon: 2 }) });
    s = frame(s, { type: "state", data: stateFrame({ lat: null, lon: null }) });
    expect(s.track).toEqual([
      [1, 2],
      [1.001, 2],
    ]);
    expect(s.state?.lat).toBeNull();
  });

  it("caps the track at TRACK_MAX points, keeping the newest", () => {
    let s = initialVehicleData();
    for (let i = 0; i < TRACK_MAX + 50; i++) s = frame(s, { type: "state", data: stateFrame({ lat: i * 1e-4, lon: 0.5 }) });
    expect(s.track.length).toBe(TRACK_MAX);
    expect(s.track[s.track.length - 1][0]).toBeCloseTo((TRACK_MAX + 49) * 1e-4);
    expect(s.track[0][0]).toBeCloseTo(50 * 1e-4);
  });

  it("resets the track when the profile changes", () => {
    let s = initialVehicleData();
    s = frame(s, { type: "state", data: stateFrame({ lat: 1, lon: 1 }) });
    s = frame(s, { type: "state", data: stateFrame({ profile: "other", lat: 2, lon: 2 }) });
    expect(s.track).toEqual([[2, 2]]);
  });

  it("keeps unrelated slices identical (cheap selectors)", () => {
    const s0 = initialVehicleData();
    const s1 = frame(s0, { type: "state", data: stateFrame() });
    expect(s1.messages).toBe(s0.messages);
    expect(s1.proposals).toBe(s0.proposals);
    expect(s1.events).toBe(s0.events);
  });
});

describe("messages, pins and history", () => {
  it("records numeric samples only for pinned fields, capped", () => {
    let s = initialVehicleData(["ATTITUDE.roll", "VFR_HUD.alt"]);
    for (let i = 0; i < HISTORY_MAX + 10; i++) {
      s = frame(s, { type: "message", data: detail("ATTITUDE", { roll: i, pitch: 0, name: "x" }) });
    }
    expect(s.history["ATTITUDE.roll"].length).toBe(HISTORY_MAX);
    expect(s.history["ATTITUDE.roll"][HISTORY_MAX - 1]).toBe(HISTORY_MAX + 9);
    expect(s.history["ATTITUDE.pitch"]).toBeUndefined();
    expect(s.history["VFR_HUD.alt"]).toBeUndefined();
    expect(s.details.ATTITUDE.fields.roll).toBe(HISTORY_MAX + 9);
  });

  it("ignores non-numeric values for pinned fields", () => {
    let s = initialVehicleData(["X.v"]);
    s = frame(s, { type: "message", data: detail("X", { v: null }) });
    s = frame(s, { type: "message", data: detail("X", { v: "str" }) });
    s = frame(s, { type: "message", data: detail("X", { v: [1, 2] }) });
    expect(s.history["X.v"]).toBeUndefined();
  });

  it("pin/unpin are idempotent and unpin drops history", () => {
    let s = run(initialVehicleData(), [
      { type: "pin", key: "A.x" },
      { type: "pin", key: "A.x" },
      { type: "frame", frame: { type: "message", data: detail("A", { x: 1 }) } },
    ]);
    expect(s.pins).toEqual(["A.x"]);
    expect(s.history["A.x"]).toEqual([1]);
    s = reduceVehicle(s, { type: "unpin", key: "A.x" });
    expect(s.pins).toEqual([]);
    expect(s.history["A.x"]).toBeUndefined();
    expect(reduceVehicle(s, { type: "unpin", key: "A.x" })).toBe(s);
  });

  it("subscription = expanded types + pinned types, sorted unique", () => {
    expect(subscriptionNames(["VFR_HUD", "ATTITUDE"], ["ATTITUDE.roll", "GPS_RAW_INT.eph"])).toEqual([
      "ATTITUDE",
      "GPS_RAW_INT",
      "VFR_HUD",
    ]);
    expect(subscriptionNames([], [])).toEqual([]);
    expect(splitPin("A.b.c")).toEqual({ message: "A", field: "b.c" });
  });

  it("expand toggles the expanded list", () => {
    let s = reduceVehicle(initialVehicleData(), { type: "expand", name: "HEARTBEAT", expanded: true });
    expect(s.expanded).toEqual(["HEARTBEAT"]);
    expect(reduceVehicle(s, { type: "expand", name: "HEARTBEAT", expanded: true })).toBe(s);
    s = reduceVehicle(s, { type: "expand", name: "HEARTBEAT", expanded: false });
    expect(s.expanded).toEqual([]);
  });
});

describe("events", () => {
  it("dedupes, orders and caps", () => {
    let s = initialVehicleData();
    const e = (t: number, m = "m") => ({ timestamp: t, kind: "statustext" as const, message: m, severity: "INFO" });
    s = reduceVehicle(s, { type: "events", events: [e(3), e(1), e(2)] });
    s = frame(s, { type: "event", data: e(2) });
    expect(s.events.map((x) => x.timestamp)).toEqual([1, 2, 3]);
    const many = Array.from({ length: EVENTS_MAX + 20 }, (_, i) => e(100 + i));
    s = reduceVehicle(s, { type: "events", events: many });
    expect(s.events.length).toBe(EVENTS_MAX);
    expect(s.events[s.events.length - 1].timestamp).toBe(100 + EVENTS_MAX + 19);
  });
});

describe("proposals", () => {
  it("upserts from ws frames and sorts newest first", () => {
    let s = initialVehicleData();
    s = frame(s, { type: "proposal", data: proposal({ id: "a", created_at: 1 }) });
    s = frame(s, { type: "proposal", data: proposal({ id: "b", created_at: 2 }) });
    s = frame(s, { type: "proposal", data: proposal({ id: "a", created_at: 1, status: "rejected" }) });
    expect(sortedProposals(s.proposals).map((p) => [p.id, p.status])).toEqual([
      ["b", "pending"],
      ["a", "rejected"],
    ]);
  });

  it("ifAbsent never overwrites (chat stream copies are not authoritative)", () => {
    let s = frame(initialVehicleData(), { type: "proposal", data: proposal({ status: "uploaded" }) });
    const s2 = reduceVehicle(s, { type: "proposal", proposal: proposal({ status: "pending" }), ifAbsent: true });
    expect(s2).toBe(s);
    s = reduceVehicle(initialVehicleData(), { type: "proposal", proposal: proposal(), ifAbsent: true });
    expect(s.proposals.p1.status).toBe("pending");
  });

  it("a late 'uploading' frame does not overwrite a terminal result", () => {
    const done = proposal({ status: "uploaded", upload: { ok: true, message: "", verified: true, diff: [] } });
    expect(mergeProposal(done, proposal({ status: "uploading" }))).toBe(done);
    const failed = proposal({ status: "upload_failed" });
    const retry = proposal({ status: "pending" });
    expect(mergeProposal(failed, retry)).toBe(retry);
  });
});

describe("misc frames", () => {
  it("mission and command frames", () => {
    let s = frame(initialVehicleData(), { type: "mission", data: { items: [], current_seq: 3 } });
    expect(s.mission?.current_seq).toBe(3);
    s = frame(s, { type: "command", data: { enabled: true } });
    expect(s.commandEnabled).toBe(true);
    s = frame(s, { type: "messages", data: [{ name: "HEARTBEAT", rate_hz: 1, age_s: 0.1, count: 5 }] });
    expect(s.messages[0].name).toBe("HEARTBEAT");
  });

  it("ws status no-ops when unchanged", () => {
    const s = initialVehicleData();
    expect(reduceVehicle(s, { type: "ws", status: "connecting" })).toBe(s);
    expect(reduceVehicle(s, { type: "ws", status: "open" }).ws).toBe("open");
  });
});

describe("parseWsFrame", () => {
  it("accepts well-formed frames", () => {
    expect(parseWsFrame('{"type":"command","data":{"enabled":false}}')).toEqual({
      type: "command",
      data: { enabled: false },
    });
    expect(parseWsFrame('{"type":"messages","data":[]}')).toEqual({ type: "messages", data: [] });
  });
  it("rejects malformed frames", () => {
    expect(parseWsFrame("not json")).toBeNull();
    expect(parseWsFrame('{"type":"state"}')).toBeNull();
    expect(parseWsFrame('{"type":"messages","data":{}}')).toBeNull();
    expect(parseWsFrame('{"type":"state","data":[]}')).toBeNull();
    expect(parseWsFrame('{"type":"bogus","data":{}}')).toBeNull();
    expect(parseWsFrame("[1,2]")).toBeNull();
  });
});
