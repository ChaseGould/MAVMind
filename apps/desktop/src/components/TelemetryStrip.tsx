import { fmtAge, fmtDistance, fmtDuration, fmtInt, fmtNum, isNum } from "../lib/format";
import { useVehicle } from "../state/AppContext";

type Tone = "" | "good" | "warn" | "bad";

function Cell({ label, value, tone = "", title }: { label: string; value: string; tone?: Tone; title?: string }) {
  return (
    <div className={`tcell ${tone ? `t-${tone}` : ""}`} title={title}>
      <span className="tlabel">{label}</span>
      <span className="tvalue">{value}</span>
    </div>
  );
}

export function TelemetryStrip() {
  const f = useVehicle((s) => s.state);
  const pct = f?.battery_remaining_pct ?? null;
  const battTone: Tone = !isNum(pct) ? "" : pct < 20 ? "bad" : pct < 35 ? "warn" : "good";
  const fix = f?.gps_fix_type ?? null;
  const gpsTone: Tone = !isNum(fix) ? "" : fix >= 3 ? "good" : fix === 2 ? "warn" : "bad";
  const hb = f?.link.last_heartbeat_age_s ?? null;
  const hbTone: Tone = !isNum(hb) ? "" : hb > 3 ? "bad" : hb > 1.5 ? "warn" : "good";
  const loss = f?.link.packet_loss_pct ?? null;
  const lossTone: Tone = !isNum(loss) ? "" : loss > 10 ? "bad" : loss > 2 ? "warn" : "good";
  const armed = f?.armed ?? null;
  return (
    <footer className="telemetry">
      <div className="tgroup">
        <span className="tgroup-name">Battery</span>
        <Cell label="V" value={fmtNum(f?.battery_voltage_v ?? null, 2)} tone={battTone} />
        <Cell label="A" value={fmtNum(f?.battery_current_a ?? null, 1)} />
        <Cell label="%" value={fmtInt(pct)} tone={battTone} />
      </div>
      <div className="tgroup">
        <span className="tgroup-name">GPS</span>
        <Cell label="fix" value={f?.gps_fix_name ?? "--"} tone={gpsTone} title={isNum(fix) ? `fix type ${fix}` : undefined} />
        <Cell label="sats" value={fmtInt(f?.gps_sats ?? null)} />
        <Cell label="hdop" value={fmtNum(f?.hdop ?? null, 2)} />
      </div>
      <div className="tgroup">
        <span className="tgroup-name">Link</span>
        <Cell label="hb" value={fmtAge(hb)} tone={hbTone} title="Time since last heartbeat" />
        <Cell
          label="rssi"
          value={`${fmtInt(f?.link.rssi ?? null)}/${fmtInt(f?.link.remrssi ?? null)}`}
          title="Local / remote RSSI"
        />
        <Cell label="loss" value={fmtNum(loss, 1, "%")} tone={lossTone} />
        {isNum(f?.link.quality_pct) && <Cell label="qual" value={fmtInt(f?.link.quality_pct ?? null, "%")} />}
      </div>
      <div className="tgroup">
        <span className="tgroup-name">Vehicle</span>
        <Cell label="mode" value={f?.mode ?? "--"} />
        <Cell
          label="armed"
          value={armed === null ? "--" : armed ? "ARMED" : "DISARMED"}
          tone={armed === null ? "" : armed ? "bad" : "good"}
        />
        <Cell label="EKF" value={f?.ekf_ok == null ? "--" : f.ekf_ok ? "ok" : "BAD"} tone={f?.ekf_ok === false ? "bad" : ""} />
        <Cell label="type" value={f?.vehicle_type ?? "--"} />
      </div>
      <div className="tgroup">
        <span className="tgroup-name">Flight</span>
        <Cell label="home" value={fmtDistance(f?.distance_home_m ?? null)} />
        <Cell label="time" value={fmtDuration(f?.flight_time_s ?? null)} />
        <Cell label="alt" value={fmtNum(f?.alt_rel_m ?? null, 1, "m")} title="Altitude relative to home" />
        <Cell label="wp" value={fmtInt(f?.mission_current_seq ?? null)} />
      </div>
      <div className="tgroup tgroup-src">
        <span className="tgroup-name">Source</span>
        <Cell label="" value={f ? `${f.profile ?? "--"} · ${f.source ?? "--"}` : "--"} />
      </div>
    </footer>
  );
}
