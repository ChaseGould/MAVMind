"""The vehicle-command MCP server. Off by default; enabled per session from the UI.

Its only tool is propose_mission. Proposing never uploads: a human approves in the UI,
which calls the vehicle service's REST API directly. There is no approve tool.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from ..audit import AuditLog
from ..validator import mission_schema

INSTRUCTIONS = (
    "Propose missions for human review. A proposal is validated by deterministic code and shown to the "
    "operator, who approves or rejects it. You cannot approve, upload, arm, or change modes."
)


def _description() -> str:
    schema = mission_schema()
    return (
        "Propose a mission for the operator to review. It is validated against safety limits "
        "(command whitelist, altitude, geofence, distance from home, leg length, flight time vs battery) "
        "and drawn on the operator's map. Nothing is uploaded unless the operator clicks Approve.\n"
        "If validation fails, read the failed checks, fix the mission, and propose again.\n"
        "Altitudes are metres relative to home. Do not include home; it is added automatically.\n"
        "Mission JSON schema:\n" + json.dumps(schema["$defs"], separators=(",", ":"))
    )


def build_command_server(ctx: Any, audit: AuditLog | None = None) -> MCPServer:
    mcp = MCPServer("mavmind-vehicle-command", instructions=INSTRUCTIONS)

    @mcp.tool(
        description=_description(),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
    )
    def propose_mission(
        name: Annotated[str, Field(description="Short mission name")],
        items: Annotated[list[dict[str, Any]], Field(description="Mission items per the schema, in order")],
        description: Annotated[str, Field(description="What the mission does and why")] = "",
    ) -> dict:
        if not ctx.command_enabled:
            if audit is not None:
                audit.write("propose_refused", reason="command server disabled")
            return {
                "accepted": False,
                "reason": "The command server is disabled. The operator must enable Commands in the UI first.",
            }
        mission: dict[str, Any] = {"name": name, "items": items}
        if description:
            mission["description"] = description
        p = ctx.proposals.propose(mission, origin="llm")
        failures = p.validation.failures()
        return {
            "accepted": True,
            "proposal_id": p.id,
            "status": p.status,
            "valid": p.validation.ok,
            "failed_checks": [{"name": c.name, "message": c.message} for c in failures],
            "estimates": p.validation.estimates,
            "proposal": p.to_dict(),
            "next_step": (
                "Shown to the operator for approval. Do not claim it was uploaded."
                if p.validation.ok
                else "Validation failed. Fix the failed checks and call propose_mission again."
            ),
        }

    return mcp
