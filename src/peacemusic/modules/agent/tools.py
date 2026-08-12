"""Dynamic, policy-aware tool registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.results import ToolResult
from peacemusic.modules.settings.models import GuildSettings


class ToolCategory(StrEnum):
    MUSIC = "music"
    MEMORY = "memory"
    DISCORD = "discord"


ToolHandler = Callable[..., Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    category: ToolCategory
    handler: ToolHandler


class ToolRegistry:
    """Expose only tools enabled by the effective guild configuration."""

    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def available(self, settings: GuildSettings) -> tuple[ToolSpec, ...]:
        enabled = {
            ToolCategory.MUSIC: settings.ai.music_tools_enabled,
            ToolCategory.MEMORY: settings.ai.memory_tools_enabled,
            ToolCategory.DISCORD: settings.ai.discord_tools_enabled,
        }
        return tuple(spec for spec in self._specs.values() if enabled[spec.category])

    async def invoke(
        self,
        name: str,
        context: AgentRequestContext,
        arguments: dict[str, Any],
        settings: GuildSettings,
    ) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult.failure("TOOL_NOT_FOUND", f"Unknown tool: {name}")
        if spec not in self.available(settings):
            return ToolResult.failure("TOOL_DISABLED", f"Tool is disabled: {name}")
        try:
            return await spec.handler(context, **arguments)
        except TypeError as exc:
            return ToolResult.failure("INVALID_TOOL_ARGUMENTS", str(exc))
