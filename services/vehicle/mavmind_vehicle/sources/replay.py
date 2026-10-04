"""ReplaySource: play a .tlog at 1x or faster. Read-only; for development and tests."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from pymavlink import mavutil

from ..messages import MavMessage, MissionItem, UploadResult
from ..paths import resolve
from .base import BaseSource, match_params

log = logging.getLogger(__name__)


def iter_tlog(path: str | Path) -> Iterator[MavMessage]:
    """Yield every decoded message in a tlog with its logged timestamp."""
    conn = mavutil.mavlink_connection(str(path), dialect="ardupilotmega", notimestamps=False)
    try:
        while True:
            m = conn.recv_match()
            if m is None:
                return
            if m.get_type() == "BAD_DATA":
                continue
            yield MavMessage.from_pymavlink(m, m._timestamp)
    finally:
        conn.close()


class ReplaySource(BaseSource):
    source_type = "replay"
    is_live = False
    read_only = True

    def __init__(self, path: str, speed: float = 1.0, loop: bool = False) -> None:
        super().__init__()
        self.path = resolve(path)
        self.speed = speed
        self.loop = loop
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._finished: asyncio.Event | None = None
        self._mission: dict[int, MissionItem] = {}
        self._mission_count: int | None = None

    async def connect(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"tlog not found: {self.path}")
        self._loop = asyncio.get_running_loop()
        self._finished = asyncio.Event()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tlog-replay", daemon=True)
        self._thread.start()
        self.connected = True

    async def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 2.0)
        await super().close()

    async def wait_finished(self, timeout: float | None = None) -> None:
        assert self._finished is not None, "connect() first"
        await asyncio.wait_for(self._finished.wait(), timeout)

    def _run(self) -> None:
        offset = 0.0
        try:
            while not self._stop.is_set():
                first_ts = last_ts = None
                wall0 = time.monotonic()
                for msg in iter_tlog(self.path):
                    if self._stop.is_set():
                        return
                    if first_ts is None:
                        first_ts = msg.timestamp
                    if self.speed > 0:
                        delay = (msg.timestamp - first_ts) / self.speed - (time.monotonic() - wall0)
                        if delay > 0 and self._stop.wait(delay):
                            return
                    last_ts = msg.timestamp
                    if offset:
                        msg = MavMessage(msg.name, msg.fields, msg.timestamp + offset, msg.sysid, msg.compid, msg.seq)
                    self._dispatch_threadsafe(msg)
                if not self.loop or first_ts is None or last_ts is None:
                    return
                offset += (last_ts - first_ts) + 1.0
        finally:
            if self._loop is not None and not self._loop.is_closed() and self._finished is not None:
                self._loop.call_soon_threadsafe(self._finished.set)

    def _dispatch(self, msg: MavMessage) -> None:
        f = msg.fields
        if msg.sysid != 255 and f.get("mission_type", 0) == 0:
            if msg.name == "MISSION_COUNT":
                self._mission_count = f.get("count")
                self._mission = {}
            elif msg.name == "MISSION_ITEM_INT":
                self._mission[int(f["seq"])] = MissionItem.from_fields(f)
        super()._dispatch(msg)

    async def get_params(self, names: list[str]) -> dict[str, float]:
        return match_params(self.params, names)

    async def download_mission(self) -> list[MissionItem]:
        return [self._mission[k] for k in sorted(self._mission)]

    async def upload_mission(self, items: list[MissionItem]) -> UploadResult:
        return UploadResult(False, "replay source is read-only")

    async def set_mode(self, mode: str) -> bool:
        self.last_error = "replay source is read-only"
        return False

    async def arm(self, armed: bool) -> bool:
        self.last_error = "replay source is read-only"
        return False
