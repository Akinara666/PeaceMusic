from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import PlaybackError, ValidationError
from peacemusic.modules.music.models import PlaybackStatus, ResolvedMedia
from peacemusic.modules.music.permissions import (
    AllowAllPermissionService,
    MusicRequestContext,
)
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.recovery import PlaybackRecoveryService
from peacemusic.modules.music.service import MusicService
from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)
from peacemusic.modules.settings.service import GuildSettingsService


class Resolver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def resolve(self, query: str) -> ResolvedMedia:
        self.calls.append(query)
        return ResolvedMedia(title=query, source_url=f"https://example.test/{query}")


class AudioFactory:
    async def create(self, track, *, start_seconds: int = 0):
        suffix = f"@{start_seconds}" if start_seconds else ""
        return f"source:{track.title}{suffix}"


class FlakyAudioFactory(AudioFactory):
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts = 0

    async def create(self, track, *, start_seconds: int = 0):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise RuntimeError("temporary source failure")
        return await super().create(track, start_seconds=start_seconds)


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


def test_music_service_restarts_voice_source_when_seeking() -> None:
    async def scenario() -> None:
        voice = VoiceGateway()
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
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
        assert await service.seek(context, 15) == 15

        assert voice.played == [(1, "source:one"), (1, "source:one@15")]
        assert voice.actions == ["stop"]

    asyncio.run(scenario())


def test_music_service_retries_source_creation_with_bounded_recovery() -> None:
    async def scenario() -> None:
        voice = VoiceGateway()
        audio = FlakyAudioFactory(failures=1)
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            AllowAllPermissionService(),
            voice_gateway=voice,
            audio_source_factory=audio,
            recovery=PlaybackRecoveryService(max_attempts=2, retry_delay_seconds=0),
        )
        context = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
        )

        await service.play(context, "recoverable")

        assert audio.attempts == 2
        assert voice.played == [(1, "source:recoverable")]

    asyncio.run(scenario())


def test_music_service_marks_player_failed_after_recovery_exhaustion() -> None:
    async def scenario() -> None:
        audio = FlakyAudioFactory(failures=3)
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            AllowAllPermissionService(),
            voice_gateway=VoiceGateway(),
            audio_source_factory=audio,
            recovery=PlaybackRecoveryService(max_attempts=2, retry_delay_seconds=0),
        )
        context = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
        )

        with pytest.raises(PlaybackError):
            await service.play(context, "failed")

        assert (await service.player_state(1)).status is PlaybackStatus.FAILED
        assert audio.attempts == 2

    asyncio.run(scenario())


def test_music_service_disconnects_after_idle_timeout() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        await settings.update(
            1,
            actor_user_id=2,
            section="voice",
            values={"idle_disconnect_timeout": 0},
        )
        voice = VoiceGateway()
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            AllowAllPermissionService(),
            voice_gateway=voice,
            audio_source_factory=AudioFactory(),
            settings=settings,
        )
        context = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
        )

        await service.play(context, "idle")
        voice.callbacks[0](None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert voice.actions[-2:] == ["stop", "disconnect"]
        assert (await service.player_state(1)).status is PlaybackStatus.DISCONNECTED
        await service.shutdown()

    asyncio.run(scenario())


def test_music_service_preserves_voice_connection_in_247_mode() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        await settings.update(
            1,
            actor_user_id=2,
            section="voice",
            values={"idle_disconnect_timeout": 0, "mode_24_7": True},
        )
        voice = VoiceGateway()
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            AllowAllPermissionService(),
            voice_gateway=voice,
            audio_source_factory=AudioFactory(),
            settings=settings,
        )
        context = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
        )

        await service.play(context, "always-on")
        voice.callbacks[0](None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert voice.actions == []
        assert (await service.player_state(1)).status is PlaybackStatus.IDLE
        await service.shutdown()

    asyncio.run(scenario())
