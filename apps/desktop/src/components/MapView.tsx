import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, Marker, Polygon, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import { commandShort, missionPath, missionPoints } from "../lib/mapgeo";
import type { MissionItem, Proposal } from "../types";
import { useApp, useVehicle } from "../state/AppContext";
import { mapFocus } from "../state/mapFocus";

const VEHICLE_SVG = `<svg viewBox="-20 -20 40 40" width="40" height="40" aria-hidden="true">
  <path d="M0,-17 L11,13 L0,7 L-11,13 Z" fill="#ffd400" stroke="#111" stroke-width="2" stroke-linejoin="round"/>
</svg>`;

/** Vehicle marker + trail, updated imperatively from the store (no React re-render at 10 Hz). */
function VehicleLayer({ follow }: { follow: boolean }) {
  const map = useMap();
  const { store } = useApp();
  const followRef = useRef(follow);
  followRef.current = follow;

  useEffect(() => {
    const icon = L.divIcon({
      className: "mm-vehicle",
      html: `<div class="mm-vehicle-rot">${VEHICLE_SVG}</div>`,
      iconSize: [40, 40],
      iconAnchor: [20, 20],
    });
    const marker = L.marker([0, 0], { icon, interactive: false, keyboard: false, zIndexOffset: 1000 });
    const trail = L.polyline([], { color: "#ff7ad9", weight: 2, opacity: 0.85, interactive: false });
    trail.addTo(map);
    let onMap = false;
    let lastFrame: unknown = null;
    let lastTrack: unknown = null;
    let centredOnce = false;
    let lastPan = 0;

    const update = () => {
      const s = store.getState();
      if (s.track !== lastTrack) {
        lastTrack = s.track;
        trail.setLatLngs(s.track);
      }
      const f = s.state;
      if (f === lastFrame) return;
      lastFrame = f;
      if (!f || f.lat === null || f.lon === null) {
        if (onMap) {
          marker.remove();
          onMap = false;
        }
        return;
      }
      const ll = L.latLng(f.lat, f.lon);
      marker.setLatLng(ll);
      if (!onMap) {
        marker.addTo(map);
        onMap = true;
      }
      const el = marker.getElement()?.querySelector<HTMLElement>(".mm-vehicle-rot");
      const hdg = f.heading_deg ?? f.yaw_deg;
      if (el) {
        el.style.transform = `rotate(${hdg ?? 0}deg)`;
        el.style.opacity = hdg === null ? "0.5" : "1";
      }
      if (!centredOnce) {
        centredOnce = true;
        map.setView(ll, Math.max(map.getZoom(), 17), { animate: false });
      } else if (followRef.current) {
        const now = performance.now();
        if (now - lastPan > 250) {
          lastPan = now;
          map.panTo(ll, { animate: false });
        }
      }
    };
    update();
    const unsub = store.subscribe(update);
    const unsubFocus = mapFocus.on(({ points }) => {
      if (points.length === 1) map.setView(points[0], Math.max(map.getZoom(), 17));
      else if (points.length > 1) map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 19 });
    });
    return () => {
      unsub();
      unsubFocus();
      marker.remove();
      trail.remove();
    };
  }, [map, store]);
  return null;
}

const homeIcon = L.divIcon({ className: "mm-home", html: "H", iconSize: [22, 22], iconAnchor: [11, 11] });

function numberIcon(label: string, cls: string): L.DivIcon {
  const div = document.createElement("div");
  div.textContent = label;
  return L.divIcon({ className: `mm-wp ${cls}`, html: div, iconSize: [22, 22], iconAnchor: [11, 11] });
}

function useHome(): { lat: number; lon: number } | null {
  const key = useVehicle((s) => (s.state?.home ? `${s.state.home.lat},${s.state.home.lon}` : ""));
  return useMemo(() => {
    if (!key) return null;
    const [lat, lon] = key.split(",").map(Number);
    return { lat, lon };
  }, [key]);
}

const MissionLayer = memo(function MissionLayer({
  items,
  home,
  current,
  variant,
  title,
}: {
  items: MissionItem[];
  home: { lat: number; lon: number } | null;
  current: number | null;
  variant: "mission" | "proposal" | "invalid";
  title?: string;
}) {
  const path = useMemo(() => missionPath(items, home), [items, home]);
  const points = useMemo(() => missionPoints(items), [items]);
  const color = variant === "mission" ? "#ffb000" : variant === "proposal" ? "#36d1ff" : "#ff5a5a";
  return (
    <>
      {path.length > 1 && (
        <Polyline
          positions={path}
          pathOptions={{
            color,
            weight: variant === "mission" ? 3 : 2.5,
            opacity: 0.9,
            dashArray: variant === "mission" ? undefined : "8 6",
          }}
        />
      )}
      {points.map((p) => (
        <Marker
          key={`${p.seq}`}
          position={[p.lat, p.lon]}
          icon={numberIcon(String(p.seq), `mm-wp-${variant}${current === p.seq ? " mm-wp-current" : ""}`)}
        >
          <Tooltip direction="top" offset={[0, -10]}>
            {title ? `${title} · ` : ""}#{p.seq} {commandShort(p.command)}
            {p.alt_m !== null ? ` · ${p.alt_m.toFixed(0)} m` : ""}
          </Tooltip>
        </Marker>
      ))}
    </>
  );
});

