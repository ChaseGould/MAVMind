import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { initialChat, newSessionId, reduceChat, type Turn } from "../lib/chat";
import { errText, useApp, useVehicle } from "../state/AppContext";
import { Markdown } from "./Markdown";
import { ProposalCard } from "./ProposalCard";
import { ToolCallBlock } from "./ToolCallBlock";

const SUGGESTIONS = [
  "What is the vehicle doing right now?",
  "Is anything wrong with the GPS or battery?",
  "Which MAVLink messages are arriving, and at what rates?",
  "Summarise the recent events and status texts.",
];
const COMMAND_SUGGESTION = "Propose a short survey mission around home at 30 m.";

const END_NOTES: Record<string, string> = {
  stopped: "Stopped.",
  max_tokens: "Response cut off (max tokens).",
  incomplete: "Stream ended without a final message.",
};

export function Chat() {
  const { agent, store } = useApp();
  const commandEnabled = useVehicle((s) => s.commandEnabled === true);
  const [chat, dispatch] = useReducer(reduceChat, undefined, () => initialChat(newSessionId()));
  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [chat.turns]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || chat.streaming) return;
      setInput("");
      stick.current = true;
      dispatch({ type: "send", text });
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const stream = agent.chat(
          { session_id: chat.sessionId, message: text, commands_enabled: commandEnabled },
          ctrl.signal,
        );
        for await (const ev of stream) {
          if (ev.type === "proposal") {
            // Keep the shared proposals store (map + cards) in sync. WS frames
            // from the vehicle service are authoritative for later updates.
            store.dispatch({ type: "proposal", proposal: ev.proposal, ifAbsent: true });
          }
          dispatch({ type: "event", event: ev });
        }
        dispatch({ type: "finish", reason: "incomplete" });
      } catch (e) {
        if (ctrl.signal.aborted) dispatch({ type: "finish", reason: "stopped" });
        else {
          dispatch({ type: "event", event: { type: "error", message: `Agent service: ${errText(e)}` } });
          dispatch({ type: "finish", reason: "error" });
        }
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
      }
    },
    [agent, chat.sessionId, chat.streaming, commandEnabled, store],
  );

  const stop = () => abortRef.current?.abort();

  const newChat = () => {
    abortRef.current?.abort();
    const old = chat.sessionId;
    agent.reset(old).catch(() => undefined);
    dispatch({ type: "reset", sessionId: newSessionId() });
  };

  return (
    <div className="chat">
      <div className="chat-bar">
        <span className="muted small" title={`session ${chat.sessionId}`}>
          Session {chat.sessionId.slice(0, 8)}
        </span>
        {commandEnabled ? (
          <span className="badge badge-warn" title="The LLM may propose missions">
            commands on
          </span>
        ) : (
          <span className="badge" title="Read-only: the LLM can only inspect">
            read-only
          </span>
        )}
        <span className="spacer" />
        <button className="btn btn-small" onClick={newChat} disabled={chat.turns.length === 0 && !chat.streaming}>
          New chat
        </button>
      </div>

      <div
        className="chat-list"
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {chat.turns.length === 0 && (
          <div className="chat-empty">
            <p>Ask about the vehicle state, the mission, or the MAVLink traffic.</p>
            <div className="suggestions">
              {(commandEnabled ? [...SUGGESTIONS, COMMAND_SUGGESTION] : SUGGESTIONS).map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {chat.turns.map((t) => (
          <TurnView key={t.id} turn={t} streaming={chat.streaming && t === chat.turns[chat.turns.length - 1]} />
        ))}
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={chat.streaming ? "Waiting for the reply…" : "Ask MAVMind…  (Enter to send, Shift+Enter for newline)"}
          rows={2}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        {chat.streaming ? (
          <button type="button" className="btn btn-warn" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={!input.trim()}>
            Send
          </button>
        )}
      </form>
    </div>
  );
}

function TurnView({ turn, streaming }: { turn: Turn; streaming: boolean }) {
  if (turn.role === "user") {
    return (
      <div className="turn turn-user">
        <div className="bubble">{turn.text}</div>
      </div>
    );
  }
  const note = turn.end ? END_NOTES[turn.end] : undefined;
  return (
    <div className="turn turn-assistant">
      {turn.parts.length === 0 && streaming && <div className="thinking">thinking…</div>}
      {turn.parts.map((p, i) => {
        switch (p.kind) {
          case "text":
            return <Markdown key={i} text={p.text} />;
          case "tool":
            return <ToolCallBlock key={i} part={p} />;
          case "proposal":
            return <ProposalCard key={i} id={p.id} />;
          case "error":
            return (
              <div key={i} className="chat-error">
                {p.message}
              </div>
            );
          default:
            return null;
        }
      })}
      {streaming && turn.parts.length > 0 && <span className="cursor" />}
      {note && <div className="muted small">{note}</div>}
    </div>
  );
}
