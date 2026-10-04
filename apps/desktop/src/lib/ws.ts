// Auto-reconnecting WebSocket to the vehicle service.
import type { WsClientMessage, WsFrame } from "../types";
import { parseWsFrame, type WsStatus } from "./vehicle";

/** Exponential backoff: 0.5 s, 1 s, 2 s, ... capped at maxMs (jitter optional). */
export function backoffDelay(attempt: number, baseMs = 500, maxMs = 10_000, jitter = 0): number {
  const d = Math.min(maxMs, baseMs * 2 ** Math.max(0, attempt));
  return Math.round(d + d * jitter * Math.random());
}

export type SocketHandlers = {
  onFrame: (f: WsFrame) => void;
  onStatus: (s: WsStatus) => void;
  onOpen?: () => void;
};

export class VehicleSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private names: string[] = [];

  constructor(
    private readonly url: string,
    private readonly handlers: SocketHandlers,
  ) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onopen = ws.onclose = ws.onerror = ws.onmessage = null;
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
    this.handlers.onStatus("closed");
  }

  /** Replace the inspector subscription set; re-sent automatically on reconnect. */
  setSubscription(names: string[]): void {
    this.names = names;
    this.sendSubscription();
  }

  private sendSubscription(): void {
    const msg: WsClientMessage = { type: "subscribe", names: this.names };
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private connect(): void {
    if (this.stopped) return;
    this.handlers.onStatus("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.handlers.onStatus("open");
      this.sendSubscription();
      this.handlers.onOpen?.();
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      const frame = parseWsFrame(ev.data);
      if (frame) this.handlers.onFrame(frame);
    };
    ws.onerror = () => {
      /* onclose follows */
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.handlers.onStatus("closed");
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = backoffDelay(this.attempt++, 500, 10_000, 0.2);
    this.timer = setTimeout(() => this.connect(), delay);
  }
}