function ProposalLayers({ home }: { home: { lat: number; lon: number } | null }) {
  const proposals = useVehicle((s) => s.proposals);
  const visible = useMemo(
    () =>
      Object.values(proposals)
        .filter((p: Proposal) => p.status === "pending" || p.status === "uploading" || p.status === "invalid")
        .sort((a, b) => a.created_at - b.created_at),
    [proposals],
  );
  return (
    <>
      {visible.map((p) => (
        <MissionLayer
          key={p.id}
          items={p.items}
          home={home}
          current={null}
          variant={p.status === "invalid" ? "invalid" : "proposal"}
          title={`${p.mission.name} (${p.status})`}
        />
      ))}
    </>
  );
}

function GeofenceLayer() {
  const geofence = useVehicle((s) => s.geofence);
  if (!geofence || geofence.polygon.length < 3) return null;
  return (
    <Polygon
      positions={geofence.polygon}
      pathOptions={{ color: "#ff3b3b", weight: 2, fillOpacity: 0.04, dashArray: "4 4" }}
    />
  );
}

function StaticLayers() {
  const home = useHome();
  const mission = useVehicle((s) => s.mission);
  const currentSeq = useVehicle((s) => s.state?.mission_current_seq ?? s.mission?.current_seq ?? null);
  return (
    <>
      <GeofenceLayer />
      {mission && mission.items.length > 0 && (
        <MissionLayer items={mission.items} home={home} current={currentSeq} variant="mission" title="Mission" />
      )}
      <ProposalLayers home={home} />
      {home && (
        <Marker position={[home.lat, home.lon]} icon={homeIcon}>
          <Tooltip direction="top" offset={[0, -10]}>
            Home
          </Tooltip>
        </Marker>
      )}
    </>
  );
}

export function MapView() {
  const { store } = useApp();
  const [follow, setFollow] = useState(true);
  const hasPos = useVehicle((s) => s.state?.lat != null && s.state?.lon != null);

  const recenter = () => {
    const f = store.getState().state;
    if (f && f.lat !== null && f.lon !== null) mapFocus.emit({ points: [[f.lat, f.lon]] });
    setFollow(true);
  };

  return (
    <div className="map-wrap">
      <MapContainer center={[20, 0]} zoom={2} className="map" zoomControl worldCopyJump attributionControl>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        <StaticLayers />
        <VehicleLayer follow={follow} />
        <DragUnfollow onDrag={() => setFollow(false)} />
        <AutoResize />
      </MapContainer>
      <div className="map-controls">
        <button className={`btn btn-small ${follow ? "btn-active" : ""}`} onClick={() => setFollow((f) => !f)} disabled={!hasPos}>
          {follow ? "Following" : "Follow"}
        </button>
        <button className="btn btn-small" onClick={recenter} disabled={!hasPos}>
          Recenter
        </button>
        <button className="btn btn-small" onClick={() => store.dispatch({ type: "clearTrack" })}>
          Clear trail
        </button>
      </div>
      <div className="map-legend">
        <span>
          <i className="lg lg-mission" />
          Mission
        </span>
        <span>
          <i className="lg lg-proposal" />
          Proposed
        </span>
        <span>
          <i className="lg lg-invalid" />
          Invalid
        </span>
        <span>
          <i className="lg lg-fence" />
          Fence
        </span>
        <span>
          <i className="lg lg-trail" />
          Trail
        </span>
      </div>
      {!hasPos && <div className="map-nofix">No vehicle position</div>}
    </div>
  );
}

/** Stop following when the user drags the map. */
function DragUnfollow({ onDrag }: { onDrag: () => void }) {
  const map = useMap();
  useEffect(() => {
    map.on("dragstart", onDrag);
    return () => {
      map.off("dragstart", onDrag);
    };
  }, [map, onDrag]);
  return null;
}

/** Leaflet needs to be told when its container changes size (panels, window). */
function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const ro = new ResizeObserver(() => map.invalidateSize({ animate: false }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  return null;
}
