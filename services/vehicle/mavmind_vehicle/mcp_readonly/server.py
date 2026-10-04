"""The read-only vehicle MCP server (streamable HTTP). It has no way to move the aircraft."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from ..audit import AuditLog
from . import tools

INSTRUCTIONS = (
    "Read-only access to a MAVLink vehicle's live telemetry, mission, messages, parameters and events. "
    "Every response includes source, timestamp, age_s and rate_hz; quote data age when answering. "
    "available:false means the data is missing - say so rather than guessing."
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def build_readonly_server(ctx: Any, audit: AuditLog | None = None) -> MCPServer:
    mcp = MCPServer("mavmind-vehicle-readonly", instructions=INSTRUCTIONS)

    def logged(name: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if audit is not None:
            audit.write("mcp_readonly_call", tool=name, args=args, available=result.get("available"))
        return result

    @mcp.tool(annotations=READ_ONLY)
    def get_vehicle_state() -> dict:
        """Current vehicle state: flight mode, armed, position (lat/lon, MSL and relative altitude), attitude,
        speeds, battery, GPS fix and satellites, EKF health, flight time. Each block has its own age_s."""
        return logged("get_vehicle_state", {}, tools.get_vehicle_state(ctx))

    @mcp.tool(annotations=READ_ONLY)
    async def get_mission() -> dict:
        """Mission items on the vehicle (item 0 is home), current item, progress, and distance to the
        current item and along the remaining path."""
        return logged("get_mission", {}, await tools.get_mission(ctx))

    @mcp.tool(annotations=READ_ONLY)
    def list_messages() -> dict:
        """Every MAVLink message type received on this link, with its rate (Hz), age (s) and count.
        Use this to learn what data the current stream rates can answer."""
        return logged("list_messages", {}, tools.list_messages(ctx))

    @mcp.tool(annotations=READ_ONLY)
    def get_message(
        name: Annotated[str, Field(description="MAVLink message name, e.g. VFR_HUD or BATTERY_STATUS")],
    ) -> dict:
        """Latest instance of one MAVLink message type with all fields (scaled integers converted,
        units in field names)."""
        return logged("get_message", {"name": name}, tools.get_message(ctx, name))

    @mcp.tool(annotations=READ_ONLY)
    def get_message_history(
        name: Annotated[str, Field(description="MAVLink message name")],
        fields: Annotated[
            list[str] | None, Field(description="Fields to return (raw or unit-suffixed names); default all numeric")
        ] = None,
        window_s: Annotated[float, Field(description="How far back to look, seconds", gt=0, le=3600)] = 60.0,
        max_points: Annotated[int, Field(description="Cap on returned points", ge=1, le=1000)] = 200,
    ) -> dict:
        """One message's fields over a time window, downsampled to max_points. t_rel_s is seconds
        relative to now (negative = past). For statistics use analyze_field instead of reading arrays."""
        args = {"name": name, "fields": fields, "window_s": window_s, "max_points": max_points}
        return logged("get_message_history", args, tools.get_message_history(ctx, name, fields, window_s, max_points))

    @mcp.tool(annotations=READ_ONLY)
    def analyze_field(
        message: Annotated[str, Field(description="MAVLink message name, e.g. SYS_STATUS")],
        field: Annotated[str, Field(description="Field name, raw or unit-suffixed, e.g. voltage_battery_v")],
        window_s: Annotated[float, Field(description="Window in seconds", gt=0, le=3600)] = 300.0,
        threshold: Annotated[
            float | None, Field(description="Optional threshold; returns crossings and time below it")
        ] = None,
    ) -> dict:
        """Min, max, mean, std, trend (linear fit), and threshold crossings for one field over a window.
        Computed in code - use this rather than computing statistics yourself."""
        args = {"message": message, "field": field, "window_s": window_s, "threshold": threshold}
        return logged("analyze_field", args, tools.analyze_field(ctx, message, field, window_s, threshold))

    @mcp.tool(annotations=READ_ONLY)
    def get_statustext(
        since_seconds_ago: Annotated[float, Field(description="Look-back window, seconds", gt=0)] = 600.0,
        min_severity: Annotated[
            str | None, Field(description="Only this severity or worse: EMERGENCY..DEBUG, e.g. WARNING")
        ] = None,
    ) -> dict:
        """Recent STATUSTEXT messages from the autopilot with severity (prearm failures, failsafes,
        mission progress, EKF messages)."""
        args = {"since_seconds_ago": since_seconds_ago, "min_severity": min_severity}
        return logged("get_statustext", args, tools.get_statustext(ctx, since_seconds_ago, min_severity))

    @mcp.tool(annotations=READ_ONLY)
    def get_events(
        since_seconds_ago: Annotated[float, Field(description="Look-back window, seconds", gt=0)] = 600.0,
        since_timestamp: Annotated[float | None, Field(description="Unix time; overrides since_seconds_ago")] = None,
        kinds: Annotated[
            list[str] | None,
            Field(description="Filter: mode_change, armed, disarmed, statustext, failsafe, mission_progress, link"),
        ] = None,
    ) -> dict:
        """Event log: mode changes (with the failsafe that likely caused them), arm/disarm, failsafes,
        STATUSTEXT, mission progress, link loss."""
        args = {"since_seconds_ago": since_seconds_ago, "since_timestamp": since_timestamp, "kinds": kinds}
        return logged("get_events", args, tools.get_events(ctx, since_seconds_ago, since_timestamp, kinds))

    @mcp.tool(annotations=READ_ONLY)
    async def get_params(
        names: Annotated[
            list[str], Field(description="Parameter names or prefixes ending in _ (e.g. FS_, FENCE_, BATT_LOW_VOLT)")
        ],
    ) -> dict:
        """Read autopilot parameters by name or prefix. Read-only: parameters cannot be changed."""
        return logged("get_params", {"names": names}, await tools.get_params(ctx, names))

    @mcp.tool(annotations=READ_ONLY)
    def get_link_health() -> dict:
        """Link health: last heartbeat age, packet loss (recent and total), radio RSSI/noise,
        per-message rates."""
        return logged("get_link_health", {}, tools.get_link_health(ctx))

    @mcp.tool(annotations=READ_ONLY)
    def get_home() -> dict:
        """Home position and the vehicle's distance and bearing to home."""
        return logged("get_home", {}, tools.get_home(ctx))

    return mcp
