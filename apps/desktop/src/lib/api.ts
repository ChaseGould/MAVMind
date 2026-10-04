// Typed REST clients for the vehicle and agent services.
import type {
  AgentHealth,
  ChatEvent,
  ChatRequest,
  ConnectResponse,
  Geofence,
  MessageDetail,
  MessageSummary,
  MissionState,
  OkMessage,
  ProfilesResponse,
  Proposal,
  VehicleEvent,
  VehicleHealth,
} from "../types";
import { readNdjson } from "./ndjson";
import { joinUrl } from "./url";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function errorMessage(res: Response): Promise<string> {
  let text = "";
  try {
    text = await res.text();
  } catch {
    /* ignore */
  }
  try {
    const j = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown };
    const d = j.detail ?? j.message ?? j.error;
    if (typeof d === "string") return d;
    if (d !== undefined) return JSON.stringify(d);
  } catch {
    /* not JSON */
  }
  return text.trim() || `${res.status} ${res.statusText}`;
}

export async function requestJson<T>(
  base: string,
  path: string,
  init: RequestInit & { json?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const { json, timeoutMs = 15_000, ...rest } = init;
  const ctrl = new AbortController();
  const outer = rest.signal;
  const onAbort = () => ctrl.abort();
  outer?.addEventListener("abort", onAbort);
  const timer = timeoutMs > 0 ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  try {
    const res = await fetch(joinUrl(base, path), {
      ...rest,
      signal: ctrl.signal,
      headers: json !== undefined ? { "Content-Type": "application/json", ...(rest.headers ?? {}) } : rest.headers,
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
    if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
    return (await res.json()) as T;
  } finally {
    if (timer) clearTimeout(timer);
    outer?.removeEventListener("abort", onAbort);
  }
}

const post = { method: "POST" } as const;

export function vehicleApi(base: string) {
  return {
    health: (signal?: AbortSignal) => requestJson<VehicleHealth>(base, "/health", { signal, timeoutMs: 2500 }),
    profiles: () => requestJson<ProfilesResponse>(base, "/api/profiles"),
    connect: (profile: string) =>
      requestJson<ConnectResponse>(base, "/api/connect", { ...post, json: { profile }, timeoutMs: 60_000 }),
    disconnect: () => requestJson<{ ok: boolean }>(base, "/api/disconnect", { ...post, json: {} }),
    messages: () => requestJson<{ messages: MessageSummary[] }>(base, "/api/messages"),
    message: (name: string) => requestJson<MessageDetail>(base, `/api/messages/${encodeURIComponent(name)}`),
    mission: () => requestJson<MissionState>(base, "/api/mission"),
    refreshMission: () =>
      requestJson<MissionState>(base, "/api/mission/refresh", { ...post, json: {}, timeoutMs: 60_000 }),
    geofence: () => requestJson<Geofence>(base, "/api/geofence"),
    events: (since: number) => requestJson<{ events: VehicleEvent[] }>(base, `/api/events?since=${since}`),
    modes: () => requestJson<{ modes: string[] }>(base, "/api/modes"),
    arm: (armed: boolean) => requestJson<OkMessage>(base, "/api/actions/arm", { ...post, json: { armed } }),
    setMode: (mode: string) => requestJson<OkMessage>(base, "/api/actions/mode", { ...post, json: { mode } }),
    getCommand: () => requestJson<{ enabled: boolean }>(base, "/api/command"),
    setCommand: (enabled: boolean) =>
      requestJson<{ enabled: boolean }>(base, "/api/command", { ...post, json: { enabled } }),
    proposals: () => requestJson<{ proposals: Proposal[] }>(base, "/api/proposals"),
    proposal: (id: string) => requestJson<Proposal>(base, `/api/proposals/${encodeURIComponent(id)}`),
    // Upload + readback can take a while on a real link.
    approve: (id: string) =>
      requestJson<Proposal>(base, `/api/proposals/${encodeURIComponent(id)}/approve`, {
        ...post,
        json: {},
        timeoutMs: 120_000,
      }),
    reject: (id: string, reason?: string) =>
      requestJson<Proposal>(base, `/api/proposals/${encodeURIComponent(id)}/reject`, {
        ...post,
        json: reason ? { reason } : {},
      }),
  };
}

export type VehicleApi = ReturnType<typeof vehicleApi>;

export function agentApi(base: string) {
  return {
    health: (signal?: AbortSignal) => requestJson<AgentHealth>(base, "/health", { signal, timeoutMs: 2500 }),
    reset: (session_id: string) =>
      requestJson<{ ok: boolean }>(base, "/api/chat/reset", { ...post, json: { session_id } }),
    /**
     * Stream a chat turn. Yields ChatEvents as NDJSON lines arrive; malformed
     * lines become `error` events. Abort via `signal`.
     */
    async *chat(req: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatEvent> {
      const res = await fetch(joinUrl(base, "/api/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
        body: JSON.stringify(req),
        signal,
      });
      if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
      if (!res.body) throw new ApiError("Response has no body", res.status);
      for await (const line of readNdjson<ChatEvent>(res.body)) {
        if (line.ok) {
          if (line.value && typeof line.value === "object" && typeof line.value.type === "string") yield line.value;
        } else {
          yield { type: "error", message: `Unparseable stream line: ${line.line.slice(0, 200)}` };
        }
      }
    },
  };
}

export type AgentApi = ReturnType<typeof agentApi>;
