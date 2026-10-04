"""The Claude call. Streams text deltas and returns the final message for the tool loop."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

from anthropic import AsyncAnthropic

from .config import AgentConfig
from .keys import find_api_key

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM(Protocol):
    def stream(
        self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield ("text", str) deltas, optionally ("retry", reason), then exactly one ("message", final)."""
        ...


class AnthropicLLM:
    def __init__(self, cfg: AgentConfig, client: AsyncAnthropic | None = None) -> None:
        self.cfg = cfg
        key = find_api_key()
        # With no key here the SDK still resolves ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile.
        self.client = client or (AsyncAnthropic(api_key=key) if key else AsyncAnthropic())

    async def stream(
        self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> AsyncIterator[tuple[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "system": system,
            "tools": tools,
            "messages": messages,
            "cache_control": {"type": "ephemeral"},
        }
        if self.cfg.effort:
            kwargs["output_config"] = {"effort": self.cfg.effort}
        betas: list[str] = []
        if self.cfg.fallbacks == "default":
            betas.append(FALLBACK_BETA)
            kwargs["fallbacks"] = "default"
        for attempt in range(3):
            try:
                async with self.client.beta.messages.stream(**kwargs, betas=betas) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield "text", event.text
                    final = await stream.get_final_message()
                yield "message", final
                return
            except ValueError as exc:
                # Eager tool-input streaming produced JSON the SDK could not parse. No tool_use id
                # exists to answer, so re-issue the turn (bounded). API errors are not ValueError.
                if attempt == 2:
                    raise
                log.warning("unparseable tool input, retrying turn: %s", exc)
                yield "retry", str(exc)
