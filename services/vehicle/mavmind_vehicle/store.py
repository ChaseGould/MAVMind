"""TelemetryStore: latest message per type, rolling history, events, rates, link health.

Everything is keyed by standard MAVLink message names so it works the same for
every TelemetrySource. Time is the source clock: wall time for live links, log
time for replays (so "age" and "rate" stay meaningful when replaying fast).
"""

from __future__ import annotations

import bisect
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

from .messages import MavMessage, MissionItem, enum_name

SEVERITIES = ["EMERGENCY", "ALERT", "CRITICAL", "ERROR", "WARNING", "NOTICE", "INFO", "DEBUG"]

FAILSAFE_PATTERNS = re.compile(
    r"failsafe|battery \d* ?is (low|critical)|low battery|battery (low|critical)|"
    r"fence breach|ekf ?\w* ?(failsafe|variance)|gps glitch|radio failsafe|"
    r"gcs failsafe|crash|potential thrust loss|vibration",
    re.IGNORECASE,
)

COPTER_TYPES = {2, 3, 4, 13, 14, 15, 29, 35}
PLANE_TYPES = {1, 16, 19, 20, 21, 22, 23, 24, 25, 28}
VEHICLE_TYPE_NAMES = {10: "rover", 11: "boat", 12: "sub", 7: "airship", 9: "rocket"}

BATTERY_STATES = {2: "LOW", 3: "CRITICAL", 4: "EMERGENCY", 5: "FAILED", 6: "UNHEALTHY"}


def vehicle_type_name(mav_type: int | None) -> str | None:
    if mav_type is None:
        return None
    if mav_type in COPTER_TYPES:
        return "copter"
    if mav_type in PLANE_TYPES:
        return "plane"
    return VEHICLE_TYPE_NAMES.get(mav_type, enum_name("MAV_TYPE", mav_type, "MAV_TYPE_").lower())


def mode_name(mav_type: int, autopilot: int, base_mode: int, custom_mode: int) -> str:
    if autopilot == mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
        mapping = mavutil.mode_mapping_bynumber(mav_type)
        if mapping and custom_mode in mapping:
            return mapping[custom_mode]
    if autopilot == mavlink.MAV_AUTOPILOT_PX4:
        return mavutil.interpret_px4_mode(base_mode, custom_mode)
    return f"Mode({custom_mode})"


@dataclass(slots=True)
class Event:
    timestamp: float
    kind: str
    message: str
    severity: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _LinkStats:
    received: int = 0
    lost: int = 0
    last_seq: int | None = None
    # (timestamp, received, lost) samples for a windowed loss figure
    samples: deque = field(default_factory=lambda: deque(maxlen=600))


