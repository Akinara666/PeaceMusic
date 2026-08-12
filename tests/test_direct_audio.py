from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import ValidationError
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.graph import InputRoute
from peacemusic.modules.agent.service import AgentService
from peacemusic.modules.agent.state import AttachmentRef
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.music.models import ResolvedMedia
from peacemusic.modules.music.permissions import (
    AllowAllPermissionService,
    MusicRequestContext,
)
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.settings.service import GuildSettingsService
from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)


class Resolver:
    async def resolve(self, query: str) -> ResolvedMedia:
        return ResolvedMedia(title=query, source_url=query)


def test_music_service_accepts_only_trusted_discord_audio_urls() -> None:
    async def scenario() -> None:
        service = MusicService(
            GuildPlayerManager(), Resolver(), AllowAllPermissionService()
        )
        context = MusicRequestContext(guild_id=1, user_id=2)

        track = await service.play_direct_audio(
            context,
            title="voice.mp3",
            url="https://cdn.discordapp.com/attachments/1/2/voice.mp3",
        )
        assert track.stream_url == track.source_url
        with pytest.raises(ValidationError):
            await service.play_direct_audio(
                context, title="bad.mp3", url="https://example.test/bad.mp3"
            )

    asyncio.run(scenario())


def test_agent_service_routes_audio_attachment_without_provider_call() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        called = False

        async def direct_audio(context, attachment):
            nonlocal called
            called = True
            return type("Track", (), {"title": attachment.filename})()

        class Factory:
            def create(self, tools, *, system_prompt=None):
                raise AssertionError("AI provider must not be called")

        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=Factory(),
            coordinator=type("Coordinator", (), {})(),
            direct_audio_handler=direct_audio,
        )
        state = await service.handle(
            AgentRequestContext("req", 1, 2, 3, "User"),
            "",
            attachments=[
                AttachmentRef(
                    attachment_id="1",
                    filename="voice.mp3",
                    content_type="audio/mpeg",
                    size_bytes=4,
                    url="https://cdn.discordapp.com/voice.mp3",
                )
            ],
        )

        assert state.input_route == InputRoute.DIRECT_AUDIO
        assert state.final_response == "Queued voice.mp3"
        assert called is True

    asyncio.run(scenario())
