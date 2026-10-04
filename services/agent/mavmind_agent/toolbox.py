"""MCP client side: connect to the vehicle MCP servers and expose their tools to the LLM loop."""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import Any, Protocol

from mcp import Client

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 30_000


class Toolbox(Protocol):
    def tool_defs(self) -> list[dict[str, Any]]: ...
    async def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]: ...


class ToolboxError(RuntimeError):
    pass


class McpToolbox:
    """Holds one MCP client per server for the duration of a chat turn."""

    def __init__(self, servers: dict[str, str]) -> None:
        self.servers = servers
        self._stack = AsyncExitStack()
        self._clients: dict[str, Client] = {}
        self._tools: dict[str, tuple[str, dict[str, Any]]] = {}

    async def __aenter__(self) -> McpToolbox:
        await self._stack.__aenter__()
        try:
            for label, url in self.servers.items():
                client = Client(url)
                try:
                    await self._stack.enter_async_context(client)
                    listed = await client.list_tools()
                except Exception as exc:  # noqa: BLE001
                    raise ToolboxError(f"cannot reach the {label} MCP server at {url}: {exc}") from exc
                self._clients[label] = client
                for tool in listed.tools:
                    self._tools[tool.name] = (
                        label,
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                            "eager_input_streaming": True,
                        },
                    )
        except BaseException:
            await self._stack.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.__aexit__(*exc)

    def tool_defs(self) -> list[dict[str, Any]]:
        return [spec for _, spec in sorted(self._tools.values(), key=lambda t: t[1]["name"])]

    async def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        if name not in self._tools:
            return json.dumps({"error": f"unknown tool {name}"}), True
        label, _ = self._tools[name]
        try:
            result = await self._clients[label].call_tool(name, args)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"tool call failed: {exc}"}), True
        parts = [getattr(c, "text", "") for c in result.content if getattr(c, "type", "") == "text"]
        text = "\n".join(p for p in parts if p)
        if not text and result.structured_content is not None:
            text = json.dumps(result.structured_content)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n...[truncated]"
        return text, bool(result.is_error)
