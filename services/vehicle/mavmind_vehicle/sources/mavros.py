"""MavrosSource: ROS 2 + MAVROS via rclpy.

Telemetry comes from MAVROS's raw MAVLink passthrough topic (mavros_msgs/Mavlink), which we
re-frame and decode with pymavlink, so message names and fields match MavlinkSource exactly.
Mission push/pull, parameters, arming and mode use MAVROS services.

rclpy and mavros_msgs come from the ROS 2 installation (e.g. `apt install ros-humble-mavros`),
not from PyPI, so they are imported lazily. Verify the raw topic name for the installed MAVROS
version with `ros2 topic list | grep mavlink` (MAVROS 2 default: /uas1/mavlink_source).
"""

from __future__ import annotations

import asyncio
import logging
import struct
import threading
import time
from typing import Any

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from ..messages import MavMessage, MissionItem, UploadResult
from .base import BaseSource, is_prefix, match_params

log = logging.getLogger(__name__)

MAGIC_V1 = 0xFE
MAGIC_V2 = 0xFD


def frame_bytes(msg: Any) -> bytes:
    """Rebuild the on-wire MAVLink frame from a mavros_msgs/Mavlink message."""
    length = int(msg.len)
    payload = b"".join(struct.pack("<Q", int(w)) for w in msg.payload64)[:length]
    payload = payload.ljust(length, b"\x00")
    if int(msg.magic) == MAGIC_V2:
        msgid = int(msg.msgid)
        header = struct.pack(
            "<BBBBBBBHB",
            MAGIC_V2,
            length,
            int(msg.incompat_flags),
            int(msg.compat_flags),
            int(msg.seq),
            int(msg.sysid),
            int(msg.compid),
            msgid & 0xFFFF,
            msgid >> 16,
        )
        sig = bytes(msg.signature) if int(msg.incompat_flags) & 0x01 else b""
        return header + payload + struct.pack("<H", int(msg.checksum)) + sig
    header = struct.pack("<BBBBBB", MAGIC_V1, length, int(msg.seq), int(msg.sysid), int(msg.compid), int(msg.msgid))
    return header + payload + struct.pack("<H", int(msg.checksum))


class RawDecoder:
    """Decode mavros_msgs/Mavlink into pymavlink messages."""

    def __init__(self) -> None:
        self.mav = mavlink.MAVLink(None)
        self.mav.robust_parsing = True

    def decode(self, msg: Any, timestamp: float | None = None) -> MavMessage | None:
        try:
            parsed = self.mav.parse_buffer(frame_bytes(msg))
        except mavlink.MAVError as exc:
            log.debug("could not decode raw MAVLink: %s", exc)
            return None
        for m in parsed or []:
            if m.get_type() != "BAD_DATA":
                return MavMessage.from_pymavlink(m, timestamp if timestamp is not None else time.time())
        return None


