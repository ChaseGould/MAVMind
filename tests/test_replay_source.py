import pytest

from conftest import TLOG
from mavmind_vehicle.sources.replay import ReplaySource
from mavmind_vehicle.store import TelemetryStore


async def test_replay_fast_feeds_store_and_is_read_only(expected):
    source = ReplaySource(str(TLOG), speed=0)
    store = TelemetryStore(live=False)
    source.on_message(store.ingest)
    await source.connect()
    await source.wait_finished(30)
    assert store.count("ATTITUDE") == expected["message_counts"]["ATTITUDE"]
    assert len(await source.download_mission()) == len(expected["mission"])
    assert (await source.get_params(["BATT_LOW_VOLT"])) == {"BATT_LOW_VOLT": 10.5}
    assert not (await source.upload_mission([])).ok
    assert not await source.arm(True) and "read-only" in source.last_error
    assert not await source.set_mode("RTL")
    await source.close()


async def test_replay_loop_keeps_time_moving(expected):
    source = ReplaySource(str(TLOG), speed=0, loop=True)
    seen = []
    source.on_message(lambda m: seen.append(m.timestamp) if m.name == "HEARTBEAT" else None)
    await source.connect()
    import asyncio

    while len(seen) < expected["message_counts"]["HEARTBEAT"] + 10:
        await asyncio.sleep(0.05)
    await source.close()
    hb = sorted(seen)
    assert hb[-1] - hb[0] > expected["duration_s"]


async def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        await ReplaySource("tests/tlogs/nope.tlog").connect()
