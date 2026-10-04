"""MavlinkSource: direct MAVLink over UDP/TCP/serial with pymavlink (ardupilotmega dialect).

Runs natively on Windows with no ROS. A reader thread decodes messages and hands
them to the asyncio loop; request/response protocols (mission, params, commands)
run as coroutines on the loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Callable

from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

from ..messages import MavMessage, MissionItem, UploadResult, enum_name
from .base import BaseSource, SourceError, is_prefix, match_params

log = logging.getLogger(__name__)


class MavlinkSource(BaseSource):
    source_type = "mavlink"

    def __init__(
        self,
        url: str = "udpin:0.0.0.0:14550",
        baud: int = 57600,
        source_system: int = 255,
        source_component: int = 190,
        stream_rate_hz: float | None = 10,
        message_rates: dict[str, float] | None = None,
        heartbeat_hz: float = 1.0,
        command_timeout_s: float = 3.0,
    ) -> None:
        super().__init__()
        self.url = url
        self.baud = baud
        self.source_system = source_system
        self.source_component = source_component
        self.stream_rate_hz = stream_rate_hz
        self.message_rates = message_rates or {}
        self.heartbeat_hz = heartbeat_hz
        self.command_timeout_s = command_timeout_s
        self.conn: Any = None
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._tasks: list[asyncio.Task[Any]] = []

    # ------------------------------------------------------------- lifecycle
    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        os.environ.setdefault("MAVLINK20", "1")
        self.conn = await asyncio.to_thread(
            mavutil.mavlink_connection,
            self.url,
            baud=self.baud,
            source_system=self.source_system,
            source_component=self.source_component,
            dialect="ardupilotmega",
            autoreconnect=True,
        )
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, name="mavlink-reader", daemon=True)
        self._reader.start()
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._tasks.append(asyncio.create_task(self._setup_streams()))
        self.connected = True

    async def close(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        if self._reader is not None:
            await asyncio.to_thread(self._reader.join, 2.0)
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
        await super().close()

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                m = self.conn.recv_match(blocking=True, timeout=0.5)
            except Exception as exc:  # noqa: BLE001 - serial unplugged, socket errors, ...
                log.warning("mavlink read error: %s", exc)
                time.sleep(0.5)
                continue
            if m is None or m.get_type() == "BAD_DATA":
                continue
            self._dispatch_threadsafe(MavMessage.from_pymavlink(m, time.time()))

    def _send(self, fn: Callable[[], Any]) -> None:
        with self._send_lock:
            fn()

    async def _heartbeat_loop(self) -> None:
        period = 1.0 / self.heartbeat_hz
        while True:
            try:
                self._send(
                    lambda: self.conn.mav.heartbeat_send(
                        mavlink.MAV_TYPE_GCS, mavlink.MAV_AUTOPILOT_INVALID, 0, 0, mavlink.MAV_STATE_ACTIVE
                    )
                )
            except Exception as exc:  # noqa: BLE001 - udpin has no peer until first packet
                log.debug("heartbeat send failed: %s", exc)
            await asyncio.sleep(period)

    async def _setup_streams(self) -> None:
        while not await self.wait_heartbeat(10):
            log.info("waiting for vehicle heartbeat on %s", self.url)
        ts, tc = self.target_system, self.target_component
        if self.stream_rate_hz:
            rate = int(self.stream_rate_hz)
            self._send(lambda: self.conn.mav.request_data_stream_send(ts, tc, mavlink.MAV_DATA_STREAM_ALL, rate, 1))
        for name, hz in self.message_rates.items():
            msg_id = getattr(mavlink, f"MAVLINK_MSG_ID_{name}", None)
            if msg_id is None:
                log.warning("unknown message in message_rates: %s", name)
                continue
            interval_us = -1 if hz <= 0 else int(1e6 / hz)
            self._command_long(mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, msg_id, interval_us)
        self._command_long(mavlink.MAV_CMD_REQUEST_MESSAGE, mavlink.MAVLINK_MSG_ID_HOME_POSITION)

    def _command_long(self, command: int, *params: float) -> None:
        p = list(params) + [0.0] * (7 - len(params))
        ts, tc = self.target_system, self.target_component
        self._send(lambda: self.conn.mav.command_long_send(ts, tc, command, 0, *p))

    async def _command(self, command: int, *params: float) -> tuple[bool, str]:
        try:
            ack = await self._request(
                lambda: self._command_long(command, *params),
                lambda m: m.name == "COMMAND_ACK" and m.fields.get("command") == command,
                timeout=self.command_timeout_s,
                retries=2,
            )
        except SourceError:
            return False, "no COMMAND_ACK from vehicle"
        result = ack.fields.get("result", -1)
        name = enum_name("MAV_RESULT", result, "MAV_RESULT_")
        return result == mavlink.MAV_RESULT_ACCEPTED, name

    # ---------------------------------------------------------------- params
    async def get_params(self, names: list[str]) -> dict[str, float]:
        if any(is_prefix(n) for n in names):
            await self._fetch_all_params()
        ts, tc = self.target_system, self.target_component
        for n in names:
            if is_prefix(n) or n.upper() in self.params:
                continue
            pid = n.upper()
            try:
                await self._request(
                    lambda pid=pid: self._send(lambda: self.conn.mav.param_request_read_send(ts, tc, pid.encode(), -1)),
                    lambda m, pid=pid: m.name == "PARAM_VALUE" and str(m.fields.get("param_id")) == pid,
                    timeout=1.5,
                    retries=2,
                )
            except SourceError:
                log.info("parameter %s not returned by vehicle", pid)
        return match_params(self.params, names)

    async def _fetch_all_params(self, quiet_s: float = 2.0, overall_s: float = 90.0) -> None:
        if self.param_count and len(self.params) >= self.param_count:
            return
        ts, tc = self.target_system, self.target_component
        self._send(lambda: self.conn.mav.param_request_list_send(ts, tc))
        start = last_change = time.monotonic()
        last_len = len(self.params)
        while time.monotonic() - start < overall_s:
            await asyncio.sleep(0.2)
            if self.param_count and len(self.params) >= self.param_count:
                return
            if len(self.params) != last_len:
                last_len, last_change = len(self.params), time.monotonic()
            elif time.monotonic() - last_change > quiet_s:
                return

    # --------------------------------------------------------------- mission
    async def download_mission(self) -> list[MissionItem]:
        ts, tc = self.target_system, self.target_component
        count_msg = await self._request(
            lambda: self._send(lambda: self.conn.mav.mission_request_list_send(ts, tc, 0)),
            lambda m: m.name == "MISSION_COUNT" and m.fields.get("mission_type", 0) == 0,
        )
        items: list[MissionItem] = []
        for seq in range(int(count_msg.fields["count"])):
            m = await self._request(
                lambda seq=seq: self._send(lambda: self.conn.mav.mission_request_int_send(ts, tc, seq, 0)),
                lambda m, seq=seq: (
                    m.name == "MISSION_ITEM_INT" and m.fields.get("seq") == seq and m.fields.get("mission_type", 0) == 0
                ),
            )
            items.append(MissionItem.from_fields(m.fields))
        self._send(lambda: self.conn.mav.mission_ack_send(ts, tc, mavlink.MAV_MISSION_ACCEPTED, 0))
        return items

    async def upload_mission(self, items: list[MissionItem]) -> UploadResult:
        ts, tc = self.target_system, self.target_component
        items = [_renumber(it, i) for i, it in enumerate(items)]

        def is_reply(m: MavMessage) -> bool:
            return m.fields.get("mission_type", 0) == 0 and m.name in (
                "MISSION_REQUEST_INT",
                "MISSION_REQUEST",
                "MISSION_ACK",
            )

        try:
            msg = await self._request(
                lambda: self._send(lambda: self.conn.mav.mission_count_send(ts, tc, len(items), 0)),
                is_reply,
                timeout=self.command_timeout_s,
            )
        except SourceError:
            return UploadResult(False, "vehicle did not respond to MISSION_COUNT")
        sent: set[int] = set()
        while True:
            if msg.name == "MISSION_ACK":
                result = msg.fields.get("type", -1)
                name = enum_name("MAV_MISSION_RESULT", result, "MAV_MISSION_")
                ok = result == mavlink.MAV_MISSION_ACCEPTED and len(sent) >= len(items)
                return UploadResult(ok, f"vehicle replied {name}", count=len(sent))
            seq = int(msg.fields["seq"])
            if seq >= len(items):
                return UploadResult(False, f"vehicle requested out-of-range item {seq}", count=len(sent))
            item = items[seq]
            fields = item.to_int_fields()
            try:
                msg = await self._request(
                    lambda fields=fields: self._send(
                        lambda: self.conn.mav.mission_item_int_send(ts, tc, **_item_args(fields))
                    ),
                    is_reply,
                    timeout=self.command_timeout_s,
                )
            except SourceError:
                return UploadResult(False, f"upload stalled after item {seq}", count=len(sent))
            sent.add(seq)

    # -------------------------------------------------------------- commands
    async def set_mode(self, mode: str) -> bool:
        mapping = self.mode_mapping()
        mode_id = mapping.get(mode.upper())
        if mode_id is None:
            self.last_error = f"unknown mode {mode!r} for this vehicle"
            return False
        ok, result = await self._command(
            mavlink.MAV_CMD_DO_SET_MODE, mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode_id
        )
        self.last_error = None if ok else f"mode change rejected: {result}"
        return ok

    async def arm(self, armed: bool) -> bool:
        ok, result = await self._command(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1 if armed else 0)
        self.last_error = None if ok else f"{'arm' if armed else 'disarm'} rejected: {result}"
        return ok


def _renumber(item: MissionItem, seq: int) -> MissionItem:
    item = MissionItem(**{k: getattr(item, k) for k in item.__slots__})  # type: ignore[attr-defined]
    item.seq = seq
    return item


def _item_args(f: dict[str, Any]) -> dict[str, Any]:
    keys = ("seq frame command current autocontinue param1 param2 param3 param4 x y z mission_type").split()
    return {k: f[k] for k in keys}