class MavrosSource(BaseSource):
    source_type = "mavros"

    def __init__(
        self,
        namespace: str = "/mavros",
        raw_topic: str = "/uas1/mavlink_source",
        node_name: str = "mavmind_vehicle",
        service_timeout_s: float = 10.0,
    ) -> None:
        super().__init__()
        self.ns = namespace.rstrip("/")
        self.raw_topic = raw_topic
        self.node_name = node_name
        self.service_timeout_s = service_timeout_s
        self.decoder = RawDecoder()
        self._node: Any = None
        self._executor: Any = None
        self._spin_thread: threading.Thread | None = None
        self._clients: dict[str, Any] = {}
        self._srv: dict[str, Any] = {}
        self._mission: dict[int, MissionItem] = {}
        self._mission_count: int | None = None
        self._mission_event = asyncio.Event()

    async def connect(self) -> None:
        try:
            import rclpy
            from mavros_msgs import srv
            from mavros_msgs.msg import Mavlink
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        except ImportError as exc:  # pragma: no cover - depends on a ROS install
            raise RuntimeError(
                "MAVROS profile needs ROS 2 with rclpy and mavros_msgs; source /opt/ros/<distro>/setup.bash first"
            ) from exc
        self._loop = asyncio.get_running_loop()
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node(self.node_name)
        # Best effort matches both best-effort and reliable publishers.
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=200)
        self._node.create_subscription(Mavlink, self.raw_topic, self._on_raw, qos)
        self._srv = {
            "pull": srv.WaypointPull,
            "push": srv.WaypointPush,
            "arming": srv.CommandBool,
            "set_mode": srv.SetMode,
            "param_pull": srv.ParamPull,
        }
        names = {
            "pull": f"{self.ns}/mission/pull",
            "push": f"{self.ns}/mission/push",
            "arming": f"{self.ns}/cmd/arming",
            "set_mode": f"{self.ns}/set_mode",
            "param_pull": f"{self.ns}/param/pull",
        }
        self._clients = {k: self._node.create_client(self._srv[k], name) for k, name in names.items()}
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(target=self._executor.spin, name="ros-spin", daemon=True)
        self._spin_thread.start()
        self.connected = True

    async def close(self) -> None:  # pragma: no cover - needs ROS
        if self._executor is not None:
            self._executor.shutdown()
        if self._node is not None:
            self._node.destroy_node()
        await super().close()

    def _on_raw(self, raw: Any) -> None:
        msg = self.decoder.decode(raw)
        if msg is not None:
            self._dispatch_threadsafe(msg)

    def _dispatch(self, msg: MavMessage) -> None:
        f = msg.fields
        if msg.sysid == self.target_system and f.get("mission_type", 0) == 0:
            if msg.name == "MISSION_COUNT":
                self._mission_count = f.get("count")
                self._mission = {}
            elif msg.name == "MISSION_ITEM_INT":
                self._mission[int(f["seq"])] = MissionItem.from_fields(f)
                if self._mission_count is not None and len(self._mission) >= self._mission_count:
                    self._mission_event.set()
        super()._dispatch(msg)

    async def _call(self, key: str, request: Any) -> Any:
        client = self._clients[key]
        deadline = time.monotonic() + self.service_timeout_s
        while not client.service_is_ready():
            if time.monotonic() > deadline:
                raise RuntimeError(f"MAVROS service {client.srv_name} not available")
            await asyncio.sleep(0.1)
        fut = client.call_async(request)
        while not fut.done():
            if time.monotonic() > deadline + self.service_timeout_s:
                raise RuntimeError(f"MAVROS service {client.srv_name} timed out")
            await asyncio.sleep(0.05)
        return fut.result()

    # ----------------------------------------------------------------- params
    async def get_params(self, names: list[str]) -> dict[str, float]:
        missing = any(is_prefix(n) for n in names) or any(n.upper() not in self.params for n in names)
        if missing and not (self.param_count and len(self.params) >= self.param_count):
            req = self._srv["param_pull"].Request()
            req.force_pull = False
            await self._call("param_pull", req)
            # PARAM_VALUEs from the pull arrive on the raw topic and fill self.params.
            for _ in range(50):
                if self.param_count and len(self.params) >= self.param_count:
                    break
                await asyncio.sleep(0.1)
        return match_params(self.params, names)

    # ---------------------------------------------------------------- mission
    async def download_mission(self) -> list[MissionItem]:
        self._mission_event.clear()
        resp = await self._call("pull", self._srv["pull"].Request())
        if not resp.success:
            raise RuntimeError("MAVROS mission pull failed")
        if resp.wp_received == 0:
            return []
        await asyncio.wait_for(self._mission_event.wait(), 5.0)
        return [self._mission[k] for k in sorted(self._mission)]

    async def upload_mission(self, items: list[MissionItem]) -> UploadResult:
        from mavros_msgs.msg import Waypoint

        req = self._srv["push"].Request()
        req.start_index = 0
        wps = []
        for i, it in enumerate(items):
            wp = Waypoint()
            wp.frame = it.frame
            wp.command = it.command
            wp.is_current = i == 0
            wp.autocontinue = bool(it.autocontinue)
            wp.param1, wp.param2, wp.param3, wp.param4 = (
                float(it.param1),
                float(it.param2),
                float(it.param3),
                float(it.param4),
            )
            wp.x_lat, wp.y_long, wp.z_alt = float(it.lat), float(it.lon), float(it.alt)
            wps.append(wp)
        req.waypoints = wps
        try:
            resp = await self._call("push", req)
        except RuntimeError as exc:
            return UploadResult(False, str(exc))
        ok = bool(resp.success) and int(resp.wp_transfered) == len(items)
        return UploadResult(
            ok, f"MAVROS push transferred {resp.wp_transfered}/{len(items)}", count=int(resp.wp_transfered)
        )

    # --------------------------------------------------------------- commands
    async def set_mode(self, mode: str) -> bool:
        mode_id = self.mode_mapping().get(mode.upper())
        req = self._srv["set_mode"].Request()
        req.base_mode = 0
        req.custom_mode = mode.upper()
        try:
            resp = await self._call("set_mode", req)
        except RuntimeError as exc:
            self.last_error = str(exc)
            return False
        if not resp.mode_sent:
            self.last_error = "MAVROS did not send the mode change"
            return False
        if mode_id is None:
            return True
        fut = self._waiter(
            lambda m: m.name == "HEARTBEAT" and m.sysid == self.target_system and m.fields.get("custom_mode") == mode_id
        )
        try:
            await asyncio.wait_for(fut, 3.0)
            self.last_error = None
            return True
        except asyncio.TimeoutError:
            self.last_error = f"vehicle did not switch to {mode.upper()}"
            return False

    async def arm(self, armed: bool) -> bool:
        req = self._srv["arming"].Request()
        req.value = armed
        try:
            resp = await self._call("arming", req)
        except RuntimeError as exc:
            self.last_error = str(exc)
            return False
        self.last_error = None if resp.success else f"{'arm' if armed else 'disarm'} rejected (result {resp.result})"
        return bool(resp.success)
