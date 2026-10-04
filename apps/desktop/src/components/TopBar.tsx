import { useEffect, useState } from "react";
import { errText, useApp, useVehicle } from "../state/AppContext";
import { useHealth } from "../state/health";
import { useConfirm } from "./Modal";
import { SettingsDialog } from "./SettingsDialog";

function StatusPill({ label, online, title }: { label: string; online: boolean | null; title: string }) {
  const cls = online === null ? "pill pill-unknown" : online ? "pill pill-ok" : "pill pill-bad";
  return (
    <span className={cls} title={title}>
      <span className="dot" />
      {label}
    </span>
  );
}

export function TopBar() {
  const { urls, setUrls, vehicle, agent, store, notify } = useApp();
  const vHealth = useHealth(vehicle.health);
  const aHealth = useHealth(agent.health);
  const ws = useVehicle((s) => s.ws);
  const profiles = useVehicle((s) => s.profiles);
  const modes = useVehicle((s) => s.modes);
  const connected = useVehicle((s) => s.state?.connected ?? false);
  const mode = useVehicle((s) => s.state?.mode ?? null);
  const armed = useVehicle((s) => s.state?.armed ?? null);
  const commandEnabled = useVehicle((s) => s.commandEnabled);
  const [dialog, confirm] = useConfirm();
  const [showSettings, setShowSettings] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [profile, setProfile] = useState("");
  const [modeSel, setModeSel] = useState("");

  const vOnline = vHealth.online === true;
  const linkUp = vOnline && (connected || vHealth.data?.connected === true);

  // Default the pickers to the active profile / current mode.
  useEffect(() => {
    if (!profile && profiles) setProfile(profiles.active ?? profiles.profiles[0]?.name ?? "");
  }, [profiles, profile]);
  useEffect(() => {
    if (mode) setModeSel((cur) => (cur === "" ? mode : cur));
  }, [mode]);

  const run = async <T,>(key: string, fn: () => Promise<T>, okText?: (r: T) => string | null) => {
    setBusy(key);
    try {
      const r = await fn();
      const ok = (r as { ok?: boolean })?.ok;
      const msg = (r as { message?: string })?.message;
      if (ok === false) notify("error", msg || `${key} failed`);
      else {
        const t = okText ? okText(r) : msg ?? null;
        if (t) notify("ok", t);
      }
      return r;
    } catch (e) {
      notify("error", `${key}: ${errText(e)}`);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const onConnect = () =>
    run("Connect", () => vehicle.connect(profile), (r) => r.message || `Connected (${r.profile})`).then(() =>
      vehicle.profiles().then((p) => store.dispatch({ type: "profiles", profiles: p }), () => undefined),
    );
  const onDisconnect = () => run("Disconnect", () => vehicle.disconnect(), () => "Disconnected");

  const onArm = async () => {
    const toArm = armed !== true;
    const r = await confirm({
      title: toArm ? "Arm vehicle?" : "Disarm vehicle?",
      body: toArm ? (
        <p>
          Arming enables the motors. Make sure the area around the vehicle is clear and you are ready to fly.
        </p>
      ) : (
        <p>Disarming in flight will cut the motors and the vehicle will fall. Only disarm on the ground.</p>
      ),
      confirmLabel: toArm ? "Arm" : "Disarm",
      tone: "danger",
    });
    if (r.confirmed) await run(toArm ? "Arm" : "Disarm", () => vehicle.arm(toArm));
  };

  const setMode = (m: string) => run(`Mode ${m}`, () => vehicle.setMode(m), (r) => r.message || `Mode ${m} requested`);

  const onCommandToggle = async () => {
    const enable = commandEnabled !== true;
    if (enable) {
      const r = await confirm({
        title: "Enable command mode?",
        body: (
          <>
            <p>
              The LLM will be allowed to <b>propose missions</b>. Nothing is uploaded until you approve a proposal
              here, and the LLM can never arm, change mode or upload by itself.
            </p>
          </>
        ),
        confirmLabel: "Enable commands",
        tone: "warn",
      });
      if (!r.confirmed) return;
    }
    const res = await run(enable ? "Enable commands" : "Disable commands", () => vehicle.setCommand(enable), () => null);
    if (res) store.dispatch({ type: "command", enabled: res.enabled });
  };

  const modeOptions = mode && !modes.includes(mode) ? [mode, ...modes] : modes;
  const agentTitle = aHealth.data
    ? `Agent: ${urls.agent}\nmodel: ${aHealth.data.model ?? "--"}\nAPI key: ${aHealth.data.api_key ? "yes" : "MISSING"}\nread-only MCP: ${aHealth.data.readonly_mcp ? "ok" : "unavailable"}`
    : `Agent: ${urls.agent}\n${aHealth.error ?? "checking..."}`;
  const vehicleTitle = vHealth.data
    ? `Vehicle service: ${urls.vehicle}\nprofile: ${vHealth.data.profile ?? "--"}\nlink: ${vHealth.data.connected ? "connected" : "not connected"}\nsource: ${vHealth.data.source ?? "--"}`
    : `Vehicle service: ${urls.vehicle}\n${vHealth.error ?? "checking..."}`;

  return (
    <header className="topbar">
      <div className="brand" title="MAVMind ground station">
        <span className="brand-mark" />
        MAVMind
      </div>

      <div className="group">
        <StatusPill label="Vehicle svc" online={vHealth.online} title={vehicleTitle} />
        <StatusPill label="Agent svc" online={aHealth.online} title={agentTitle} />
        <StatusPill
          label={linkUp ? "Link" : "No link"}
          online={vOnline ? linkUp && ws === "open" : vHealth.online === null ? null : false}
          title={`WebSocket: ${ws}\nVehicle link: ${linkUp ? "connected" : "not connected"}`}
        />
        {aHealth.data && !aHealth.data.api_key && (
          <span className="pill pill-warn" title="The agent service has no LLM API key configured">
            No API key
          </span>
        )}
      </div>

      <div className="group">
        <select
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          disabled={!vOnline || !profiles}
          title={profiles?.profiles.find((p) => p.name === profile)?.description ?? "Connection profile"}
        >
          {!profiles && <option value="">profiles…</option>}
          {/* A service started with --profile <path> has an active profile outside config/profiles. */}
          {profiles?.active && !profiles.profiles.some((p) => p.name === profiles.active) && (
            <option value={profiles.active}>{profiles.active} (active)</option>
          )}
          {profiles?.profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
              {profiles.active === p.name ? " (active)" : ""}
            </option>
          ))}
        </select>
        {linkUp ? (
          <button className="btn" onClick={onDisconnect} disabled={!vOnline || busy !== null}>
            Disconnect
          </button>
        ) : (
          <button className="btn btn-primary" onClick={onConnect} disabled={!vOnline || !profile || busy !== null}>
            {busy === "Connect" ? "Connecting…" : "Connect"}
          </button>
        )}
      </div>

      <div className="group">
        <button
          className={`btn ${armed ? "btn-danger" : "btn-arm"}`}
          onClick={onArm}
          disabled={!linkUp || busy !== null}
          title={armed === null ? "Armed state unknown" : armed ? "Vehicle is ARMED" : "Vehicle is disarmed"}
        >
          {armed ? "Disarm" : "Arm"}
        </button>
        <select value={modeSel} onChange={(e) => setModeSel(e.target.value)} disabled={!linkUp || modeOptions.length === 0}>
          {modeOptions.length === 0 && <option value="">modes…</option>}
          {modeOptions.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <button className="btn" onClick={() => setMode(modeSel)} disabled={!linkUp || !modeSel || busy !== null}>
          Set
        </button>
        <button className="btn btn-quick" onClick={() => setMode("RTL")} disabled={!linkUp || busy !== null} title="Return to launch">
          RTL
        </button>
        <button className="btn btn-quick" onClick={() => setMode("LOITER")} disabled={!linkUp || busy !== null} title="Hold position">
          Loiter
        </button>
      </div>

      <span className="spacer" />

      <div className="group">
        <label
          className={`switch ${commandEnabled ? "switch-on" : ""}`}
          title="Allow the LLM to propose missions (uploads still need your approval)"
        >
          <input
            type="checkbox"
            checked={commandEnabled === true}
            disabled={!vOnline || busy !== null}
            onChange={onCommandToggle}
          />
          <span className="switch-track">
            <span className="switch-thumb" />
          </span>
          Commands
        </label>
        <button className="btn btn-icon" onClick={() => setShowSettings(true)} title="Service settings" aria-label="Settings">
          ⚙
        </button>
      </div>

      {dialog}
      {showSettings && <SettingsDialog urls={urls} onSave={setUrls} onClose={() => setShowSettings(false)} />}
    </header>
  );
}

export function CommandBanner() {
  const enabled = useVehicle((s) => s.commandEnabled);
  if (enabled !== true) return null;
  return (
    <div className="command-banner" role="alert">
      <span className="command-badge">COMMAND MODE ON</span> — LLM may propose missions. Nothing uploads without your
      approval.
    </div>
  );
}
