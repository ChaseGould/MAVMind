import { useMemo, useState } from "react";
import { fmtAge, fmtField } from "../lib/format";
import { pinKey } from "../lib/vehicle";
import type { MessageDetail, MessageSummary } from "../types";
import { useApp, useVehicle } from "../state/AppContext";

export function Inspector() {
  const { store } = useApp();
  const liveMessages = useVehicle((s) => s.messages);
  const liveDetails = useVehicle((s) => s.details);
  const expanded = useVehicle((s) => s.expanded);
  const pins = useVehicle((s) => s.pins);
  const [filter, setFilter] = useState("");
  // Pause freezes what is displayed; the store keeps updating underneath.
  const [frozen, setFrozen] = useState<{ messages: MessageSummary[]; details: Record<string, MessageDetail> } | null>(
    null,
  );
  const paused = frozen !== null;
  const messages = frozen?.messages ?? liveMessages;
  const details = frozen?.details ?? liveDetails;

  const rows = useMemo(() => {
    const q = filter.trim().toUpperCase();
    return messages
      .filter((m) => !q || m.name.toUpperCase().includes(q))
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [messages, filter]);

  const totalHz = useMemo(() => messages.reduce((acc, m) => acc + (m.rate_hz || 0), 0), [messages]);

  return (
    <div className="inspector">
      <div className="inspector-bar">
        <input
          className="filter"
          placeholder="Filter message types…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          spellCheck={false}
        />
        <button className={`btn btn-small ${paused ? "btn-warn" : ""}`} onClick={() => setFrozen(paused ? null : { messages: liveMessages, details: liveDetails })}>
          {paused ? "Paused" : "Pause"}
        </button>
      </div>
      <div className="inspector-meta muted small">
        {messages.length} types · {totalHz.toFixed(1)} msg/s{paused ? " · display frozen" : ""}
      </div>
      <div className="inspector-table">
        <div className="irow ihead">
          <span>Message</span>
          <span className="num">Hz</span>
          <span className="num">Age</span>
          <span className="num">Count</span>
        </div>
        {rows.length === 0 && <div className="empty">{messages.length ? "No match" : "No messages yet"}</div>}
        {rows.map((m) => {
          const open = expanded.includes(m.name);
          const d = details[m.name];
          return (
            <div key={m.name} className={`imsg ${open ? "open" : ""}`}>
              <button
                className={`irow ${m.age_s > 5 ? "stale" : ""}`}
                onClick={() => store.dispatch({ type: "expand", name: m.name, expanded: !open })}
                aria-expanded={open}
              >
                <span className="iname">
                  <span className="caret">{open ? "▾" : "▸"}</span>
                  {m.name}
                </span>
                <span className="num">{m.rate_hz.toFixed(1)}</span>
                <span className="num">{fmtAge(m.age_s)}</span>
                <span className="num">{m.count}</span>
              </button>
              {open && (
                <div className="ifields">
                  {!d ? (
                    <div className="empty small">waiting for {m.name}…</div>
                  ) : (
                    <>
                      <div className="muted small ifields-meta">
                        sys {d.sysid} · comp {d.compid} · {d.rate_hz.toFixed(1)} Hz · age {fmtAge(d.age_s)}
                      </div>
                      {Object.entries(d.fields).map(([k, v]) => {
                        const key = pinKey(m.name, k);
                        const pinned = pins.includes(key);
                        const numeric = typeof v === "number" && Number.isFinite(v);
                        return (
                          <div className="ifield" key={k}>
                            <span className="ifield-name">{k}</span>
                            <span className="ifield-val">{fmtField(v)}</span>
                            {numeric || pinned ? (
                              <button
                                className={`btn btn-tiny ${pinned ? "btn-active" : ""}`}
                                title={pinned ? "Unpin from watch panel" : "Pin to watch panel"}
                                onClick={() => store.dispatch({ type: pinned ? "unpin" : "pin", key })}
                              >
                                {pinned ? "pinned" : "pin"}
                              </button>
                            ) : (
                              <span />
                            )}
                          </div>
                        );
                      })}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
