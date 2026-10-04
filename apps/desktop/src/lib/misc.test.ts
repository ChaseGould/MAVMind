import { describe, expect, it } from "vitest";
import { commandShort, missionPath, missionPoints } from "./mapgeo";
import { defaultUrls, FALLBACK_URLS } from "./settings";
import { backoffDelay } from "./ws";
import type { MissionItem } from "../types";

const item = (seq: number, command: string, lat: number | null, lon: number | null): MissionItem => ({
  seq,
  command,
  frame: "GLOBAL_RELATIVE_ALT",
  params: [0, 0, 0, 0],
  lat,
  lon,
  alt_m: 20,
});

describe("backoffDelay", () => {
  it("grows exponentially and caps", () => {
    expect([0, 1, 2, 3].map((a) => backoffDelay(a))).toEqual([500, 1000, 2000, 4000]);
    expect(backoffDelay(20)).toBe(10_000);
  });
  it("adds bounded jitter", () => {
    for (let i = 0; i < 20; i++) {
      const d = backoffDelay(1, 500, 10_000, 0.2);
      expect(d).toBeGreaterThanOrEqual(1000);
      expect(d).toBeLessThanOrEqual(1200);
    }
  });
});

describe("mission geometry", () => {
  const items = [
    item(0, "NAV_WAYPOINT", 1, 1), // home
    item(1, "NAV_TAKEOFF", null, null),
    item(2, "NAV_WAYPOINT", 1.1, 1.1),
    item(3, "NAV_WAYPOINT", 0, 0), // placeholder
    item(4, "NAV_WAYPOINT", 1.2, 1.2),
    item(5, "NAV_RETURN_TO_LAUNCH", null, null),
  ];

  it("missionPoints skips home, nulls and 0,0", () => {
    expect(missionPoints(items).map((p) => p.seq)).toEqual([2, 4]);
  });

  it("missionPath starts at home and returns on RTL", () => {
    expect(missionPath(items, { lat: 5, lon: 5 })).toEqual([
      [5, 5],
      [1.1, 1.1],
      [1.2, 1.2],
      [5, 5],
    ]);
    // Falls back to seq 0 when the state has no home.
    expect(missionPath(items, null)[0]).toEqual([1, 1]);
    expect(missionPath(items.slice(1), null)).toEqual([
      [1.1, 1.1],
      [1.2, 1.2],
    ]);
  });

  it("commandShort", () => {
    expect(commandShort("NAV_WAYPOINT")).toBe("WP");
    expect(commandShort("DO_SET_SERVO")).toBe("SET_SERVO");
  });
});

describe("defaultUrls", () => {
  it("uses env when present, else fallbacks", () => {
    expect(defaultUrls({})).toEqual(FALLBACK_URLS);
    expect(defaultUrls({ VITE_VEHICLE_URL: "http://10.0.0.2:8700/", VITE_AGENT_URL: "" })).toEqual({
      vehicle: "http://10.0.0.2:8700",
      agent: FALLBACK_URLS.agent,
    });
  });
});

import { Store } from "./store";

describe("Store", () => {
  it("notifies only on change and supports unsubscribe", () => {
    const st = new Store((s: number, a: number) => (a === 0 ? s : s + a), 1);
    let calls = 0;
    const un = st.subscribe(() => calls++);
    st.dispatch(0);
    st.dispatch(2);
    expect(st.getState()).toBe(3);
    expect(calls).toBe(1);
    un();
    st.dispatch(1);
    expect(calls).toBe(1);
  });
});