class TelemetryStore:
    def __init__(
        self,
        history_s: float = 600.0,
        history_max_hz: float = 2.0,
        rate_window_s: float = 5.0,
        max_events: int = 2000,
        max_statustext: int = 500,
        live: bool = True,
    ) -> None:
        self.history_s = history_s
        self.history_min_dt = 1.0 / history_max_hz if history_max_hz > 0 else 0.0
        self.rate_window_s = rate_window_s
        self.long_rate_window_s = max(30.0, rate_window_s)
        self.live = live
        self._lock = threading.RLock()
        self._latest: dict[str, MavMessage] = {}
        self._history: dict[str, deque[MavMessage]] = {}
        self._recent_ts: dict[str, deque[float]] = {}
        self._counts: dict[str, int] = {}
        self._first_seen: dict[str, float] = {}
        self._events: deque[Event] = deque(maxlen=max_events)
        self._statustext: deque[Event] = deque(maxlen=max_statustext)
        self._params: dict[str, float] = {}
        self._param_count: int | None = None
        self._mission: list[MissionItem] = []
        self._mission_rx: dict[int, MissionItem] = {}
        self._mission_rx_count: int | None = None
        self._non_vehicle_components: set[tuple[int, int]] = set()
        self._link: dict[tuple[int, int], _LinkStats] = {}
        self._last_ts: float = 0.0
        self.vehicle_sysid: int | None = None
        self.vehicle_compid: int | None = None
        self.mav_type: int | None = None
        self.autopilot: int | None = None
        self.mode: str | None = None
        self.armed: bool | None = None
        self.armed_since: float | None = None
        self.last_flight_time_s: float | None = None
        self.mission_current_seq: int | None = None
        self._battery_state: int | None = None
        self._link_lost = False
        self._msg_listeners: list[Callable[[MavMessage], None]] = []
        self._event_listeners: list[Callable[[Event], None]] = []
        self._mission_listeners: list[Callable[[list[MissionItem]], None]] = []

    # ------------------------------------------------------------------ clock
    def now(self) -> float:
        if self.live:
            return time.time()
        return self._last_ts

    # -------------------------------------------------------------- listeners
    def add_message_listener(self, cb: Callable[[MavMessage], None]) -> None:
        self._msg_listeners.append(cb)

    def add_event_listener(self, cb: Callable[[Event], None]) -> None:
        self._event_listeners.append(cb)

    def add_mission_listener(self, cb: Callable[[list[MissionItem]], None]) -> None:
        self._mission_listeners.append(cb)

    # ----------------------------------------------------------------- ingest
    def ingest(self, msg: MavMessage) -> None:
        if msg.name == "BAD_DATA":
            return
        with self._lock:
            if not self._accept(msg):
                return
            ts = msg.timestamp
            if ts > self._last_ts:
                self._last_ts = ts
            name = msg.name
            self._latest[name] = msg
            self._counts[name] = self._counts.get(name, 0) + 1
            self._first_seen.setdefault(name, ts)
            recent = self._recent_ts.setdefault(name, deque())
            recent.append(ts)
            while recent and recent[0] < ts - self.long_rate_window_s:
                recent.popleft()
            hist = self._history.setdefault(name, deque())
            if not hist or ts - hist[-1].timestamp >= self.history_min_dt:
                hist.append(msg)
            while hist and hist[0].timestamp < ts - self.history_s:
                hist.popleft()
            self._track_link(msg)
            self._derive(msg)
        for cb in list(self._msg_listeners):
            cb(msg)

    def _accept(self, msg: MavMessage) -> bool:
        """Drop traffic from GCSs and other non-autopilot components (Mission Planner, MAVROS)."""
        key = (msg.sysid, msg.compid)
        if msg.name == "HEARTBEAT":
            f = msg.fields
            if f.get("autopilot") == mavlink.MAV_AUTOPILOT_INVALID or f.get("type") == mavlink.MAV_TYPE_GCS:
                self._non_vehicle_components.add(key)
                return False
            if self.vehicle_sysid is None:
                self.vehicle_sysid, self.vehicle_compid = msg.sysid, msg.compid
            return msg.sysid == self.vehicle_sysid
        if key in self._non_vehicle_components or msg.sysid == 255:
            return False
        if self.vehicle_sysid is not None and msg.sysid != self.vehicle_sysid:
            return False
        return True

    def _track_link(self, msg: MavMessage) -> None:
        if msg.seq is None:
            return
        key = (msg.sysid, msg.compid)
        st = self._link.setdefault(key, _LinkStats())
        if st.last_seq is not None:
            gap = (msg.seq - st.last_seq) % 256
            if gap == 0:
                return  # duplicate
            if gap < 128:
                st.lost += gap - 1
        st.last_seq = msg.seq
        st.received += 1
        if not st.samples or msg.timestamp - st.samples[-1][0] >= 1.0:
            st.samples.append((msg.timestamp, st.received, st.lost))

    def _emit(self, event: Event) -> None:
        self._events.append(event)
        for cb in list(self._event_listeners):
            cb(event)

    def _derive(self, msg: MavMessage) -> None:
        f = msg.fields
        ts = msg.timestamp
        name = msg.name
        if name == "HEARTBEAT":
            self.mav_type = f["type"]
            self.autopilot = f["autopilot"]
            mode = mode_name(f["type"], f["autopilot"], f["base_mode"], f["custom_mode"])
            armed = bool(f["base_mode"] & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            if self.mode is not None and mode != self.mode:
                data: dict[str, Any] = {"from": self.mode, "to": mode}
                cause = self._recent_cause(ts)
                if cause:
                    data["possible_cause"] = cause.message
                    data["possible_cause_time"] = cause.timestamp
                msg_text = f"Mode changed {self.mode} -> {mode}"
                if cause:
                    msg_text += f" ({cause.message.strip()} {ts - cause.timestamp:.1f}s earlier)"
                self._emit(Event(ts, "mode_change", msg_text, data=data))
            self.mode = mode
            if self.armed is not None and armed != self.armed:
                if armed:
                    self.armed_since = ts
                    self._emit(Event(ts, "armed", "Vehicle armed", data={"mode": mode}))
                else:
                    if self.armed_since is not None:
                        self.last_flight_time_s = ts - self.armed_since
                    self.armed_since = None
                    self._emit(Event(ts, "disarmed", "Vehicle disarmed", data={"mode": mode}))
            elif self.armed is None and armed:
                self.armed_since = ts
            self.armed = armed
            if self._link_lost:
                self._link_lost = False
                self._emit(Event(ts, "link", "Heartbeat regained"))
        elif name == "STATUSTEXT":
            sev = f.get("severity", 6)
            sev_name = SEVERITIES[sev] if 0 <= sev < len(SEVERITIES) else str(sev)
            text = str(f.get("text", "")).strip()
            ev = Event(ts, "statustext", text, severity=sev_name)
            self._statustext.append(ev)
            self._emit(ev)
            if FAILSAFE_PATTERNS.search(text):
                self._emit(Event(ts, "failsafe", text, severity=sev_name, data={"source": "STATUSTEXT"}))
        elif name == "BATTERY_STATUS":
            state = f.get("charge_state")
            if state is not None and state != self._battery_state:
                if state in BATTERY_STATES and (self._battery_state or 0) < state:
                    self._emit(
                        Event(
                            ts,
                            "failsafe",
                            f"Battery {f.get('id', 0) + 1} charge state {BATTERY_STATES[state]}",
                            severity="CRITICAL" if state >= 3 else "WARNING",
                            data={"source": "BATTERY_STATUS", "charge_state": state},
                        )
                    )
                self._battery_state = state
        elif name == "MISSION_CURRENT":
            seq = f.get("seq")
            if seq != self.mission_current_seq:
                if self.mission_current_seq is not None:
                    self._emit(Event(ts, "mission_progress", f"Mission current item {seq}", data={"seq": seq}))
                self.mission_current_seq = seq
        elif name == "MISSION_ITEM_REACHED":
            self._emit(Event(ts, "mission_progress", f"Reached mission item {f.get('seq')}", data=dict(f)))
        elif name == "PARAM_VALUE":
            pid = str(f.get("param_id", "")).strip("\x00")
            self._params[pid] = float(f.get("param_value", 0.0))
            self._param_count = f.get("param_count")
        elif name == "MISSION_COUNT" and f.get("mission_type", 0) == 0:
            self._mission_rx = {}
            self._mission_rx_count = f.get("count")
            if self._mission_rx_count == 0:
                self.set_mission([])
        elif name in ("MISSION_ITEM_INT", "MISSION_ITEM") and f.get("mission_type", 0) == 0:
            if self._mission_rx_count is not None:
                item = MissionItem.from_fields(f, is_int=name == "MISSION_ITEM_INT")
                self._mission_rx[item.seq] = item
                if len(self._mission_rx) >= self._mission_rx_count:
                    items = [self._mission_rx[i] for i in sorted(self._mission_rx)]
                    self._mission_rx_count = None
                    self.set_mission(items)

    def _recent_cause(self, ts: float, window_s: float = 10.0) -> Event | None:
        for ev in reversed(self._events):
            if ts - ev.timestamp > window_s:
                break
            if ev.kind == "failsafe":
                return ev
        return None

    def check_link(self, timeout_s: float = 3.0) -> None:
        """Emit a link event when heartbeats stop. Call periodically on live links."""
        hb = self._latest.get("HEARTBEAT")
        if hb is None or self._link_lost:
            return
        now = self.now()
        if now - hb.timestamp > timeout_s:
            self._link_lost = True
            self._emit(Event(now, "link", f"No heartbeat for {now - hb.timestamp:.1f}s"))

    # ---------------------------------------------------------------- mission
    def set_mission(self, items: list[MissionItem]) -> None:
        with self._lock:
            self._mission = list(items)
        for cb in list(self._mission_listeners):
            cb(self._mission)

    def mission(self) -> list[MissionItem]:
        with self._lock:
            return list(self._mission)

    # ----------------------------------------------------------------- params
    def params(self) -> dict[str, float]:
        with self._lock:
            return dict(self._params)

    @property
    def param_count(self) -> int | None:
        return self._param_count

    # ---------------------------------------------------------------- queries
    def latest(self, name: str) -> MavMessage | None:
        return self._latest.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._latest)

    def count(self, name: str) -> int:
        return self._counts.get(name, 0)

    def age(self, name: str) -> float | None:
        msg = self._latest.get(name)
        return None if msg is None else max(0.0, self.now() - msg.timestamp)

    def rate(self, name: str) -> float:
        """Messages per second, ending at the store clock.

        Uses the short rate window when it holds enough samples and falls back to a
        longer window for slow messages (HOME_POSITION every 10 s). Stale streams
        decay towards zero instead of reporting their last rate forever.
        """
        with self._lock:
            recent = self._recent_ts.get(name)
            if not recent:
                return 0.0
            now = self.now()
            for window in (self.rate_window_s, self.long_rate_window_s):
                n = len(recent) - bisect.bisect_right(recent, now - window)
                if n >= 3 or (window == self.long_rate_window_s and n >= 2):
                    span = recent[-1] - recent[-n]
                    if span <= 0:
                        return 0.0
                    r = (n - 1) / span
                    age = now - recent[-1]
                    if age > 2.0 / r and age > 1.0:
                        return n / window
                    return r
            return 0.0

    def history(self, name: str, since: float | None = None, until: float | None = None) -> list[MavMessage]:
        with self._lock:
            hist = list(self._history.get(name, ()))
        if since is not None:
            hist = [m for m in hist if m.timestamp >= since]
        if until is not None:
            hist = [m for m in hist if m.timestamp <= until]
        return hist

    def events(self, since: float | None = None, kinds: set[str] | None = None) -> list[Event]:
        with self._lock:
            evs = list(self._events)
        return [e for e in evs if (since is None or e.timestamp >= since) and (not kinds or e.kind in kinds)]

    def statustext(self, since: float | None = None) -> list[Event]:
        with self._lock:
            evs = list(self._statustext)
        return [e for e in evs if since is None or e.timestamp >= since]

    def link_stats(self, window_s: float = 30.0) -> dict[str, Any]:
        with self._lock:
            key = (self.vehicle_sysid, self.vehicle_compid)
            st = self._link.get(key)  # type: ignore[arg-type]
            if st is None:
                return {"received": 0, "lost": 0, "packet_loss_pct": None, "window_packet_loss_pct": None}
            total = st.received + st.lost
            loss = 100.0 * st.lost / total if total else None
            win_loss = None
            now = self.now()
            old = next((s for s in st.samples if s[0] >= now - window_s), None)
            if old is not None:
                d_rx = st.received - old[1]
                d_lost = st.lost - old[2]
                if d_rx + d_lost > 0:
                    win_loss = 100.0 * d_lost / (d_rx + d_lost)
            return {
                "received": st.received,
                "lost": st.lost,
                "packet_loss_pct": loss,
                "window_packet_loss_pct": win_loss,
            }

    def flight_time_s(self) -> float | None:
        if self.armed and self.armed_since is not None:
            return max(0.0, self.now() - self.armed_since)
        return self.last_flight_time_s

    @property
    def vehicle_type(self) -> str | None:
        return vehicle_type_name(self.mav_type)

    def reset(self) -> None:
        """Forget everything (used when switching profile)."""
        listeners = (self._msg_listeners, self._event_listeners, self._mission_listeners)
        self.__init__(  # type: ignore[misc]
            history_s=self.history_s,
            history_max_hz=1.0 / self.history_min_dt if self.history_min_dt else 0.0,
            rate_window_s=self.rate_window_s,
            max_events=self._events.maxlen or 2000,
            max_statustext=self._statustext.maxlen or 500,
            live=self.live,
        )
        self._msg_listeners, self._event_listeners, self._mission_listeners = listeners
