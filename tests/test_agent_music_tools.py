from __future__ import annotations

import asyncio

from peacemusic.core.errors import MediaExtractionError
from peacemusic.adapters.discord.permissions import DiscordMusicPermissionService
from peacemusic.infrastructure.persistence.repositories.in_memory_dj_roles import (
    InMemoryDJRoleRepository,
)
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
        result = await registry.invoke("seek_music", context, {"seconds": 15}, settings)
        assert result.ok is True
        assert result.data["position_seconds"] == 15
        result = await registry.invoke("clear_queue", context, {}, settings)
        assert result.ok is True

    asyncio.run(scenario())


def test_music_tool_preserves_the_underlying_media_provider_reason() -> None:
    class FailingResolver:
        async def resolve(self, query: str) -> ResolvedMedia:
            provider_error = RuntimeError("HTTP 403: signature challenge failed")
            raise MediaExtractionError(
                "yt-dlp could not resolve the query"
            ) from provider_error

    async def scenario() -> None:
        service = MusicService(
            GuildPlayerManager(),
            FailingResolver(),  # type: ignore[arg-type]
            AllowAllPermissionService(),
        )
        registry = ToolRegistry(build_music_tool_specs(service))
        context = AgentRequestContext("req-1", 123, 456, 789, "User")

        result = await registry.invoke(
            "play_music",
            context,
            {"query": "blocked video"},
            GuildSettings(guild_id=123),
        )

        assert result.ok is False
        assert "yt-dlp could not resolve the query" in result.message
        assert "HTTP 403: signature challenge failed" in result.message

    asyncio.run(scenario())


def test_music_tool_returns_the_reason_for_a_missing_dj_role() -> None:
    async def scenario() -> None:
        roles = InMemoryDJRoleRepository()
        await roles.add_role(123, 10, "DJ")
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            DiscordMusicPermissionService(roles),
        )
        registry = ToolRegistry(build_music_tool_specs(service))
        context = AgentRequestContext(
            "req-1",
            123,
            456,
            789,
            "User",
            user_voice_channel_id=10,
            bot_voice_channel_id=10,
        )

        result = await registry.invoke(
            "stop_music",
            context,
            {},
            GuildSettings(guild_id=123),
        )

        assert result.ok is False
        assert result.code == "MUSIC_PERMISSION_DENIED"
        assert "requires a DJ role" in result.message
        assert result.data["reason"] == "dj_role_required"
        assert result.data["capability"] == "stop"

    asyncio.run(scenario())
