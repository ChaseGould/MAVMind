"""The validator must reject every case in this suite. It is deterministic code, never an LLM."""

import copy

import pytest

from mavmind_vehicle.config import load_safety
from mavmind_vehicle.geo import offset
from mavmind_vehicle.messages import MissionItem
from mavmind_vehicle.validator import VehicleContext, diff_missions, validate_mission

HOME = (-35.363262, 149.165237, 584.0)
LIMITS = load_safety()


def at(n: float, e: float) -> tuple[float, float]:
    return offset(HOME[0], HOME[1], n, e)


def wp(n: float, e: float, alt: float = 40, **extra) -> dict:
    lat, lon = at(n, e)
    return {"command": "NAV_WAYPOINT", "lat": lat, "lon": lon, "alt_m": alt, **extra}


def good_mission() -> dict:
    return {
        "name": "north field survey",
        "items": [
            {"command": "NAV_TAKEOFF", "alt_m": 40},
            {"command": "DO_CHANGE_SPEED", "speed_mps": 6},
            wp(200, -100),
            wp(200, 100),
            wp(300, 100, hold_s=2),
            {"command": "DO_DIGICAM_CONTROL"},
            {"command": "NAV_LOITER_TIME", **{k: v for k, v in wp(300, -100).items() if k != "command"}, "time_s": 20},
            {"command": "NAV_RETURN_TO_LAUNCH"},
        ],
    }


VEHICLE = VehicleContext(home=HOME, battery_remaining_pct=95, vehicle_type="copter")


def run(mission, vehicle=VEHICLE, limits=LIMITS):
    return validate_mission(mission, limits, vehicle)


def failed(result) -> set[str]:
    return {c.name for c in result.checks if not c.ok}


def test_good_mission_passes():
    r = run(good_mission())
    assert r.ok, [c for c in r.checks if not c.ok]
    assert r.estimates["flight_time_s"] > 0
    assert r.estimates["total_distance_m"] > 600
    assert len(r.items) == len(good_mission()["items"]) + 1  # + home at seq 0
    assert r.items[0].seq == 0 and r.items[0].lat == HOME[0]
    assert r.items[1].command_name == "NAV_TAKEOFF" and r.items[1].alt == 40


def mutate(fn):
    m = good_mission()
    fn(m)
    return m


REJECTIONS = {
    # schema
    "not an object": ("[]", "schema"),
    "missing items": ({"name": "x"}, "schema"),
    "empty items": ({"name": "x", "items": []}, "schema"),
    "unknown command": (mutate(lambda m: m["items"].insert(1, {"command": "DO_FLIGHTTERMINATION"})), "schema"),
    "waypoint without alt": (mutate(lambda m: m["items"][2].pop("alt_m")), "schema"),
    "extra field": (mutate(lambda m: m["items"][2].update(evil=True)), "schema"),
    "latitude out of range": (mutate(lambda m: m["items"][2].update(lat=123.0)), "schema"),
    "string altitude": (mutate(lambda m: m["items"][2].update(alt_m="40")), "schema"),
    "servo pwm out of range": (
        mutate(lambda m: m["items"].insert(1, {"command": "DO_SET_SERVO", "servo": 9, "pwm": 3000})),
        "schema",
    ),
    "negative loiter time": (mutate(lambda m: m["items"][6].update(time_s=-5)), "schema"),
    "zero speed": (mutate(lambda m: m["items"][1].update(speed_mps=0)), "schema"),
    "land with lat only": (
        mutate(lambda m: m["items"].__setitem__(-1, {"command": "NAV_LAND", "lat": HOME[0]})),
        "schema",
    ),
    # structure
    "no takeoff": (mutate(lambda m: m["items"].pop(0)), "structure"),
    "no return or land": (mutate(lambda m: m["items"].pop()), "structure"),
    "nav after rtl": (mutate(lambda m: m["items"].append(wp(10, 10))), "structure"),
    "two takeoffs": (mutate(lambda m: m["items"].insert(3, {"command": "NAV_TAKEOFF", "alt_m": 30})), "structure"),
    # altitude
    "too high": (mutate(lambda m: m["items"][3].update(alt_m=150)), "altitude_limits"),
    "too low": (mutate(lambda m: m["items"][3].update(alt_m=2)), "altitude_limits"),
    "takeoff too high": (mutate(lambda m: m["items"][0].update(alt_m=500)), "altitude_limits"),
    # geofence
    "waypoint outside fence": (mutate(lambda m: m["items"].insert(3, wp(1200, 0))), "geofence"),
    "land outside fence": (
        mutate(
            lambda m: m["items"].__setitem__(
                -1, {"command": "NAV_LAND", "lat": at(-1000, 0)[0], "lon": at(-1000, 0)[1]}
            )
        ),
        "geofence",
    ),
    # distance and legs
    "too far from home": (mutate(lambda m: m["items"].insert(3, wp(600, 600))), "max_distance_from_home"),
    "leg too long": (mutate(lambda m: m["items"].insert(3, wp(-500, 0))), "max_leg_length"),
    # speed / servo
    "too fast": (mutate(lambda m: m["items"][1].update(speed_mps=25)), "speed_limit"),
    "servo channel not allowed": (
        mutate(lambda m: m["items"].insert(1, {"command": "DO_SET_SERVO", "servo": 3, "pwm": 1500})),
        "servo_channels",
    ),
    # flight time vs battery
    "long loiter drains battery": (mutate(lambda m: m["items"][6].update(time_s=900)), "battery"),
}


