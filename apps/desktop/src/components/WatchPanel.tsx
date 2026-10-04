import { fmtField } from "../lib/format";
import { splitPin } from "../lib/vehicle";
import { useApp, useVehicle } from "../state/AppContext";
import { Sparkline } from "./Sparkline";

export function WatchPanel() {
  const { store } = useApp();
  const pins = useVehicle((s) => s.pins);
  const history = useVehicle((s) => s.history);
  return (
    <section className="panel watch">
      <div className="panel-head">
        <span>Watch</span>
        <span className="muted small">{pins.length ? `${pins.length} pinned` : ""}</span>
      </div>
      {pins.length === 0 ? (
        <div className="empty">Pin numeric fields from the Inspector to watch them here.</div>
      ) : (
        <div className="watch-list">
          {pins.map((key) => {
            const vals = history[key] ?? [];
            const cur = vals.length ? vals[vals.length - 1] : null;
            const { message, field } = splitPin(key);
            let min = Infinity;
            let max = -Infinity;
            for (const v of vals) {
              if (v < min) min = v;
              if (v > max) max = v;
            }
            return (
              <div className="watch-row" key={key}>
                <div className="watch-label" title={key}>
                  <span className="muted">{message}.</span>
                  {field}
                </div>
                <div className="watch-value">{fmtField(cur)}</div>
                <Sparkline values={vals} width={150} height={28} />
                <div className="watch-range muted small" title="min / max of recent samples">
                  {vals.length ? `${fmtField(min)} … ${fmtField(max)}` : "waiting…"}
                </div>
                <button className="btn btn-tiny" title="Unpin" onClick={() => store.dispatch({ type: "unpin", key })}>
                  ×
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
