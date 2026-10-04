from mavmind_vehicle.units import convert_fields, field_value


def test_global_position_int_scaled():
    out = convert_fields(
        "GLOBAL_POSITION_INT",
        {"lat": -353632620, "lon": 1491652370, "alt": 584090, "relative_alt": 30000, "vx": 800, "hdg": 9000},
    )
    assert out["lat_deg"] == -35.363262
    assert out["lon_deg"] == 149.165237
    assert out["alt_msl_m"] == 584.09
    assert out["alt_rel_m"] == 30.0
    assert out["vx_mps"] == 8.0
    assert out["heading_deg"] == 90.0


def test_invalid_sentinels_become_null():
    out = convert_fields("SYS_STATUS", {"voltage_battery": 12000, "current_battery": -1, "battery_remaining": -1})
    assert out == {"voltage_battery_v": 12.0, "current_battery_a": None, "battery_remaining_pct": None}
    cells = convert_fields("BATTERY_STATUS", {"voltages": [4100, 4090, 65535]})["voltages_v"]
    assert cells == [4.1, 4.09, None]


def test_attitude_radians_to_degrees():
    out = convert_fields("ATTITUDE", {"roll": 3.141592653589793 / 2, "pitch": 0.0})
    assert abs(out["roll_deg"] - 90.0) < 1e-6


def test_unknown_fields_pass_through():
    assert convert_fields("NOT_A_MESSAGE", {"a": 1}) == {"a": 1}


def test_field_value_accepts_raw_or_converted_names():
    f = {"voltage_battery": 11500}
    assert field_value("SYS_STATUS", f, "voltage_battery") == 11.5
    assert field_value("SYS_STATUS", f, "voltage_battery_v") == 11.5
    assert field_value("SYS_STATUS", f, "nope") is None
