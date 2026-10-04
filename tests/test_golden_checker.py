"""The golden checker itself: realistic answers pass, wrong ones fail."""

from golden import check, load_questions

Q = {q["id"]: q for q in load_questions()}


def result(answer, tools=()):
    return {"answer": answer, "tools": list(tools), "errors": []}


def test_why_rtl():
    good = (
        "It switched AUTO -> RTL because of a low-battery failsafe: the pack sagged to 10.48 V, below "
        "BATT_LOW_VOLT (10.5 V), and BATT_FS_LOW_ACT = 2 (RTL)."
    )
    assert check(Q["why_rtl"], result(good, ["get_events", "get_params"])) == []
    assert check(Q["why_rtl"], result("The pilot switched it.", ["get_events"]))
    assert check(Q["why_rtl"], result(good, []))  # must have looked at events


def test_numbers():
    assert check(Q["attitude_rate"], result("ATTITUDE is arriving at 9.8 Hz.")) == []
    assert check(Q["attitude_rate"], result("About 4 Hz."))
    assert check(Q["packet_loss"], result("Yes, about 1.0 % loss.", ["get_link_health"])) == []
    assert check(Q["packet_loss"], result("No loss at 0 %.", ["get_link_health"]))
    assert check(Q["flight_duration"], result("Armed for 149 s (about 2.5 min).")) == []
    assert check(Q["failsafe_voltage_vs_threshold"], result("10.48 V; threshold 10.5 V.")) == []


def test_unanswerable_must_say_so():
    assert check(Q["unanswerable_airspeed_temp"], result("That data is not available on this link.")) == []
    assert check(Q["unanswerable_airspeed_temp"], result("It is 35 C."))
