import { useEffect, useRef } from "react";
import { fmtClock } from "../lib/format";
import type { VehicleEvent } from "../types";
import { useVehicle } from "../state/AppContext";

export function severityClass(e: VehicleEvent): string {
  const s = (e.severity ?? "").toUpperCase();
  if (["EMERGENCY", "ALERT", "CRITICAL", "ERROR"].includes(s) || e.kind === "failsafe") return "sev-bad";
  if (s === "WARNING") return "sev-warn";
  if (s === "DEBUG") return "sev-debug";
  if (e.kind === "armed") return "sev-armed";
  if (e.kind === "mode_change" || e.kind === "disarmed") return "sev-info";
  return "";
}

const KIND_LABEL: Record<string, string> = {
  mode_change: "MODE",
  armed: "ARM",
  disarmed: "DISARM",
  statustext: "TEXT",
  failsafe: "FS",
  mission_progress: "MSN",
  link: "LINK",
};

export function EventLog() {
  const events = useVehicle((s) => s.events);
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [events]);

  return (
    <section className="panel events">
      <div className="panel-head">
        <span>Events</span>
        <span className="muted small">{events.length}</span>
      </div>
      <div
        className="events-list"
        ref={ref}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
      >
        {events.length === 0 && <div className="empty">No events yet</div>}
        {events.map((e, i) => (
          <div key={`${e.timestamp}-${i}`} className={`event ${severityClass(e)}`} title={e.data ? JSON.stringify(e.data) : undefined}>
            <span className="ev-time">{fmtClock(e.timestamp)}</span>
            <span className="ev-kind">{e.severity ? e.severity.slice(0, 4) : (KIND_LABEL[e.kind] ?? e.kind)}</span>
            <span className="ev-msg">{e.message}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
