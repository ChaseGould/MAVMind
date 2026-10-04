"""scripts/tlog_to_udp.py feeds a recorded flight to a live-link profile."""

import asyncio
import socket
import subprocess
import sys
from pathlib import Path

from conftest import TLOG, free_port
from mavmind_vehicle.sources.mavlink import MavlinkSource
from mavmind_vehicle.store import TelemetryStore

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tlog_to_udp.py"


async def test_live_source_consumes_replayed_log():
    port = free_port(socket.SOCK_DGRAM)
    source = MavlinkSource(url=f"udpin:127.0.0.1:{port}", stream_rate_hz=None)
    store = TelemetryStore()
    source.on_message(store.ingest)
    await source.connect()
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), str(TLOG), "--out", f"udpout:127.0.0.1:{port}", "--speed", "40"]
    )
    try:
        for _ in range(200):
            if any(e.data.get("to") == "RTL" for e in store.events(kinds={"mode_change"})):
                break
            await asyncio.sleep(0.1)
        rtl = [e for e in store.events(kinds={"mode_change"}) if e.data.get("to") == "RTL"]
        assert rtl and "Battery 1 is low" in rtl[0].data["possible_cause"]
        assert store.count("ATTITUDE") > 1000
    finally:
        proc.kill()
        await source.close()
