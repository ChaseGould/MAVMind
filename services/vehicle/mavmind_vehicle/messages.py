"""Source-independent message and mission types."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pymavlink.dialects.v20 import ardupilotmega as mavlink


@dataclass(frozen=True, slots=True)
class MavMessage:
    """One decoded MAVLink message, always in standard MAVLink names and fields."""

    name: str
    fields: dict[str, Any]
    timestamp: float
    sysid: int
    compid: int
    seq: int | None = None

    @classmethod
    def from_pymavlink(cls, msg: Any, timestamp: float | None = None) -> MavMessage:
        fields = {}
        for key in msg.get_fieldnames():
            fields[key] = _plain(getattr(msg, key))
        ts = timestamp if timestamp is not None else getattr(msg, "_timestamp", None) or time.time()
        try:
            seq = msg.get_seq()
        except Exception:  # noqa: BLE001 - some synthetic messages have no header
            seq = None
        return cls(msg.get_type(), fields, float(ts), msg.get_srcSystem(), msg.get_srcComponent(), seq)


def _plain(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            return list(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def enum_name(enum: str, value: int, strip: str = "") -> str:
    entry = mavlink.enums.get(enum, {}).get(value)
    if entry is None:
        return str(value)
    name = entry.name
    return name[len(strip) :] if strip and name.startswith(strip) else name


def enum_value(enum: str, name: str, prefix: str = "") -> int | None:
    full = name if name.startswith(prefix) else prefix + name
    for value, entry in mavlink.enums.get(enum, {}).items():
        if entry.name == full:
            return value
    return None


def command_name(cmd: int) -> str:
    return enum_name("MAV_CMD", cmd, "MAV_CMD_")


def command_id(name: str) -> int | None:
    return enum_value("MAV_CMD", name, "MAV_CMD_")


def frame_name(frame: int) -> str:
    return enum_name("MAV_FRAME", frame, "MAV_FRAME_")


NAV_COMMANDS_WITH_POSITION = {
    mavlink.MAV_CMD_NAV_WAYPOINT,
    mavlink.MAV_CMD_NAV_LOITER_TIME,
    mavlink.MAV_CMD_NAV_LOITER_UNLIM,
    mavlink.MAV_CMD_NAV_LOITER_TURNS,
    mavlink.MAV_CMD_NAV_LAND,
    mavlink.MAV_CMD_NAV_TAKEOFF,
    mavlink.MAV_CMD_NAV_SPLINE_WAYPOINT,
}


# Frames whose x/y are latitude/longitude. Other frames (MAV_FRAME_MISSION) carry raw param5/param6.
GLOBAL_FRAMES = {0, 3, 5, 6, 10, 11}


@dataclass(slots=True)
class MissionItem:
    """A MAVLink mission item (MISSION_ITEM_INT semantics).

    lat/lon are degrees for global frames; for MAV_FRAME_MISSION items they hold raw param5/param6.
    """

    seq: int
    command: int
    frame: int = mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT
    param1: float = 0.0
    param2: float = 0.0
    param3: float = 0.0
    param4: float = 0.0
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 0.0
    autocontinue: int = 1
    current: int = 0
    mission_type: int = mavlink.MAV_MISSION_TYPE_MISSION

    @property
    def command_name(self) -> str:
        return command_name(self.command)

    @property
    def has_position(self) -> bool:
        return self.command in NAV_COMMANDS_WITH_POSITION and not (self.lat == 0 and self.lon == 0)

    def to_api(self) -> dict[str, Any]:
        pos = self.has_position
        return {
            "seq": self.seq,
            "command": self.command_name,
            "frame": frame_name(self.frame),
            "params": [self.param1, self.param2, self.param3, self.param4],
            "lat": self.lat if pos else None,
            "lon": self.lon if pos else None,
            "alt_m": self.alt if self.command in NAV_COMMANDS_WITH_POSITION else None,
        }

    @classmethod
    def from_fields(cls, f: dict[str, Any], is_int: bool = True) -> MissionItem:
        scale = 1e-7 if is_int and int(f["frame"]) in GLOBAL_FRAMES else 1.0
        return cls(
            seq=int(f["seq"]),
            command=int(f["command"]),
            frame=int(f["frame"]),
            param1=float(f["param1"]),
            param2=float(f["param2"]),
            param3=float(f["param3"]),
            param4=float(f["param4"]),
            lat=float(f["x"]) * scale,
            lon=float(f["y"]) * scale,
            alt=float(f["z"]),
            autocontinue=int(f.get("autocontinue", 1)),
            current=int(f.get("current", 0)),
            mission_type=int(f.get("mission_type", 0)),
        )

    def to_int_fields(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "frame": self.frame,
            "command": self.command,
            "current": self.current,
            "autocontinue": self.autocontinue,
            "param1": self.param1,
            "param2": self.param2,
            "param3": self.param3,
            "param4": self.param4,
            "x": int(round(self.lat * 1e7)) if self.frame in GLOBAL_FRAMES else int(round(self.lat)),
            "y": int(round(self.lon * 1e7)) if self.frame in GLOBAL_FRAMES else int(round(self.lon)),
            "z": float(self.alt),
            "mission_type": self.mission_type,
        }


@dataclass(slots=True)
class UploadResult:
    ok: bool
    message: str
    count: int = 0
    details: dict[str, Any] = field(default_factory=dict)
