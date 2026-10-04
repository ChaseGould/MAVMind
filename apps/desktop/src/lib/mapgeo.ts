// Geometry helpers for drawing missions on the map.
import type { Home, MissionItem } from "../types";

export type LatLon = [number, number];

/** Item has a usable position (null and the 0,0 placeholder are not). */
export function hasPosition(it: MissionItem): it is MissionItem & { lat: number; lon: number } {
  return (
    typeof it.lat === "number" &&
    typeof it.lon === "number" &&
    Number.isFinite(it.lat) &&
    Number.isFinite(it.lon) &&
    !(it.lat === 0 && it.lon === 0)
  );
}

export type MissionPoint = { seq: number; lat: number; lon: number; command: string; alt_m: number | null };

/** Positioned items after home (seq >= 1), in sequence order. */
export function missionPoints(items: MissionItem[]): MissionPoint[] {
  return items
    .filter((it) => it.seq >= 1 && hasPosition(it))
    .sort((a, b) => a.seq - b.seq)
    .map((it) => ({ seq: it.seq, lat: it.lat as number, lon: it.lon as number, command: it.command, alt_m: it.alt_m }));
}

/**
 * Polyline for a mission: starts at home (when known), visits each positioned
 * item in order, and returns to home after a RETURN_TO_LAUNCH item.
 */
export function missionPath(items: MissionItem[], home: Pick<Home, "lat" | "lon"> | null): LatLon[] {
  const sorted = items.filter((it) => it.seq >= 1).sort((a, b) => a.seq - b.seq);
  const homeItem = items.find((it) => it.seq === 0 && hasPosition(it));
  const h: LatLon | null = home ? [home.lat, home.lon] : homeItem ? [homeItem.lat as number, homeItem.lon as number] : null;
  const path: LatLon[] = h ? [h] : [];
  for (const it of sorted) {
    if (hasPosition(it)) path.push([it.lat as number, it.lon as number]);
    else if (/RETURN_TO_LAUNCH/.test(it.command) && h) path.push(h);
  }
  return path;
}

/** Short label for a mission command ("NAV_WAYPOINT" -> "WP"). */
export function commandShort(cmd: string): string {
  const map: Record<string, string> = {
    NAV_WAYPOINT: "WP",
    NAV_TAKEOFF: "TO",
    NAV_LAND: "LAND",
    NAV_LOITER_TIME: "LOIT",
    NAV_RETURN_TO_LAUNCH: "RTL",
  };
  return map[cmd] ?? cmd.replace(/^(MAV_CMD_)?(NAV_|DO_)?/, "");
}
