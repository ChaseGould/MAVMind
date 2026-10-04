import pytest

from conftest import store_until


def test_every_message_type_in_the_log_is_listed(full_store, expected):
    vehicle_types = set(expected["message_counts"]) - {"MISSION_REQUEST_LIST", "MISSION_REQUEST_INT", "MISSION_ACK"}
    assert set(full_store.names()) == vehicle_types


def test_counts_match_log_and_gcs_traffic_is_filtered(full_store, expected):
    # The log interleaves a GCS heartbeat (sysid 255); only the vehicle's are counted.
    assert full_store.count("HEARTBEAT") == expected["message_counts"]["HEARTBEAT"] // 2
    for name in ("ATTITUDE", "GLOBAL_POSITION_INT", "SYS_STATUS", "STATUSTEXT"):
        assert full_store.count(name) == expected["message_counts"][name]


@pytest.mark.parametrize("t_rel", [40.0, 100.0, 150.0])
def test_replay_rates_match_nominal(tlog_messages, expected, t_rel):
    store = store_until(tlog_messages, t_rel)
    for name, nominal in expected["nominal_rates_hz"].items():
        rate = store.rate(name)
        tolerance = 0.25 if nominal >= 1 else 0.5
        assert rate == pytest.approx(nominal, rel=tolerance), f"{name}: {rate} vs {nominal}"


def test_rate_decays_when_stream_stops(tlog_messages):
    store = store_until(tlog_messages)
    assert store.rate("PARAM_VALUE") == 0.0  # burst at t=1s, long gone


def test_events_tell_the_failsafe_story(full_store, expected):
    facts = expected["facts"]
    kinds = [(e.kind, e.message) for e in full_store.events()]
    assert ("armed", "Vehicle armed") in kinds
    failsafes = full_store.events(kinds={"failsafe"})
    assert any(f"{facts['failsafe_voltage_v']:.2f}V" in e.message for e in failsafes)
    rtl = [e for e in full_store.events(kinds={"mode_change"}) if e.data.get("to") == "RTL"]
    assert len(rtl) == 1
    assert rtl[0].data["from"] == "AUTO"
    assert "Battery 1 is low" in rtl[0].data["possible_cause"]
    assert rtl[0].timestamp - expected["start_time"] == pytest.approx(facts["failsafe_t"], abs=1.5)


def test_link_loss_from_sequence_gaps(full_store, expected):
    stats = full_store.link_stats()
    assert stats["lost"] == pytest.approx(expected["dropped_vehicle_packets"], abs=3)
    assert 0.5 < stats["packet_loss_pct"] < 2.0


def test_mission_and_params_captured_passively(full_store, expected):
    mission = full_store.mission()
    assert len(mission) == len(expected["mission"])
    assert mission[0].lat == pytest.approx(expected["home"]["lat"], abs=1e-7)
    assert full_store.params()["BATT_LOW_VOLT"] == pytest.approx(10.5)
    assert len(full_store.params()) == len(expected["params"])


def test_flight_time_and_state(full_store, expected):
    assert full_store.vehicle_type == "copter"
    assert full_store.armed is False
    facts = expected["facts"]
    assert full_store.flight_time_s() == pytest.approx(facts["disarm_t"] - facts["arm_t"], abs=1.5)


def test_history_is_downsampled_and_bounded(full_store):
    hist = full_store.history("ATTITUDE")
    assert 0 < len(hist) <= full_store.count("ATTITUDE")
    gaps = [b.timestamp - a.timestamp for a, b in zip(hist, hist[1:])]
    assert min(gaps) >= full_store.history_min_dt - 1e-6
