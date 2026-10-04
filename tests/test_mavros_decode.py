"""MavrosSource re-frames mavros_msgs/Mavlink and decodes it with pymavlink (no ROS needed here)."""

import struct
from types import SimpleNamespace

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from mavmind_vehicle.sources.mavros import RawDecoder


def as_ros_msg(packed: bytes) -> SimpleNamespace:
    """Build what MAVROS publishes on /uas1/mavlink_source from an on-wire frame."""
    if packed[0] == 0xFD:
        length, incompat, compat, seq, sysid, compid = packed[1:7]
        msgid = packed[7] | packed[8] << 8 | packed[9] << 16
        payload = packed[10 : 10 + length]
    else:
        length, seq, sysid, compid, msgid = packed[1:6]
        incompat = compat = 0
        payload = packed[6 : 6 + length]
    checksum = (
        struct.unpack("<H", packed[-2:])[0]
        if packed[0] == 0xFE
        else struct.unpack("<H", packed[10 + length : 12 + length])[0]
    )
    padded = payload + b"\x00" * (-len(payload) % 8)
    payload64 = [struct.unpack("<Q", padded[i : i + 8])[0] for i in range(0, len(padded), 8)]
    return SimpleNamespace(
        framing_status=1,
        magic=packed[0],
        len=length,
        incompat_flags=incompat,
        compat_flags=compat,
        seq=seq,
        sysid=sysid,
        compid=compid,
        msgid=msgid,
        checksum=checksum,
        payload64=payload64,
        signature=[],
    )


def test_v2_round_trip_matches_pymavlink_names():
    mav = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    packed = mavlink.MAVLink_vfr_hud_message(12.5, 11.0, 270, 55, 612.3, -0.5).pack(mav)
    msg = RawDecoder().decode(as_ros_msg(packed), timestamp=1.0)
    assert msg.name == "VFR_HUD" and msg.sysid == 1 and msg.compid == 1
    assert msg.fields["heading"] == 270 and abs(msg.fields["groundspeed"] - 11.0) < 1e-6


def test_v2_truncated_payload_and_strings():
    mav = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    packed = mavlink.MAVLink_statustext_message(2, b"Battery 1 is low 10.48V", 0, 0).pack(mav)
    msg = RawDecoder().decode(as_ros_msg(packed))
    assert msg.name == "STATUSTEXT" and msg.fields["text"] == "Battery 1 is low 10.48V"


def test_v1_frame():
    mav = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    mav.WIRE_PROTOCOL_VERSION = "1.0"
    packed = mavlink.MAVLink_heartbeat_message(2, 3, 209, 5, 4, 3).pack(mav, force_mavlink1=True)
    assert packed[0] == 0xFE
    msg = RawDecoder().decode(as_ros_msg(packed))
    assert msg.name == "HEARTBEAT" and msg.fields["custom_mode"] == 5


def test_bad_checksum_is_dropped():
    mav = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    raw = as_ros_msg(mavlink.MAVLink_vfr_hud_message(1, 1, 1, 1, 1, 1).pack(mav))
    raw.checksum ^= 0xFFFF
    assert RawDecoder().decode(raw) is None
