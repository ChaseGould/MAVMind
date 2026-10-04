"""MAVMind agent service: runs the Claude tool-use loop against the vehicle MCP servers.

The agent only ever sees the two MCP servers. It has no route to approve, upload, arm, or
change modes; those go from the UI straight to the vehicle service.
"""

__version__ = "0.1.0"
