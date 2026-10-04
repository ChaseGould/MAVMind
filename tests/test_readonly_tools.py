"""Read-only MCP tool outputs checked against the known tlog."""

import asyncio

import pytest

from conftest import Ctx, store_until
from mavmind_vehicle.mcp_readonly import tools


@pytest.fixture
def ctx(full_store):
    return Ctx(full_store)


@pytest.fixture
def midflight(tlog_messages):
    """Store at t=60 s: armed, AUTO, cruising the survey box."""
    return Ctx(store_until(tlog_messages, 60.0))


def assert_envelope(out):
    for key in ("source", "timestamp", "age_s", "rate_hz", "available"):
        assert key in out, key


def test_unavailable_before_any_data():
    from mavmind_vehicle.store import TelemetryStore

    out = tools.get_vehicle_state(Ctx(TelemetryStore(live=False)))
    assert_envelope(out)
    assert out["available"] is False and "heartbeat" in out["reason"]


def test_vehicle_state_midflight(midflight):
    out = tools.get_vehicle_state(midflight)
    assert_envelope(out)
    assert out["mode"] == "AUTO" and out["armed"] is True and out["vehicle_type"] == "copter"
    assert out["position"]["alt_rel_m"] == pytest.approx(30.0, abs=0.5)
    assert out["speeds"]["groundspeed_mps"] == pytest.approx(8.0, abs=0.5)
    assert out["gps"]["fix_name"] == "3D_FIX" and out["gps"]["satellites"] == 14
    assert out["ekf"]["ok"] is True
    assert out["battery"]["voltage_v"] < 12.0
    assert out["age_s"] < 1.5 and out["rate_hz"] == pytest.approx(1.0, rel=0.2)
    assert out["flight_time_s"] == pytest.approx(50, abs=2)


def test_vehicle_state_end_of_log(ctx, expected):
    out = tools.get_vehicle_state(ctx)
    assert out["armed"] is False
    assert out["position"]["lat"] == pytest.approx(expected["home"]["lat"], abs=1e-5)


def test_mission_progress_midflight(midflight, expected):
    out = asyncio.run(tools.get_mission(midflight))
    assert_envelope(out)
    assert out["count"] == len(expected["mission"])
    assert out["current_seq"] == 3  # takeoff done ~24 s, WP2 reached ~43 s, WP3 due ~62 s
    assert out["current_item"]["command"] == "NAV_WAYPOINT"
    assert 0 < out["distance_to_current_m"] < 160
    assert out["progress"]["nav_items_completed"] == 2
    assert out["remaining_path_m"] > out["distance_to_current_m"]


def test_list_messages_reports_every_type_with_rate(ctx, expected):
    out = tools.list_messages(ctx)
    names = {m["name"]: m for m in out["messages"]}
    for name in expected["nominal_rates_hz"]:
        assert name in names
    assert names["ATTITUDE"]["rate_hz"] == pytest.approx(10, rel=0.2)


def test_get_message_converts_units(ctx):
    out = tools.get_message(ctx, "global_position_int")
    assert out["name"] == "GLOBAL_POSITION_INT"
    assert "lat_deg" in out["fields"] and "lat" not in out["fields"]
    missing = tools.get_message(ctx, "ADSB_VEHICLE")
    assert missing["available"] is False


def test_history_is_capped(ctx):
    out = tools.get_message_history(ctx, "ATTITUDE", ["roll_deg"], window_s=600, max_points=50)
    assert out["points_returned"] == 50
    assert out["samples_in_window"] > 50
    assert out["points"][-1]["t_rel_s"] <= 0
    assert set(out["points"][0]) == {"t_rel_s", "roll_deg"}


def test_analyze_battery_voltage_finds_the_low_threshold_crossing(ctx, expected):
    out = tools.analyze_field(ctx, "SYS_STATUS", "voltage_battery_v", window_s=600, threshold=10.5)
    assert out["available"] and out["trend"] == "falling"
    assert out["min"] < 10.5 < out["max"]
    below = [c for c in out["crossings"] if c["direction"] == "below"]
    assert len(below) == 1
    t = below[0]["timestamp"] - expected["start_time"]
    assert t == pytest.approx(expected["facts"]["failsafe_t"], abs=1.0)
    assert out["std"] > 0


def test_statustext_and_events(ctx, expected):
    st = tools.get_statustext(ctx, since_seconds_ago=1000, min_severity="CRITICAL")
    assert [m["text"] for m in st["messages"]] == [s["text"] for s in expected["statustext"] if s["severity"] <= 2]
    ev = tools.get_events(ctx, since_seconds_ago=1000, kinds=["mode_change"])
    to_rtl = [e for e in ev["events"] if e["data"].get("to") == "RTL"]
    assert to_rtl and "Battery 1 is low" in to_rtl[0]["data"]["possible_cause"]


def test_params_by_prefix_with_meanings(ctx):
    out = asyncio.run(tools.get_params(ctx, ["BATT_", "FS_THR_ENABLE", "NOPE_PARAM"]))
    by = {p["name"]: p for p in out["params"]}
    assert by["BATT_LOW_VOLT"]["value"] == 10.5
    assert by["BATT_FS_LOW_ACT"]["meaning"] == "RTL"
    assert "FS_THR_ENABLE" in by
    assert out["missing"] == ["NOPE_PARAM"]


def test_link_health(ctx):
    out = tools.get_link_health(ctx)
    assert out["status"] in ("ok", "degraded")
    assert 0 < out["packet_loss_pct_total"] < 2
    assert out["radio"]["rssi"] is not None


def test_home_distance_midflight(midflight):
    out = tools.get_home(midflight)
    assert out["home"]["from"] == "HOME_POSITION"
    assert 0 < out["distance_m"] < 250
    assert 0 <= out["bearing_deg"] < 360
