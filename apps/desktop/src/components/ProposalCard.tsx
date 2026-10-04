import { useState } from "react";
import { fmtClock, fmtDistance, fmtDuration, fmtInt } from "../lib/format";
import { missionPath } from "../lib/mapgeo";
import type { Proposal } from "../types";
import { errText, useApp, useVehicle } from "../state/AppContext";
import { mapFocus } from "../state/mapFocus";
import { useConfirm } from "./Modal";

const STATUS_LABEL: Record<Proposal["status"], string> = {
  invalid: "INVALID",
  pending: "PENDING APPROVAL",
  uploading: "UPLOADING…",
  uploaded: "UPLOADED",
  upload_failed: "UPLOAD FAILED",
  rejected: "REJECTED",
};

export function ProposalCard({ id }: { id: string }) {
  const p = useVehicle((s) => s.proposals[id]);
  if (!p) return <div className="proposal proposal-missing">Proposal {id} (not found on vehicle service)</div>;
  return <ProposalCardBody p={p} />;
}

function ProposalCardBody({ p }: { p: Proposal }) {
  const { vehicle, store, notify } = useApp();
  const [dialog, confirm] = useConfirm();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showChecks, setShowChecks] = useState(p.status === "pending" || p.status === "invalid");
  const est = p.validation.estimates;
  const failed = p.validation.checks.filter((c) => !c.ok).length;
  const canApprove = p.status === "pending" && busy === null;
  const canReject = (p.status === "pending" || p.status === "invalid") && busy === null;

  const approve = async () => {
    const r = await confirm({
      title: "Approve and upload mission?",
      tone: "danger",
      confirmLabel: "Approve & upload",
      body: (
        <>
          <p>
            Upload <b>{p.mission.name}</b> ({p.mission.items.length} items) to the vehicle, replacing its current
            mission. The upload is read back and verified.
          </p>
          <p className="muted small">
            This does not arm the vehicle or change its mode. Start the mission yourself when ready.
          </p>
        </>
      ),
    });
    if (!r.confirmed) return;
    setBusy("approve");
    setError(null);
    try {
      // Straight to the vehicle service: the agent never sees approvals.
      const res = await vehicle.approve(p.id);
      store.dispatch({ type: "proposal", proposal: res });
      if (res.upload?.ok) notify("ok", `Mission "${res.mission.name}" uploaded${res.upload.verified ? " and verified" : ""}`);
      else notify("error", `Upload failed: ${res.upload?.message ?? res.status}`);
    } catch (e) {
      setError(errText(e));
      vehicle.proposal(p.id).then((x) => store.dispatch({ type: "proposal", proposal: x }), () => undefined);
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    const r = await confirm({
      title: "Reject proposal?",
      confirmLabel: "Reject",
      body: <p>Reject “{p.mission.name}”. It will not be uploaded.</p>,
      input: { label: "Reason (optional)", placeholder: "e.g. too close to the tree line" },
    });
    if (!r.confirmed) return;
    setBusy("reject");
    setError(null);
    try {
      const res = await vehicle.reject(p.id, r.value || undefined);
      store.dispatch({ type: "proposal", proposal: res });
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  };

  const showOnMap = () => {
    const home = store.getState().state?.home ?? null;
    const pts = missionPath(p.items, home);
    if (pts.length) mapFocus.emit({ points: pts });
  };

  return (
    <div className={`proposal proposal-${p.status}`}>
      <div className="proposal-head">
        <div className="proposal-title">
          <span className="proposal-kicker">Mission proposal</span>
          <span className="proposal-name">{p.mission.name}</span>
        </div>
        <span className={`status status-${p.status}`}>{STATUS_LABEL[p.status] ?? p.status}</span>
      </div>
      {p.mission.description && <div className="proposal-desc">{p.mission.description}</div>}
      <div className="proposal-stats">
        <div>
          <span className="tlabel">items</span>
          <span>{p.mission.items.length}</span>
        </div>
        <div>
          <span className="tlabel">distance</span>
          <span>{fmtDistance(est.total_distance_m)}</span>
        </div>
        <div>
          <span className="tlabel">time</span>
          <span>{fmtDuration(est.flight_time_s)}</span>
        </div>
        <div>
          <span className="tlabel">battery</span>
          <span>
            {fmtInt(est.battery_required_pct)}% / {fmtInt(est.battery_available_pct)}%
          </span>
        </div>
      </div>
      <button className="checks-toggle" onClick={() => setShowChecks((s) => !s)} aria-expanded={showChecks}>
        <span className="caret">{showChecks ? "▾" : "▸"}</span>
        Validation: {p.validation.ok ? <span className="good">passed</span> : <span className="bad">failed</span>} (
        {p.validation.checks.length - failed}/{p.validation.checks.length} checks)
      </button>
      {showChecks && (
        <ul className="checks">
          {p.validation.checks.map((c, i) => (
            <li key={i} className={c.ok ? "check-ok" : "check-fail"}>
              <span className="check-mark">{c.ok ? "PASS" : "FAIL"}</span>
              <span className="check-name">{c.name}</span>
              <span className="check-msg">{c.message}</span>
            </li>
          ))}
        </ul>
      )}
      {p.upload && (
        <div className={`upload ${p.upload.ok ? "upload-ok" : "upload-fail"}`}>
          <div>
            Upload: <b>{p.upload.ok ? "ok" : "failed"}</b> · readback{" "}
            <b>{p.upload.verified ? "verified" : "NOT verified"}</b>
          </div>
          {p.upload.message && <div className="small">{p.upload.message}</div>}
          {p.upload.diff.length > 0 && <pre className="diff">{p.upload.diff.join("\n")}</pre>}
        </div>
      )}
      {p.reject_reason && <div className="muted small">Rejected: {p.reject_reason}</div>}
      {error && <div className="bad small">Error: {error}</div>}
      <div className="proposal-actions">
        <span className="muted small">
          {fmtClock(p.created_at)} · {p.id.slice(0, 8)}
        </span>
        <span className="spacer" />
        <button className="btn btn-small" onClick={showOnMap}>
          Show on map
        </button>
        <button className="btn btn-small" onClick={reject} disabled={!canReject}>
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
        <button
          className="btn btn-small btn-approve"
          onClick={approve}
          disabled={!canApprove}
          title={p.status === "pending" ? "Upload this mission to the vehicle" : `Cannot approve: status is ${p.status}`}
        >
          {busy === "approve" ? "Uploading…" : "Approve"}
        </button>
      </div>
      {dialog}
    </div>
  );
}
