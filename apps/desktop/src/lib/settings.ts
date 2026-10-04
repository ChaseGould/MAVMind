// Service base URLs, persisted in localStorage.
import { trimBase } from "./url";

export type ServiceUrls = { vehicle: string; agent: string };

const KEY = "mavmind.serviceUrls";
export const PINS_KEY = "mavmind.pins";

export const FALLBACK_URLS: ServiceUrls = {
  vehicle: "http://127.0.0.1:8700",
  agent: "http://127.0.0.1:8701",
};

export function defaultUrls(env: Record<string, unknown> = import.meta.env): ServiceUrls {
  const v = typeof env.VITE_VEHICLE_URL === "string" && env.VITE_VEHICLE_URL ? env.VITE_VEHICLE_URL : FALLBACK_URLS.vehicle;
  const a = typeof env.VITE_AGENT_URL === "string" && env.VITE_AGENT_URL ? env.VITE_AGENT_URL : FALLBACK_URLS.agent;
  return { vehicle: trimBase(v), agent: trimBase(a) };
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = storage()?.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function saveJson(key: string, value: unknown): void {
  try {
    storage()?.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: keep in memory only */
  }
}

export function loadUrls(): ServiceUrls {
  const d = defaultUrls();
  const saved = loadJson<Partial<ServiceUrls>>(KEY, {});
  return {
    vehicle: typeof saved.vehicle === "string" && saved.vehicle ? trimBase(saved.vehicle) : d.vehicle,
    agent: typeof saved.agent === "string" && saved.agent ? trimBase(saved.agent) : d.agent,
  };
}

export function saveUrls(u: ServiceUrls): void {
  saveJson(KEY, { vehicle: trimBase(u.vehicle), agent: trimBase(u.agent) });
}

export function clearUrls(): void {
  try {
    storage()?.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function loadPins(): string[] {
  const p = loadJson<unknown>(PINS_KEY, []);
  return Array.isArray(p) ? p.filter((x): x is string => typeof x === "string") : [];
}

export function savePins(pins: string[]): void {
  saveJson(PINS_KEY, pins);
}
