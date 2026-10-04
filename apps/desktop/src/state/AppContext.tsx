import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { agentApi, vehicleApi, type AgentApi, type VehicleApi } from "../lib/api";
import { loadPins, loadUrls, savePins, saveUrls, type ServiceUrls } from "../lib/settings";
import { Store, useStore } from "../lib/store";
import { toWsUrl } from "../lib/url";
import {
  initialVehicleData,
  reduceVehicle,
  subscriptionNames,
  type VehicleAction,
  type VehicleData,
} from "../lib/vehicle";
import { VehicleSocket } from "../lib/ws";

export type VehicleStore = Store<VehicleData, VehicleAction>;

export type Toast = { id: number; kind: "ok" | "error" | "info"; text: string };

type AppCtx = {
  urls: ServiceUrls;
  setUrls: (u: ServiceUrls) => void;
  store: VehicleStore;
  vehicle: VehicleApi;
  agent: AgentApi;
  notify: (kind: Toast["kind"], text: string) => void;
  toasts: Toast[];
  dismissToast: (id: number) => void;
  /** Re-fetch REST snapshots (mission, proposals, modes, ...). */
  refresh: () => void;
};

const Ctx = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}

/** Select a slice of vehicle data. */
export function useVehicle<T>(selector: (s: VehicleData) => T): T {
  return useStore(useApp().store, selector);
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [urls, setUrlsState] = useState<ServiceUrls>(loadUrls);
  const store = useMemo<VehicleStore>(() => new Store(reduceVehicle, initialVehicleData(loadPins())), []);
  const vehicle = useMemo(() => vehicleApi(urls.vehicle), [urls.vehicle]);
  const agent = useMemo(() => agentApi(urls.agent), [urls.agent]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(1);

  const setUrls = useCallback((u: ServiceUrls) => {
    saveUrls(u);
    setUrlsState(loadUrls());
  }, []);

  const dismissToast = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const notify = useCallback(
    (kind: Toast["kind"], text: string) => {
      const id = toastId.current++;
      setToasts((t) => [...t.slice(-4), { id, kind, text }]);
      setTimeout(() => dismissToast(id), kind === "error" ? 9000 : 5000);
    },
    [dismissToast],
  );

  // Persist pins whenever they change.
  useEffect(() => {
    let last = store.getState().pins;
    return store.subscribe(() => {
      const pins = store.getState().pins;
      if (pins !== last) {
        last = pins;
        savePins(pins);
      }
    });
  }, [store]);

  // REST snapshots. Each request is independent so one failure does not block the rest.
  const refreshVehicleType = useCallback(() => {
    vehicle.modes().then((r) => store.dispatch({ type: "modes", modes: r.modes }), () => undefined);
    vehicle.geofence().then((g) => store.dispatch({ type: "geofence", geofence: g }), () => undefined);
    vehicle.mission().then((m) => store.dispatch({ type: "mission", mission: m }), () => undefined);
  }, [vehicle, store]);

  const refresh = useCallback(() => {
    vehicle.profiles().then((p) => store.dispatch({ type: "profiles", profiles: p }), () => undefined);
    vehicle.getCommand().then((c) => store.dispatch({ type: "command", enabled: c.enabled }), () => undefined);
    vehicle.proposals().then((r) => store.dispatch({ type: "proposals", proposals: r.proposals }), () => undefined);
    // since=0: the service bounds its own history; source clocks (replays) may
    // be far from the local clock, so a wall-clock cutoff could hide everything.
    vehicle.events(0).then((r) => store.dispatch({ type: "events", events: r.events }), () => undefined);
    refreshVehicleType();
  }, [vehicle, store, refreshVehicleType]);

  // One WebSocket to {vehicle}/ws, recreated when the URL changes.
  const socketRef = useRef<VehicleSocket | null>(null);
  useEffect(() => {
    const sock = new VehicleSocket(toWsUrl(urls.vehicle, "/ws"), {
      onFrame: (frame) => store.dispatch({ type: "frame", frame }),
      onStatus: (status) => store.dispatch({ type: "ws", status }),
      onOpen: refresh,
    });
    socketRef.current = sock;
    const s = store.getState();
    sock.setSubscription(subscriptionNames(s.expanded, s.pins));
    sock.start();
    return () => {
      sock.stop();
      if (socketRef.current === sock) socketRef.current = null;
    };
  }, [urls.vehicle, store, refresh]);

  // Keep the inspector subscription in sync with expanded types + pins.
  useEffect(() => {
    let lastKey = "";
    const sync = () => {
      const s = store.getState();
      const names = subscriptionNames(s.expanded, s.pins);
      const key = names.join(",");
      if (key !== lastKey) {
        lastKey = key;
        socketRef.current?.setSubscription(names);
      }
    };
    sync();
    return store.subscribe(sync);
  }, [store, urls.vehicle]);

  // Vehicle type / profile / link changes: modes, geofence and mission may change.
  useEffect(() => {
    let lastKey = "";
    return store.subscribe(() => {
      const st = store.getState().state;
      const key = st ? `${st.connected}|${st.profile}|${st.vehicle_type}` : "";
      if (key !== lastKey) {
        const first = lastKey === "";
        lastKey = key;
        if (!first && st) refreshVehicleType();
      }
    });
  }, [store, refreshVehicleType]);

  const value = useMemo<AppCtx>(
    () => ({ urls, setUrls, store, vehicle, agent, notify, toasts, dismissToast, refresh }),
    [urls, setUrls, store, vehicle, agent, notify, toasts, dismissToast, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export { errText };
