from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import ValidationError
from peacemusic.modules.music.models import ResolvedMedia
from peacemusic.modules.music.permissions import (
    AllowAllPermissionService,
    MusicRequestContext,
)
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService


class Resolver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def resolve(self, query: str) -> ResolvedMedia:
        self.calls.append(query)
        return ResolvedMedia(title=query, source_url=f"https://example.test/{query}")


class AudioFactory:
    async def create(self, track):
        return f"source:{track.title}"


class VoiceGateway:
    def __init__(self) -> None:
        self.connected: list[tuple[int, int]] = []
        self.played: list[tuple[int, object]] = []
        self.callbacks = []
        self.actions: list[str] = []

    async def connect(self, guild_id: int, channel_id: int) -> None:
        self.connected.append((guild_id, channel_id))

    async def play(self, guild_id: int, source: object, *, after=None) -> None:
        self.played.append((guild_id, source))
        self.callbacks.append(after)

    async def pause(self, guild_id: int) -> None:
        self.actions.append("pause")

    async def resume(self, guild_id: int) -> None:
        self.actions.append("resume")

    async def stop(self, guild_id: int) -> None:
        self.actions.append("stop")

    async def set_volume(self, guild_id: int, volume: int) -> None:
        self.actions.append(f"volume:{volume}")

    async def disconnect(self, guild_id: int) -> None:
        self.actions.append("disconnect")


def test_music_service_starts_voice_playback_and_advances_after_callback() -> None:
    async def scenario() -> None:
        resolver = Resolver()
        voice = VoiceGateway()
        service = MusicService(
            GuildPlayerManager(),
            resolver,
            AllowAllPermissionService(),
            voice_gateway=voice,
            audio_source_factory=AudioFactory(),
        )
        context = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
        )

        await service.play(context, "one")
        await service.play(context, "two")
        assert voice.connected == [(1, 3), (1, 3)]
        assert voice.played == [(1, "source:one")]

        voice.callbacks[0](None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert voice.played == [(1, "source:one"), (1, "source:two")]

        await service.pause(context)
        await service.resume(context)
        await service.set_volume(context, 55)
        assert voice.actions[-3:] == ["pause", "resume", "volume:55"]

    asyncio.run(scenario())


def test_voice_play_requires_voice_before_media_resolution() -> None:
    async def scenario() -> None:
        resolver = Resolver()
        service = MusicService(
            GuildPlayerManager(),
            resolver,
            AllowAllPermissionService(),
            voice_gateway=VoiceGateway(),
            audio_source_factory=AudioFactory(),
        )
        context = MusicRequestContext(guild_id=1, user_id=2)

        with pytest.raises(ValidationError, match="voice channel"):
            await service.play(context, "one")
        assert resolver.calls == []

    asyncio.run(scenario())
