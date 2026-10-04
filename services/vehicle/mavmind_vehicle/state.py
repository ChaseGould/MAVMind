"""Derive the compact vehicle state (UI frame and get_vehicle_state) from the TelemetryStore."""

from __future__ import annotations

from typing import Any

from .geo import bearing_deg, distance_m
from .messages import enum_name
from .store import BATTERY_STATES, TelemetryStore
from .units import convert_fields

EKF_FLAG_NAMES = {
    1: "attitude",
    2: "velocity_horiz",
    4: "velocity_vert",
    8: "pos_horiz_rel",
    16: "pos_horiz_abs",
    32: "pos_vert_abs",
    64: "pos_vert_agl",
    128: "const_pos_mode",
    256: "pred_pos_horiz_rel",
    512: "pred_pos_horiz_abs",
    1024: "uninitialized",
    32768: "gps_glitching",
}
EKF_REQUIRED = 1 | 2 | 4 | 8 | 16 | 32
EKF_VARIANCE_LIMIT = 0.8  # ArduPilot FS_EKF_THRESH default


def _conv(store: TelemetryStore, name: str) -> dict[str, Any] | None:
    m = store.latest(name)
    return convert_fields(name, m.fields) if m else None


def gps_fix_name(fix: int | None) -> str | None:
    return None if fix is None else enum_name("GPS_FIX_TYPE", fix, "GPS_FIX_TYPE_")


def ekf_summary(store: TelemetryStore) -> dict[str, Any] | None:
    m = store.latest("EKF_STATUS_REPORT")
    if m is None:
        return None
    f = m.fields
    flags = int(f.get("flags", 0))
    variances = {
        k: round(float(f.get(k, 0.0)), 3)
        for k in (
            "velocity_variance",
            "pos_horiz_variance",
            "pos_vert_variance",
            "compass_variance",
            "terrain_alt_variance",
        )
    }
    ok = (
        flags & EKF_REQUIRED == EKF_REQUIRED
        and not flags & (128 | 1024)
        and max(variances[k] for k in ("velocity_variance", "pos_horiz_variance", "compass_variance"))
        < EKF_VARIANCE_LIMIT
    )
    return {
        "ok": ok,
        "flags": [name for bit, name in EKF_FLAG_NAMES.items() if flags & bit],
        "variances": variances,
    }


def home_position(store: TelemetryStore) -> dict[str, Any] | None:
    hp = store.latest("HOME_POSITION")
    if hp is not None:
        c = convert_fields("HOME_POSITION", hp.fields)
        return {"lat": c["lat_deg"], "lon": c["lon_deg"], "alt_msl_m": c["alt_msl_m"], "from": "HOME_POSITION"}
    mission = store.mission()
    if mission and mission[0].seq == 0 and (mission[0].lat or mission[0].lon):
        it = mission[0]
        return {"lat": it.lat, "lon": it.lon, "alt_msl_m": it.alt, "from": "mission item 0"}
    return None


def position(store: TelemetryStore) -> dict[str, Any] | None:
    g = _conv(store, "GLOBAL_POSITION_INT")
    if g is None or (g["lat_deg"] == 0 and g["lon_deg"] == 0):
        return None
    return {
        "lat": g["lat_deg"],
        "lon": g["lon_deg"],
        "alt_msl_m": g["alt_msl_m"],
        "alt_rel_m": g["alt_rel_m"],
        "heading_deg": g["heading_deg"],
    }


def link_summary(store: TelemetryStore) -> dict[str, Any]:
    hb_age = store.age("HEARTBEAT")
    radio = store.latest("RADIO_STATUS")
    stats = store.link_stats()
    loss = stats["window_packet_loss_pct"]
    if loss is None:
        loss = stats["packet_loss_pct"]
    if hb_age is None or hb_age > 5:
        quality = 0.0 if hb_age is not None else None
    else:
        quality = max(0.0, 100.0 - (loss or 0.0) * 5)  # 20 % loss reads as unusable
    return {
        "last_heartbeat_age_s": None if hb_age is None else round(hb_age, 2),
        "rssi": radio.fields.get("rssi") if radio else None,
        "remrssi": radio.fields.get("remrssi") if radio else None,
        "packet_loss_pct": None if loss is None else round(loss, 2),
        "quality_pct": None if quality is None else round(quality, 1),
    }


