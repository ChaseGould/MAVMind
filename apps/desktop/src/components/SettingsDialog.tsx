import { useState } from "react";
import { defaultUrls, type ServiceUrls } from "../lib/settings";
import { isHttpUrl } from "../lib/url";
import { Modal } from "./Modal";

export function SettingsDialog({
  urls,
  onSave,
  onClose,
}: {
  urls: ServiceUrls;
  onSave: (u: ServiceUrls) => void;
  onClose: () => void;
}) {
  const [vehicle, setVehicle] = useState(urls.vehicle);
  const [agent, setAgent] = useState(urls.agent);
  const vOk = isHttpUrl(vehicle);
  const aOk = isHttpUrl(agent);
  const defaults = defaultUrls();
  return (
    <Modal
      title="Service settings"
      onClose={onClose}
      footer={
        <>
          <button
            className="btn"
            onClick={() => {
              setVehicle(defaults.vehicle);
              setAgent(defaults.agent);
            }}
          >
            Reset to defaults
          </button>
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={!vOk || !aOk}
            onClick={() => {
              onSave({ vehicle, agent });
              onClose();
            }}
          >
            Save
          </button>
        </>
      }
    >
      <label className="field">
        <span>Vehicle service URL</span>
        <input value={vehicle} onChange={(e) => setVehicle(e.target.value)} spellCheck={false} />
        {!vOk && <small className="bad">Enter an http(s):// URL</small>}
      </label>
      <label className="field">
        <span>Agent service URL</span>
        <input value={agent} onChange={(e) => setAgent(e.target.value)} spellCheck={false} />
        {!aOk && <small className="bad">Enter an http(s):// URL</small>}
      </label>
      <p className="muted small">
        Defaults: {defaults.vehicle} and {defaults.agent} (from VITE_VEHICLE_URL / VITE_AGENT_URL at build time).
        Saved in this machine's local storage.
      </p>
    </Modal>
  );
}
