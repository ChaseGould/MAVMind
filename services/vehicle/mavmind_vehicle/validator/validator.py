"""Deterministic mission validator. Never an LLM. Every limit comes from config/safety.yaml.

Checks: schema, item count, command whitelist, home known, structure, altitude limits,
geofence polygon (points and legs), max distance from home, max leg length, speed and
servo limits, and estimated flight time against the battery.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator
from pymavlink.dialects.v20 import ardupilotmega as mavlink

from ..geo import distance_m, point_in_polygon, segment_inside_polygon
from ..messages import MissionItem
from ..paths import shared_dir

FRAME_REL = mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT
FRAME_MISSION = mavlink.MAV_FRAME_MISSION
NAV_WITH_POSITION = {"NAV_WAYPOINT", "NAV_LOITER_TIME", "NAV_LAND"}
TERMINAL = {"NAV_RETURN_TO_LAUNCH", "NAV_LAND"}


@dataclass
class Check:
    name: str
    ok: bool
    message: str


@dataclass
class VehicleContext:
    """What the validator needs to know about the vehicle right now."""

    home: tuple[float, float, float] | None  # lat, lon, alt_msl_m
    battery_remaining_pct: float | None
    vehicle_type: str | None = "copter"


@dataclass
class ValidationResult:
    ok: bool
    checks: list[Check]
    estimates: dict[str, float | None]
    items: list[MissionItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [asdict(c) for c in self.checks],
            "estimates": self.estimates,
        }

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


@cache
def mission_schema() -> dict[str, Any]:
    return json.loads((shared_dir() / "mission_schema.json").read_text())


def _schema_errors(mission: Any) -> list[str]:
    validator = Draft202012Validator(mission_schema())
    errors = sorted(validator.iter_errors(mission), key=lambda e: list(e.absolute_path))
    out = []
    for e in errors[:8]:
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        msg = e.message
        if e.validator == "oneOf" and isinstance(e.instance, dict):
            cmd = e.instance.get("command")
            msg = f"item does not match the schema for command {cmd!r} (unknown command or wrong/missing fields)"
        out.append(f"{path}: {msg}")
    return out


def expand(mission: dict[str, Any], home: tuple[float, float, float]) -> list[MissionItem]:
    """Convert a schema-valid mission to MAVLink items. Item 0 is home (ArduPilot convention)."""
    items = [
        MissionItem(0, mavlink.MAV_CMD_NAV_WAYPOINT, mavlink.MAV_FRAME_GLOBAL, lat=home[0], lon=home[1], alt=home[2])
    ]
    for raw in mission["items"]:
        seq = len(items)
        cmd = raw["command"]
        if cmd == "NAV_TAKEOFF":
            it = MissionItem(seq, mavlink.MAV_CMD_NAV_TAKEOFF, FRAME_REL, alt=float(raw["alt_m"]))
        elif cmd == "NAV_WAYPOINT":
            it = MissionItem(
                seq,
                mavlink.MAV_CMD_NAV_WAYPOINT,
                FRAME_REL,
                param1=float(raw.get("hold_s", 0)),
                lat=raw["lat"],
                lon=raw["lon"],
                alt=float(raw["alt_m"]),
            )
        elif cmd == "NAV_LOITER_TIME":
            it = MissionItem(
                seq,
                mavlink.MAV_CMD_NAV_LOITER_TIME,
                FRAME_REL,
                param1=float(raw["time_s"]),
                lat=raw["lat"],
                lon=raw["lon"],
                alt=float(raw["alt_m"]),
            )
        elif cmd == "NAV_LAND":
            it = MissionItem(seq, mavlink.MAV_CMD_NAV_LAND, FRAME_REL, lat=raw.get("lat", 0.0), lon=raw.get("lon", 0.0))
        elif cmd == "NAV_RETURN_TO_LAUNCH":
            it = MissionItem(seq, mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, FRAME_REL)
        elif cmd == "DO_CHANGE_SPEED":
            it = MissionItem(
                seq, mavlink.MAV_CMD_DO_CHANGE_SPEED, FRAME_MISSION, param1=1, param2=float(raw["speed_mps"]), param3=-1
            )
        elif cmd == "DO_SET_SERVO":
            it = MissionItem(seq, mavlink.MAV_CMD_DO_SET_SERVO, FRAME_MISSION, param1=raw["servo"], param2=raw["pwm"])
        elif cmd == "DO_GRIPPER":
            action = 0 if raw["action"] == "release" else 1
            it = MissionItem(
                seq, mavlink.MAV_CMD_DO_GRIPPER, FRAME_MISSION, param1=raw.get("gripper", 1), param2=action
            )
        elif cmd == "DO_DIGICAM_CONTROL":
            # param5 (x) = shot: 1 triggers the camera
            it = MissionItem(seq, mavlink.MAV_CMD_DO_DIGICAM_CONTROL, FRAME_MISSION, lat=1)
        else:  # pragma: no cover - schema rejects unknown commands first
            raise ValueError(f"unsupported command {cmd}")
        items.append(it)
    return items


def _path_points(
    mission: dict[str, Any], home: tuple[float, float, float]
) -> list[tuple[str, float, float, float | None]]:
    """Positions the vehicle will fly through, starting at home, in order: (label, lat, lon, alt_rel)."""
    pts: list[tuple[str, float, float, float | None]] = [("home", home[0], home[1], 0.0)]
    alt = 0.0
    for i, it in enumerate(mission["items"], start=1):
        cmd = it["command"]
        if cmd == "NAV_TAKEOFF":
            alt = float(it["alt_m"])
            pts.append((f"item {i} takeoff", pts[-1][1], pts[-1][2], alt))
        elif cmd in ("NAV_WAYPOINT", "NAV_LOITER_TIME"):
            alt = float(it["alt_m"])
            pts.append((f"item {i} {cmd}", it["lat"], it["lon"], alt))
        elif cmd == "NAV_LAND":
            lat, lon = (it["lat"], it["lon"]) if "lat" in it else (pts[-1][1], pts[-1][2])
            pts.append((f"item {i} land", lat, lon, 0.0))
            break
        elif cmd == "NAV_RETURN_TO_LAUNCH":
            pts.append((f"item {i} RTL", home[0], home[1], 0.0))
            break
    return pts


def estimate_flight_time(
    mission: dict[str, Any], home: tuple[float, float, float], limits: dict[str, Any]
) -> dict[str, float]:
    ft = limits.get("flight_time", {})
    speed = float(ft.get("cruise_speed_mps", 8))
    climb = float(ft.get("climb_rate_mps", 2.5))
    descent = float(ft.get("descent_rate_mps", 1.0))
    t = 0.0
    dist = 0.0
    lat, lon, alt = home[0], home[1], 0.0
    for it in mission["items"]:
        cmd = it["command"]
        if cmd == "DO_CHANGE_SPEED":
            speed = max(0.5, float(it["speed_mps"]))
        elif cmd == "NAV_TAKEOFF":
            target = float(it["alt_m"])
            t += max(0.0, target - alt) / climb
            alt = target
        elif cmd in ("NAV_WAYPOINT", "NAV_LOITER_TIME"):
            d = distance_m(lat, lon, it["lat"], it["lon"])
            dz = float(it["alt_m"]) - alt
            t += max(d / speed, dz / climb if dz > 0 else -dz / descent)
            dist += d
            lat, lon, alt = it["lat"], it["lon"], float(it["alt_m"])
            t += float(it.get("hold_s", 0)) + float(it.get("time_s", 0))
        elif cmd == "NAV_LAND":
            if "lat" in it:
                d = distance_m(lat, lon, it["lat"], it["lon"])
                t += d / speed
                dist += d
            t += alt / descent
            break
        elif cmd == "NAV_RETURN_TO_LAUNCH":
            d = distance_m(lat, lon, home[0], home[1])
            t += d / speed + alt / descent
            dist += d
            break
    t *= 1 + float(ft.get("overhead_pct", 15)) / 100
    return {"total_distance_m": round(dist, 1), "flight_time_s": round(t, 1)}


def validate_mission(mission: Any, limits: dict[str, Any], vehicle: VehicleContext) -> ValidationResult:
    checks: list[Check] = []
    estimates: dict[str, float | None] = {
        "total_distance_m": None,
        "flight_time_s": None,
        "battery_required_pct": None,
        "battery_available_pct": vehicle.battery_remaining_pct,
    }

    def done() -> ValidationResult:
        return ValidationResult(all(c.ok for c in checks), checks, estimates)

    errors = _schema_errors(mission)
    checks.append(Check("schema", not errors, "; ".join(errors) if errors else "matches shared/mission_schema.json"))
    if errors:
        return done()
    items = mission["items"]

    max_items = int(limits.get("max_items", 100))
    checks.append(Check("item_count", len(items) <= max_items, f"{len(items)} items (limit {max_items})"))

    whitelist = set(limits.get("command_whitelist", []))
    bad = sorted({it["command"] for it in items} - whitelist)
    checks.append(
        Check("command_whitelist", not bad, f"not allowed: {', '.join(bad)}" if bad else "all commands whitelisted")
    )

    if vehicle.home is None:
        checks.append(Check("home_known", False, "home position unknown; cannot check distances or the geofence"))
        return done()
    home = vehicle.home
    checks.append(Check("home_known", True, f"home {home[0]:.6f}, {home[1]:.6f}"))

    structure = limits.get("structure", {})
    problems = []
    nav = [it for it in items if it["command"].startswith("NAV_")]
    if structure.get("first_nav_must_be_takeoff", True) and vehicle.vehicle_type in (None, "copter"):
        if not nav or nav[0]["command"] != "NAV_TAKEOFF":
            problems.append("first navigation item must be NAV_TAKEOFF")
    if structure.get("must_end_with_return_or_land", True):
        if not nav or nav[-1]["command"] not in TERMINAL:
            problems.append("mission must end with NAV_RETURN_TO_LAUNCH or NAV_LAND")
    term_idx = next((i for i, it in enumerate(items) if it["command"] in TERMINAL), None)
    if term_idx is not None and any(it["command"].startswith("NAV_") for it in items[term_idx + 1 :]):
        problems.append("navigation items after RTL/LAND would never run")
    if sum(1 for it in nav if it["command"] == "NAV_TAKEOFF") > 1:
        problems.append("more than one NAV_TAKEOFF")
    checks.append(
        Check("structure", not problems, "; ".join(problems) if problems else "takeoff first, ends with RTL/LAND")
    )

    alt_cfg = limits.get("altitude", {})
    amin, amax = float(alt_cfg.get("min_m", 5)), float(alt_cfg.get("max_m", 120))
    alt_bad = [
        f"item {i} ({it['command']}) {it['alt_m']} m"
        for i, it in enumerate(items, start=1)
        if "alt_m" in it and not amin <= float(it["alt_m"]) <= amax
    ]
    checks.append(
        Check(
            "altitude_limits",
            not alt_bad,
            f"outside {amin:g}-{amax:g} m: {', '.join(alt_bad)}"
            if alt_bad
            else f"all altitudes within {amin:g}-{amax:g} m",
        )
    )

    pts = _path_points(mission, home)
    fence = limits.get("geofence", {})
    if fence.get("enabled", True):
        poly = fence.get("polygon") or []
        if len(poly) < 3:
            checks.append(Check("geofence", False, "geofence enabled but polygon has fewer than 3 points"))
        else:
            outside = [label for label, la, lo, _ in pts if not point_in_polygon(la, lo, poly)]
            legs_out = [
                f"{a[0]} -> {b[0]}"
                for a, b in zip(pts, pts[1:])
                if not outside and not segment_inside_polygon((a[1], a[2]), (b[1], b[2]), poly)
            ]
            msg = "all points and legs inside the geofence"
            if outside:
                msg = f"outside geofence: {', '.join(outside)}"
            elif legs_out:
                msg = f"legs leave the geofence: {', '.join(legs_out)}"
            checks.append(Check("geofence", not outside and not legs_out, msg))

    max_home = float(limits.get("max_distance_from_home_m", 1000))
    far = [f"{label} {d:.0f} m" for label, la, lo, _ in pts if (d := distance_m(home[0], home[1], la, lo)) > max_home]
    checks.append(
        Check(
            "max_distance_from_home",
            not far,
            f"beyond {max_home:g} m: {', '.join(far)}" if far else f"all within {max_home:g} m of home",
        )
    )

    max_leg = float(limits.get("max_leg_length_m", 1000))
    long_legs = []
    for a, b in zip(pts, pts[1:]):
        d = distance_m(a[1], a[2], b[1], b[2])
        if d > max_leg:
            long_legs.append(f"{a[0]} -> {b[0]} {d:.0f} m")
    checks.append(
        Check(
            "max_leg_length",
            not long_legs,
            f"legs over {max_leg:g} m: {', '.join(long_legs)}" if long_legs else f"all legs within {max_leg:g} m",
        )
    )

    max_speed = float(limits.get("speed", {}).get("max_mps", 15))
    fast = [
        f"item {i} {it['speed_mps']} m/s"
        for i, it in enumerate(items, start=1)
        if it["command"] == "DO_CHANGE_SPEED" and it["speed_mps"] > max_speed
    ]
    if any(it["command"] == "DO_CHANGE_SPEED" for it in items):
        checks.append(
            Check(
                "speed_limit",
                not fast,
                f"over {max_speed:g} m/s: {', '.join(fast)}" if fast else f"speeds within {max_speed:g} m/s",
            )
        )

    allowed_servos = set(limits.get("servo", {}).get("allowed_channels", []))
    servo_items = [(i, it) for i, it in enumerate(items, start=1) if it["command"] == "DO_SET_SERVO"]
    if servo_items:
        bad_servo = [f"item {i} servo {it['servo']}" for i, it in servo_items if it["servo"] not in allowed_servos]
        checks.append(
            Check(
                "servo_channels",
                not bad_servo,
                f"servo channel not allowed: {', '.join(bad_servo)} (allowed {sorted(allowed_servos)})"
                if bad_servo
                else "servo channels allowed",
            )
        )

    est = estimate_flight_time(mission, home, limits)
    estimates.update(est)
    ft = limits.get("flight_time", {})
    endurance = float(ft.get("endurance_full_battery_s", 900))
    reserve = float(ft.get("reserve_pct", 25))
    required = round(100 * est["flight_time_s"] / endurance, 1)
    estimates["battery_required_pct"] = required
    if vehicle.battery_remaining_pct is None:
        checks.append(Check("battery", False, "battery remaining unknown; cannot check flight time against battery"))
    else:
        left = vehicle.battery_remaining_pct - required
        checks.append(
            Check(
                "battery",
                left >= reserve,
                f"needs ~{required:.0f}% for {est['flight_time_s'] / 60:.1f} min; {vehicle.battery_remaining_pct:.0f}% available; "
                f"{left:.0f}% would remain (reserve {reserve:g}%)",
            )
        )

    result = done()
    result.items = expand(mission, home)
    return result


def diff_missions(expected: list[MissionItem], actual: list[MissionItem]) -> list[str]:
    """Compare an approved mission with what the vehicle returned. Item 0 (home) is ignored."""
    diffs: list[str] = []
    if len(expected) != len(actual):
        diffs.append(f"item count: expected {len(expected)}, vehicle has {len(actual)}")
    for e, a in zip(expected[1:], actual[1:]):
        where = f"item {e.seq}"
        if e.command != a.command:
            diffs.append(f"{where}: command {e.command_name} != {a.command_name}")
            continue
        if e.frame in (0, 3, 10) and e.has_position:
            if abs(e.lat - a.lat) > 2e-7 or abs(e.lon - a.lon) > 2e-7:
                diffs.append(f"{where}: position {e.lat:.7f},{e.lon:.7f} != {a.lat:.7f},{a.lon:.7f}")
        if e.command in (mavlink.MAV_CMD_NAV_WAYPOINT, mavlink.MAV_CMD_NAV_LOITER_TIME, mavlink.MAV_CMD_NAV_TAKEOFF):
            if abs(e.alt - a.alt) > 0.05:
                diffs.append(f"{where}: altitude {e.alt} != {a.alt}")
        for idx in _significant_params(e.command):
            ev, av = getattr(e, f"param{idx}"), getattr(a, f"param{idx}")
            if abs(ev - av) > 0.05:
                diffs.append(f"{where}: param{idx} {ev} != {av}")
    return diffs


def _significant_params(cmd: int) -> tuple[int, ...]:
    return {
        mavlink.MAV_CMD_NAV_WAYPOINT: (1,),
        mavlink.MAV_CMD_NAV_LOITER_TIME: (1,),
        mavlink.MAV_CMD_DO_CHANGE_SPEED: (2,),
        mavlink.MAV_CMD_DO_SET_SERVO: (1, 2),
        mavlink.MAV_CMD_DO_GRIPPER: (1, 2),
    }.get(cmd, ())
