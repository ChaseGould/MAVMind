// Chat transcript reducer: applies NDJSON ChatEvents from the agent service to
// the assistant turn currently being streamed.
import type { ChatEvent } from "../types";

export type ToolPart = {
  kind: "tool";
  id: string;
  name: string;
  input: unknown;
  output: string | null;
  is_error: boolean;
};

export type AssistantPart =
  | { kind: "text"; text: string }
  | ToolPart
  | { kind: "proposal"; id: string }
  | { kind: "error"; message: string };

export type Turn =
  | { role: "user"; id: number; text: string }
  | {
      role: "assistant";
      id: number;
      parts: AssistantPart[];
      /** null while streaming; stop_reason, "stopped" (user abort) or "error" when finished. */
      end: string | null;
    };

export type ChatState = {
  sessionId: string;
  turns: Turn[];
  streaming: boolean;
  nextId: number;
};

export type ChatAction =
  | { type: "send"; text: string }
  | { type: "event"; event: ChatEvent }
  | { type: "finish"; reason: string }
  | { type: "reset"; sessionId: string };

export function initialChat(sessionId: string): ChatState {
  return { sessionId, turns: [], streaming: false, nextId: 1 };
}

function updateLastAssistant(
  s: ChatState,
  fn: (t: Extract<Turn, { role: "assistant" }>) => Extract<Turn, { role: "assistant" }>,
): ChatState {
  const idx = s.turns.length - 1;
  const last = s.turns[idx];
  if (!last || last.role !== "assistant") return s;
  const turns = s.turns.slice();
  turns[idx] = fn(last);
  return { ...s, turns };
}

export function applyChatEvent(parts: AssistantPart[], ev: ChatEvent): AssistantPart[] {
  switch (ev.type) {
    case "text_delta": {
      if (!ev.text) return parts;
      const last = parts[parts.length - 1];
      if (last && last.kind === "text") {
        const next = parts.slice();
        next[next.length - 1] = { kind: "text", text: last.text + ev.text };
        return next;
      }
      return [...parts, { kind: "text", text: ev.text }];
    }
    case "tool_call":
      return [
        ...parts,
        { kind: "tool", id: ev.id, name: ev.name, input: ev.input, output: null, is_error: false },
      ];
    case "tool_result": {
      let found = false;
      const next = parts.map((p) => {
        if (!found && p.kind === "tool" && p.id === ev.id) {
          found = true;
          return { ...p, output: ev.output, is_error: ev.is_error };
        }
        return p;
      });
      if (found) return next;
      // Result without a matching call: still show it.
      return [
        ...parts,
        { kind: "tool", id: ev.id, name: ev.name, input: null, output: ev.output, is_error: ev.is_error },
      ];
    }
    case "proposal":
      if (parts.some((p) => p.kind === "proposal" && p.id === ev.proposal.id)) return parts;
      return [...parts, { kind: "proposal", id: ev.proposal.id }];
    case "error":
      return [...parts, { kind: "error", message: ev.message }];
    case "done":
    default:
      return parts;
  }
}

export function reduceChat(s: ChatState, a: ChatAction): ChatState {
  switch (a.type) {
    case "send": {
      const user: Turn = { role: "user", id: s.nextId, text: a.text };
      const asst: Turn = { role: "assistant", id: s.nextId + 1, parts: [], end: null };
      return { ...s, turns: [...s.turns, user, asst], streaming: true, nextId: s.nextId + 2 };
    }
    case "event": {
      const ev = a.event;
      const next = updateLastAssistant(s, (t) => {
        if (t.end !== null) return t;
        const parts = applyChatEvent(t.parts, ev);
        if (ev.type === "done") return { ...t, parts, end: ev.stop_reason ?? "end_turn" };
        return parts === t.parts ? t : { ...t, parts };
      });
      return ev.type === "done" ? { ...next, streaming: false } : next;
    }
    case "finish": {
      const next = updateLastAssistant(s, (t) => (t.end === null ? { ...t, end: a.reason } : t));
      return { ...next, streaming: false };
    }
    case "reset":
      return initialChat(a.sessionId);
    default:
      return s;
  }
}

/** Generate a session id; falls back when crypto.randomUUID is unavailable. */
export function newSessionId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return "s-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}
