from __future__ import annotations

import asyncio

from peacemusic.infrastructure.persistence.repositories.in_memory_memory import (
    InMemoryMemoryRepository,
)
from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.memory_tools import build_memory_tool_specs
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.memory.service import MemoryService
from peacemusic.modules.settings.models import GuildSettings
from peacemusic.modules.settings.service import GuildSettingsService


def test_memory_tools_use_memory_service_and_return_safe_results() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        memory = MemoryService(InMemoryMemoryRepository(), settings_service=settings)
        registry = ToolRegistry(build_memory_tool_specs(memory))
        context = AgentRequestContext("req", 1, 2, 3, "User")
        guild_settings = GuildSettings(guild_id=1)

        saved = await registry.invoke(
            "remember",
            context,
            {"content": "User likes ambient music"},
            guild_settings,
        )
        assert saved.ok is True

        recalled = await registry.invoke(
            "recall",
            context,
            {"query": "ambient"},
            guild_settings,
        )
        assert recalled.ok is True
        assert len(recalled.data["memories"]) == 1

        forgotten = await registry.invoke(
            "forget",
            context,
            {"memory_id": saved.data["memory_id"]},
            guild_settings,
        )
        assert forgotten.data["deleted"] == 1

    asyncio.run(scenario())