def state_frame(store: TelemetryStore, profile: str | None, source: str | None, connected: bool) -> dict[str, Any]:
    att = _conv(store, "ATTITUDE")
    vfr = _conv(store, "VFR_HUD")
    sys = _conv(store, "SYS_STATUS")
    bat = _conv(store, "BATTERY_STATUS")
    gps = _conv(store, "GPS_RAW_INT")
    pos = position(store)
    home = home_position(store)
    ekf = ekf_summary(store)

    remaining = None
    if bat and bat.get("battery_remaining_pct") is not None:
        remaining = bat["battery_remaining_pct"]
    elif sys:
        remaining = sys.get("battery_remaining_pct")

    dist_home = bearing_home = None
    if pos and home:
        dist_home = round(distance_m(pos["lat"], pos["lon"], home["lat"], home["lon"]), 1)
        bearing_home = round(bearing_deg(pos["lat"], pos["lon"], home["lat"], home["lon"]), 1)

    heading = None
    if vfr:
        heading = vfr.get("heading_deg")
    elif pos:
        heading = pos["heading_deg"]

    return {
        "timestamp": store.now(),
        "connected": connected,
        "profile": profile,
        "source": source,
        "vehicle_type": store.vehicle_type,
        "mode": store.mode,
        "armed": store.armed,
        "lat": pos["lat"] if pos else None,
        "lon": pos["lon"] if pos else None,
        "alt_msl_m": pos["alt_msl_m"] if pos else None,
        "alt_rel_m": pos["alt_rel_m"] if pos else None,
        "heading_deg": heading,
        "roll_deg": _r(att, "roll_deg"),
        "pitch_deg": _r(att, "pitch_deg"),
        "yaw_deg": _r(att, "yaw_deg"),
        "airspeed_mps": _r(vfr, "airspeed_mps"),
        "groundspeed_mps": _r(vfr, "groundspeed_mps"),
        "climb_mps": _r(vfr, "climb_mps"),
        "throttle_pct": _r(vfr, "throttle_pct"),
        "battery_voltage_v": _r(sys, "voltage_battery_v"),
        "battery_current_a": _r(sys, "current_battery_a"),
        "battery_remaining_pct": remaining,
        "gps_fix_type": gps.get("fix_type") if gps else None,
        "gps_fix_name": gps_fix_name(gps.get("fix_type")) if gps else None,
        "gps_sats": gps.get("satellites_visible") if gps else None,
        "hdop": _r(gps, "hdop"),
        "link": link_summary(store),
        "home": {k: home[k] for k in ("lat", "lon", "alt_msl_m")} if home else None,
        "distance_home_m": dist_home,
        "bearing_home_deg": bearing_home,
        "flight_time_s": _round(store.flight_time_s(), 1),
        "mission_current_seq": store.mission_current_seq,
        "ekf_ok": ekf["ok"] if ekf else None,
    }


def battery_summary(store: TelemetryStore) -> dict[str, Any] | None:
    sys = _conv(store, "SYS_STATUS")
    bat = _conv(store, "BATTERY_STATUS")
    if not sys and not bat:
        return None
    out: dict[str, Any] = {}
    if sys:
        out.update(
            voltage_v=_r(sys, "voltage_battery_v"),
            current_a=_r(sys, "current_battery_a"),
            remaining_pct=sys.get("battery_remaining_pct"),
        )
    if bat:
        cells = [v for v in (bat.get("voltages_v") or []) if v is not None]
        out.update(
            consumed_mah=bat.get("current_consumed_mah"),
            remaining_pct=bat.get("battery_remaining_pct", out.get("remaining_pct")),
            cell_voltages_v=cells or None,
            temperature_c=bat.get("temperature_c"),
            charge_state=BATTERY_STATES.get(bat.get("charge_state") or 0, "OK") if bat.get("charge_state") else None,
        )
    return out


def _r(d: dict[str, Any] | None, key: str, nd: int = 3) -> Any:
    if not d:
        return None
    return _round(d.get(key), nd)


def _round(v: Any, nd: int) -> Any:
    return round(v, nd) if isinstance(v, float) else v