@pytest.mark.parametrize("case", sorted(REJECTIONS))
def test_rejections(case):
    mission, check = REJECTIONS[case]
    r = run(mission)
    assert not r.ok
    assert check in failed(r), f"{case}: failed checks {failed(r)}"


def test_whitelist_from_config_is_enforced():
    limits = copy.deepcopy(LIMITS)
    limits["command_whitelist"].remove("DO_DIGICAM_CONTROL")
    r = run(good_mission(), limits=limits)
    assert "command_whitelist" in failed(r)


def test_too_many_items():
    limits = copy.deepcopy(LIMITS)
    limits["max_items"] = 4
    assert "item_count" in failed(run(good_mission(), limits=limits))


def test_unknown_home_is_rejected():
    r = run(good_mission(), vehicle=VehicleContext(home=None, battery_remaining_pct=90))
    assert "home_known" in failed(r)


def test_unknown_battery_is_rejected():
    r = run(good_mission(), vehicle=VehicleContext(home=HOME, battery_remaining_pct=None))
    assert "battery" in failed(r)


def test_low_battery_is_rejected():
    r = run(good_mission(), vehicle=VehicleContext(home=HOME, battery_remaining_pct=30))
    assert "battery" in failed(r)


def test_leg_crossing_outside_fence_is_rejected():
    limits = copy.deepcopy(LIMITS)
    # A U-shaped fence: both waypoints inside, the straight leg between them crosses the notch.
    a, b, c, d = at(-400, -400), at(400, -400), at(400, 400), at(-400, 400)
    notch = [at(400, -50), at(100, -50), at(100, 50), at(400, 50)]
    limits["geofence"]["polygon"] = [list(a), list(b), *[list(p) for p in notch], list(c), list(d)]
    mission = {
        "name": "notch",
        "items": [
            {"command": "NAV_TAKEOFF", "alt_m": 30},
            wp(-200, -200, 30),
            wp(200, -200, 30),
            wp(200, 200, 30),
            {"command": "NAV_LAND", "lat": at(-200, 200)[0], "lon": at(-200, 200)[1]},
        ],
    }
    r = run(mission, limits=limits)
    assert "geofence" in failed(r)
    assert "legs leave" in next(c.message for c in r.checks if c.name == "geofence")


def test_validator_is_deterministic():
    a = run(good_mission()).to_dict()
    b = run(good_mission()).to_dict()
    assert a == b


def test_readback_diff_detects_changes():
    r = run(good_mission())
    same = [MissionItem(**{k: getattr(i, k) for k in MissionItem.__slots__}) for i in r.items]
    assert diff_missions(r.items, same) == []
    moved = [MissionItem(**{k: getattr(i, k) for k in MissionItem.__slots__}) for i in r.items]
    moved[3].lat += 0.001
    moved[4].alt = 55
    diffs = diff_missions(r.items, moved)
    assert any("item 3: position" in d for d in diffs)
    assert any("item 4: altitude" in d for d in diffs)
    assert diff_missions(r.items, r.items[:-1])[0].startswith("item count")
