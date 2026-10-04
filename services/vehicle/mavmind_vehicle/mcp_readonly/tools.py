"""Read-only vehicle tools. Pure functions over the service context, so they unit-test without MCP.

Conventions (see the build plan):
- every response carries `source`, `timestamp`, `age_s`, `rate_hz`;
- units are in field names and scaled integers are converted;
- missing data is `available: false` with a reason, never a guess;
- history/analysis output is capped (default 200 points);
- statistics are computed here, never by the LLM.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Protocol

from ..geo import bearing_deg, distance_m
from ..messages import NAV_COMMANDS_WITH_POSITION
from ..sources.base import BaseSource, match_params
from ..state import battery_summary, ekf_summary, gps_fix_name, home_position, link_summary, position
from ..store import SEVERITIES, TelemetryStore
from ..units import convert_fields, field_value

DEFAULT_MAX_POINTS = 200
HARD_MAX_POINTS = 1000
STALE_S = 5.0

# A few enumerated parameters the LLM is often asked about (ArduCopter 4.x meanings).
PARAM_MEANINGS: dict[str, dict[int, str]] = {
    "BATT_FS_LOW_ACT": {
        0: "None",
        1: "Land",
        2: "RTL",
        3: "SmartRTL or RTL",
        4: "SmartRTL or Land",
        5: "Terminate",
        6: "Auto DO_LAND_START or RTL",
        7: "Brake or Land",
    },
    "BATT_FS_CRT_ACT": {
        0: "None",
        1: "Land",
        2: "RTL",
        3: "SmartRTL or RTL",
        4: "SmartRTL or Land",
        5: "Terminate",
        6: "Auto DO_LAND_START or RTL",
        7: "Brake or Land",
    },
    "FS_THR_ENABLE": {
        0: "Disabled",
        1: "Enabled always RTL",
        2: "Enabled continue mission in auto",
        3: "Enabled always Land",
        4: "Enabled always SmartRTL or RTL",
        5: "Enabled always SmartRTL or Land",
        6: "Enabled Auto DO_LAND_START or RTL",
        7: "Enabled always Brake or Land",
    },
    "FS_GCS_ENABLE": {
        0: "Disabled",
        1: "Enabled always RTL",
        2: "Enabled continue mission in auto",
        3: "Enabled always SmartRTL or RTL",
        4: "Enabled always SmartRTL or Land",
        5: "Enabled always Land",
        6: "Enabled Auto DO_LAND_START or RTL",
        7: "Enabled always Brake or Land",
    },
    "FS_EKF_ACTION": {1: "Land", 2: "AltHold", 3: "Land even in Stabilize"},
    "FENCE_ACTION": {
        0: "Report only",
        1: "RTL or Land",
        2: "Always Land",
        3: "SmartRTL or RTL or Land",
        4: "Brake or Land",
        5: "SmartRTL or Land",
    },
    "FENCE_ENABLE": {0: "Disabled", 1: "Enabled"},
}


class Context(Protocol):
    store: TelemetryStore
    source: BaseSource | None

    @property
    def source_label(self) -> str: ...


# ----------------------------------------------------------------- helpers
def _meta(ctx: Context, msg_name: str | None = None) -> dict[str, Any]:
    store = ctx.store
    out: dict[str, Any] = {"source": ctx.source_label, "timestamp": round(store.now(), 3)}
    if msg_name is not None:
        age = store.age(msg_name)
        out["age_s"] = None if age is None else round(age, 2)
        out["rate_hz"] = round(store.rate(msg_name), 2)
    else:
        out["age_s"] = None
        out["rate_hz"] = None
    return out


def _unavailable(ctx: Context, reason: str, msg_name: str | None = None) -> dict[str, Any]:
    return {**_meta(ctx, msg_name), "available": False, "reason": reason}


def _age(store: TelemetryStore, name: str) -> float | None:
    a = store.age(name)
    return None if a is None else round(a, 2)


def _resolve_name(store: TelemetryStore, name: str) -> str | None:
    up = name.strip().upper()
    return up if store.latest(up) is not None else None


def _pick(points: list[Any], max_points: int) -> list[Any]:
    """Evenly downsample, always keeping the first and last point."""
    n = len(points)
    if n <= max_points:
        return points
    if max_points <= 1:
        return points[-1:]
    step = (n - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


def _clamp_points(max_points: int | None) -> int:
    if not max_points or max_points <= 0:
        return DEFAULT_MAX_POINTS
    return min(int(max_points), HARD_MAX_POINTS)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return float(v)


# ------------------------------------------------------------------- tools
def get_vehicle_state(ctx: Context) -> dict[str, Any]:
    store = ctx.store
    if store.latest("HEARTBEAT") is None:
        return _unavailable(ctx, "no heartbeat received from the vehicle yet", "HEARTBEAT")
    out = {**_meta(ctx, "HEARTBEAT"), "available": True}
    out.update(
        vehicle_type=store.vehicle_type,
        mode=store.mode,
        armed=store.armed,
        flight_time_s=_r(store.flight_time_s(), 1),
    )
    pos = position(store)
    out["position"] = (
        {**{k: _r(v, 7) for k, v in pos.items()}, "age_s": _age(store, "GLOBAL_POSITION_INT")}
        if pos
        else {"available": False, "reason": "no GLOBAL_POSITION_INT with a valid fix"}
    )
    att = store.latest("ATTITUDE")
    if att:
        c = convert_fields("ATTITUDE", att.fields)
        out["attitude"] = {
            "roll_deg": _r(c["roll_deg"], 2),
            "pitch_deg": _r(c["pitch_deg"], 2),
            "yaw_deg": _r(c["yaw_deg"], 2),
            "age_s": _age(store, "ATTITUDE"),
        }
    else:
        out["attitude"] = {"available": False, "reason": "no ATTITUDE received"}
    vfr = store.latest("VFR_HUD")
    if vfr:
        c = convert_fields("VFR_HUD", vfr.fields)
        out["speeds"] = {
            "airspeed_mps": _r(c["airspeed_mps"], 2),
            "groundspeed_mps": _r(c["groundspeed_mps"], 2),
            "climb_mps": _r(c["climb_mps"], 2),
            "heading_deg": c["heading_deg"],
            "throttle_pct": c["throttle_pct"],
            "age_s": _age(store, "VFR_HUD"),
        }
    else:
        out["speeds"] = {"available": False, "reason": "no VFR_HUD received"}
    bat = battery_summary(store)
    out["battery"] = (
        {**bat, "age_s": _age(store, "SYS_STATUS") if store.latest("SYS_STATUS") else _age(store, "BATTERY_STATUS")}
        if bat
        else {"available": False, "reason": "no SYS_STATUS or BATTERY_STATUS received"}
    )
    gps = store.latest("GPS_RAW_INT")
    if gps:
        c = convert_fields("GPS_RAW_INT", gps.fields)
        out["gps"] = {
            "fix_type": c["fix_type"],
            "fix_name": gps_fix_name(c["fix_type"]),
            "satellites": c["satellites_visible"],
            "hdop": c["hdop"],
            "age_s": _age(store, "GPS_RAW_INT"),
        }
    else:
        out["gps"] = {"available": False, "reason": "no GPS_RAW_INT received"}
    ekf = ekf_summary(store)
    out["ekf"] = (
        {**ekf, "age_s": _age(store, "EKF_STATUS_REPORT")}
        if ekf
        else {"available": False, "reason": "no EKF_STATUS_REPORT received (not sent by this autopilot or stream)"}
    )
    stale = sorted(
        n for n in ("GLOBAL_POSITION_INT", "ATTITUDE", "VFR_HUD", "SYS_STATUS") if (store.age(n) or 0) > STALE_S
    )
    if stale:
        out["stale_messages"] = stale
    return out


async def get_mission(ctx: Context) -> dict[str, Any]:
    store = ctx.store
    items = store.mission()
    if not items and ctx.source is not None and ctx.source.is_live:
        try:
            items = await ctx.source.download_mission()
            store.set_mission(items)
        except Exception as exc:  # noqa: BLE001
            return _unavailable(ctx, f"mission download failed: {exc}", "MISSION_CURRENT")
    if not items:
        return _unavailable(
            ctx, "no mission known (vehicle has none, or it has not been downloaded)", "MISSION_CURRENT"
        )
    out = {**_meta(ctx, "MISSION_CURRENT"), "available": True}
    current = store.mission_current_seq
    nav = [it for it in items if it.seq > 0 and it.command in NAV_COMMANDS_WITH_POSITION | {20}]
    done = [it for it in nav if current is not None and it.seq < current]
    out.update(
        count=len(items),
        note="item 0 is the home position on ArduPilot",
        current_seq=current,
        items=[it.to_api() for it in items],
        progress={
            "nav_items_total": len(nav),
            "nav_items_completed": len(done),
            "pct": round(100 * len(done) / len(nav), 1) if nav and current is not None else None,
        },
    )
    pos = position(store)
    nxt = next((it for it in items if it.seq == current), None)
    if nxt is not None:
        out["current_item"] = nxt.to_api()
        if pos and nxt.has_position:
            out["distance_to_current_m"] = round(distance_m(pos["lat"], pos["lon"], nxt.lat, nxt.lon), 1)
            out["bearing_to_current_deg"] = round(bearing_deg(pos["lat"], pos["lon"], nxt.lat, nxt.lon), 1)
    nco = store.latest("NAV_CONTROLLER_OUTPUT")
    if nco is not None:
        out["nav_controller_wp_dist_m"] = nco.fields.get("wp_dist")
    remaining = 0.0
    if pos and current is not None:
        pts = [(pos["lat"], pos["lon"])] + [(it.lat, it.lon) for it in items if it.seq >= current and it.has_position]
        remaining = sum(distance_m(*a, *b) for a, b in zip(pts, pts[1:]))
        out["remaining_path_m"] = round(remaining, 1)
    return out


def list_messages(ctx: Context) -> dict[str, Any]:
    store = ctx.store
    names = store.names()
    if not names:
        return _unavailable(ctx, "no messages received yet")
    msgs = [
        {"name": n, "rate_hz": round(store.rate(n), 2), "age_s": _age(store, n), "count": store.count(n)} for n in names
    ]
    return {**_meta(ctx), "available": True, "count": len(msgs), "messages": msgs}


def get_message(ctx: Context, name: str) -> dict[str, Any]:
    store = ctx.store
    real = _resolve_name(store, name)
    if real is None:
        return _unavailable(ctx, f"{name.upper()} has not been received on this link")
    m = store.latest(real)
    assert m is not None
    return {
        **_meta(ctx, real),
        "available": True,
        "name": real,
        "sysid": m.sysid,
        "compid": m.compid,
        "fields": convert_fields(real, m.fields),
    }


def get_message_history(
    ctx: Context,
    name: str,
    fields: list[str] | None = None,
    window_s: float = 60.0,
    max_points: int = DEFAULT_MAX_POINTS,
) -> dict[str, Any]:
    store = ctx.store
    real = _resolve_name(store, name)
    if real is None:
        return _unavailable(ctx, f"{name.upper()} has not been received on this link")
    now = store.now()
    hist = store.history(real, since=now - window_s)
    if not hist:
        return _unavailable(ctx, f"no {real} samples in the last {window_s:.0f}s", real)
    sample = convert_fields(real, hist[-1].fields)
    wanted = fields or [k for k, v in sample.items() if _num(v) is not None]
    unknown = [f for f in wanted if field_value(real, hist[-1].fields, f) is None and f not in sample]
    pts = _pick(hist, _clamp_points(max_points))
    points = []
    for m in pts:
        row: dict[str, Any] = {"t_rel_s": round(m.timestamp - now, 2)}
        for f in wanted:
            row[f] = field_value(real, m.fields, f)
        points.append(row)
    out = {
        **_meta(ctx, real),
        "available": True,
        "name": real,
        "window_s": window_s,
        "samples_in_window": len(hist),
        "points_returned": len(points),
        "history_resolution_hz": round(1 / store.history_min_dt, 2) if store.history_min_dt else None,
        "points": points,
    }
    if unknown:
        out["unknown_fields"] = unknown
    return out


def analyze_field(
    ctx: Context,
    message: str,
    field: str,
    window_s: float = 300.0,
    threshold: float | None = None,
) -> dict[str, Any]:
    store = ctx.store
    real = _resolve_name(store, message)
    if real is None:
        return _unavailable(ctx, f"{message.upper()} has not been received on this link")
    now = store.now()
    hist = store.history(real, since=now - window_s)
    series = [(m.timestamp, _num(field_value(real, m.fields, field))) for m in hist]
    series = [(t, v) for t, v in series if v is not None]
    if not series:
        return _unavailable(ctx, f"no numeric values for {real}.{field} in the last {window_s:.0f}s", real)
    ts = [t for t, _ in series]
    vs = [v for _, v in series]
    imin = min(range(len(vs)), key=vs.__getitem__)
    imax = max(range(len(vs)), key=vs.__getitem__)
    slope = _slope(ts, vs)
    span = ts[-1] - ts[0]
    change = slope * span if slope is not None else 0.0
    vrange = max(vs) - min(vs)
    if slope is None or vrange == 0 or abs(change) < 0.05 * vrange:
        trend = "flat"
    else:
        trend = "rising" if slope > 0 else "falling"
    out = {
        **_meta(ctx, real),
        "available": True,
        "message": real,
        "field": field,
        "window_s": window_s,
        "samples": len(vs),
        "span_s": round(span, 2),
        "first": _r(vs[0], 4),
        "last": _r(vs[-1], 4),
        "min": _r(vs[imin], 4),
        "min_t_rel_s": round(ts[imin] - now, 2),
        "max": _r(vs[imax], 4),
        "max_t_rel_s": round(ts[imax] - now, 2),
        "mean": _r(statistics.fmean(vs), 4),
        "std": _r(statistics.pstdev(vs), 4) if len(vs) > 1 else 0.0,
        "trend": trend,
        "slope_per_s": _r(slope, 6) if slope is not None else None,
        "change_over_window": _r(vs[-1] - vs[0], 4),
    }
    if threshold is not None:
        crossings = []
        for (_t0, v0), (t1, v1) in zip(series, series[1:]):
            if (v0 >= threshold) != (v1 >= threshold):
                crossings.append(
                    {
                        "t_rel_s": round(t1 - now, 2),
                        "timestamp": round(t1, 3),
                        "direction": "below" if v1 < threshold else "above",
                        "value": _r(v1, 4),
                    }
                )
        out["threshold"] = threshold
        out["crossings"] = crossings[:DEFAULT_MAX_POINTS]
        out["time_below_threshold_s"] = round(
            sum(t1 - t0 for (t0, v0), (t1, _) in zip(series, series[1:]) if v0 < threshold), 2
        )
    return out


def _slope(ts: list[float], vs: list[float]) -> float | None:
    n = len(ts)
    if n < 2:
        return None
    mt = statistics.fmean(ts)
    mv = statistics.fmean(vs)
    den = sum((t - mt) ** 2 for t in ts)
    if den == 0:
        return None
    return sum((t - mt) * (v - mv) for t, v in zip(ts, vs)) / den


def get_statustext(
    ctx: Context, since_seconds_ago: float = 600.0, min_severity: str | None = None, limit: int = 100
) -> dict[str, Any]:
    store = ctx.store
    now = store.now()
    texts = store.statustext(since=now - since_seconds_ago)
    if min_severity:
        cutoff = SEVERITIES.index(min_severity.upper()) if min_severity.upper() in SEVERITIES else 7
        texts = [t for t in texts if t.severity in SEVERITIES[: cutoff + 1]]
    texts = texts[-limit:]
    return {
        **_meta(ctx, "STATUSTEXT"),
        "available": True,
        "since_seconds_ago": since_seconds_ago,
        "count": len(texts),
        "messages": [
            {
                "timestamp": round(t.timestamp, 3),
                "t_rel_s": round(t.timestamp - now, 2),
                "severity": t.severity,
                "text": t.message,
            }
            for t in texts
        ],
    }


def get_events(
    ctx: Context,
    since_seconds_ago: float = 600.0,
    since_timestamp: float | None = None,
    kinds: list[str] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    store = ctx.store
    now = store.now()
    since = since_timestamp if since_timestamp is not None else now - since_seconds_ago
    evs = store.events(since=since, kinds=set(kinds) if kinds else None)[-limit:]
    return {
        **_meta(ctx),
        "available": True,
        "since_timestamp": round(since, 3),
        "count": len(evs),
        "events": [{**e.to_dict(), "t_rel_s": round(e.timestamp - now, 2)} for e in evs],
    }


async def get_params(ctx: Context, names: list[str]) -> dict[str, Any]:
    if not names:
        return _unavailable(ctx, "give parameter names or prefixes such as FS_ or BATT_")
    values: dict[str, float] = {}
    error = None
    if ctx.source is not None:
        try:
            values = await ctx.source.get_params(names)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    if not values:
        values = match_params(ctx.store.params(), names)
    if not values:
        reason = "none of the requested parameters were returned by the vehicle or seen on the link"
        if error:
            reason += f" ({error})"
        return _unavailable(ctx, reason, "PARAM_VALUE")
    params = []
    for k, v in values.items():
        entry: dict[str, Any] = {"name": k, "value": int(v) if float(v).is_integer() else round(v, 6)}
        meaning = PARAM_MEANINGS.get(k, {}).get(int(v)) if float(v).is_integer() else None
        if meaning:
            entry["meaning"] = meaning
        params.append(entry)
    missing = [n for n in names if not n.endswith(("_", "*")) and n.upper() not in values]
    out = {**_meta(ctx, "PARAM_VALUE"), "available": True, "count": len(params), "params": params}
    if missing:
        out["missing"] = missing
    return out


def get_link_health(ctx: Context) -> dict[str, Any]:
    store = ctx.store
    if store.latest("HEARTBEAT") is None:
        return _unavailable(ctx, "no heartbeat received from the vehicle yet", "HEARTBEAT")
    link = link_summary(store)
    stats = store.link_stats()
    hb_age = link["last_heartbeat_age_s"] or 0.0
    loss = link["packet_loss_pct"] or 0.0
    status = "lost" if hb_age > 5 else "degraded" if hb_age > 2 or loss > 5 else "ok"
    radio = store.latest("RADIO_STATUS")
    sys = store.latest("SYS_STATUS")
    total_rate = sum(store.rate(n) for n in store.names())
    out = {
        **_meta(ctx, "HEARTBEAT"),
        "available": True,
        "status": status,
        "last_heartbeat_age_s": link["last_heartbeat_age_s"],
        "packet_loss_pct_recent": stats["window_packet_loss_pct"] and round(stats["window_packet_loss_pct"], 2),
        "packet_loss_pct_total": stats["packet_loss_pct"] and round(stats["packet_loss_pct"], 2),
        "packets_received": stats["received"],
        "packets_lost": stats["lost"],
        "total_message_rate_hz": round(total_rate, 1),
        "message_rates_hz": {n: round(store.rate(n), 2) for n in store.names() if store.rate(n) > 0},
    }
    if radio:
        out["radio"] = {
            **{k: radio.fields.get(k) for k in ("rssi", "remrssi", "noise", "remnoise", "txbuf", "rxerrors", "fixed")},
            "age_s": _age(store, "RADIO_STATUS"),
        }
    else:
        out["radio"] = {"available": False, "reason": "no RADIO_STATUS (not a SiK/RFD radio link, or not streamed)"}
    if sys:
        out["fcu_drop_rate_comm_pct"] = round(sys.fields.get("drop_rate_comm", 0) / 100, 2)
    return out


def get_home(ctx: Context) -> dict[str, Any]:
    store = ctx.store
    home = home_position(store)
    if home is None:
        return _unavailable(
            ctx, "home position not received yet (needs HOME_POSITION or a downloaded mission)", "HOME_POSITION"
        )
    out = {**_meta(ctx, "HOME_POSITION"), "available": True, "home": home}
    pos = position(store)
    if pos:
        out["distance_m"] = round(distance_m(pos["lat"], pos["lon"], home["lat"], home["lon"]), 1)
        out["bearing_deg"] = round(bearing_deg(pos["lat"], pos["lon"], home["lat"], home["lon"]), 1)
        out["alt_above_home_m"] = _r(pos["alt_rel_m"], 2)
    else:
        out["distance_m"] = None
        out["position_note"] = "vehicle position unknown"
    return out


def _r(v: Any, nd: int) -> Any:
    return round(v, nd) if isinstance(v, float) else v
