import { describe, expect, it } from "vitest";
import { proposal } from "./fixtures";
import { applyChatEvent, initialChat, newSessionId, reduceChat, type ChatAction, type ChatState } from "./chat";

const run = (s: ChatState, actions: ChatAction[]) => actions.reduce(reduceChat, s);

describe("chat reducer", () => {
  it("streams text deltas into one part and finishes on done", () => {
    const s = run(initialChat("s1"), [
      { type: "send", text: "hi" },
      { type: "event", event: { type: "text_delta", text: "The vehicle " } },
      { type: "event", event: { type: "text_delta", text: "is in GUIDED." } },
      { type: "event", event: { type: "done", stop_reason: "end_turn" } },
    ]);
    expect(s.streaming).toBe(false);
    expect(s.turns).toHaveLength(2);
    const a = s.turns[1];
    expect(a.role).toBe("assistant");
    if (a.role !== "assistant") throw new Error();
    expect(a.parts).toEqual([{ kind: "text", text: "The vehicle is in GUIDED." }]);
    expect(a.end).toBe("end_turn");
  });

  it("pairs tool calls with results and interleaves text", () => {
    const s = run(initialChat("s1"), [
      { type: "send", text: "state?" },
      { type: "event", event: { type: "text_delta", text: "Checking." } },
      { type: "event", event: { type: "tool_call", id: "t1", name: "get_vehicle_state", input: {} } },
      { type: "event", event: { type: "tool_result", id: "t1", name: "get_vehicle_state", output: '{"mode":"RTL"}', is_error: false } },
      { type: "event", event: { type: "text_delta", text: "It is in RTL." } },
    ]);
    const a = s.turns[1];
    if (a.role !== "assistant") throw new Error();
    expect(a.parts.map((p) => p.kind)).toEqual(["text", "tool", "text"]);
    expect(a.parts[1]).toMatchObject({ kind: "tool", id: "t1", output: '{"mode":"RTL"}', is_error: false });
    expect(s.streaming).toBe(true);
  });

  it("orphan tool results are still shown", () => {
    const parts = applyChatEvent([], { type: "tool_result", id: "x", name: "n", output: "boom", is_error: true });
    expect(parts).toEqual([{ kind: "tool", id: "x", name: "n", input: null, output: "boom", is_error: true }]);
  });

  it("adds proposal parts once and records errors", () => {
    const p = proposal();
    let parts = applyChatEvent([], { type: "proposal", proposal: p });
    parts = applyChatEvent(parts, { type: "proposal", proposal: p });
    parts = applyChatEvent(parts, { type: "error", message: "rate limited" });
    expect(parts).toEqual([
      { kind: "proposal", id: "p1" },
      { kind: "error", message: "rate limited" },
    ]);
  });

  it("finish marks an unfinished turn (stop) but keeps an existing stop_reason", () => {
    let s = run(initialChat("s"), [{ type: "send", text: "x" }, { type: "finish", reason: "stopped" }]);
    let a = s.turns[1];
    if (a.role !== "assistant") throw new Error();
    expect(a.end).toBe("stopped");
    expect(s.streaming).toBe(false);
    s = run(initialChat("s"), [
      { type: "send", text: "x" },
      { type: "event", event: { type: "done", stop_reason: "end_turn" } },
      { type: "finish", reason: "incomplete" },
    ]);
    a = s.turns[1];
    if (a.role !== "assistant") throw new Error();
    expect(a.end).toBe("end_turn");
  });

  it("ignores events after the turn has ended", () => {
    const s = run(initialChat("s"), [
      { type: "send", text: "x" },
      { type: "finish", reason: "stopped" },
      { type: "event", event: { type: "text_delta", text: "late" } },
    ]);
    const a = s.turns[1];
    if (a.role !== "assistant") throw new Error();
    expect(a.parts).toEqual([]);
  });

  it("reset starts a new session", () => {
    const s = run(initialChat("a"), [{ type: "send", text: "x" }, { type: "reset", sessionId: "b" }]);
    expect(s).toEqual(initialChat("b"));
  });

  it("newSessionId returns unique ids", () => {
    const a = newSessionId();
    expect(a).toMatch(/[0-9a-f-]{8,}/i);
    expect(newSessionId()).not.toBe(a);
  });
});
