from __future__ import annotations

import asyncio

from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.music_tools import build_music_tool_specs
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.music.models import ResolvedMedia
from peacemusic.modules.music.permissions import AllowAllPermissionService
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.settings.models import GuildSettings


class Resolver:
    async def resolve(self, query: str) -> ResolvedMedia:
        return ResolvedMedia(title=query, source_url=f"https://example.test/{query}")


def test_music_tools_use_music_service_and_expose_no_reasoning_tool() -> None:
    async def scenario() -> None:
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            AllowAllPermissionService(),
        )
        registry = ToolRegistry(build_music_tool_specs(service))
        context = AgentRequestContext(
            "req-1", 123, 456, 789, "User", user_voice_channel_id=10
        )
        settings = GuildSettings(guild_id=123)

        names = {spec.name for spec in registry.available(settings)}
        assert "play_music" in names
        assert "think" not in names

        result = await registry.invoke(
            "play_music", context, {"query": "Muse"}, settings
        )
        assert result.ok is True
        assert result.data["title"] == "Muse"

        result = await registry.invoke("set_volume", context, {"value": 101}, settings)
        assert result.ok is False
        assert result.code == "INVALID_TOOL_ARGUMENTS"

        await service.play(context, "queued")
        result = await registry.invoke("clear_queue", context, {}, settings)
        assert result.ok is True

    asyncio.run(scenario())
