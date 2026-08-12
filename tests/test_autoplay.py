from __future__ import annotations

import asyncio

from peacemusic.modules.autoplay.models import AutoplayContext, TrackCandidate
from peacemusic.modules.autoplay.service import AutoplayService
from peacemusic.modules.music.models import ResolvedMedia, Track
from peacemusic.modules.music.permissions import (
    AllowAllPermissionService,
    MusicRequestContext,
)
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.settings.models import GuildSettings


class Settings:
    def __init__(self, enabled: bool) -> None:
        self.settings = GuildSettings(
            guild_id=1,
            music={"autoplay_enabled": enabled},
        )

    async def get(self, guild_id: int) -> GuildSettings:
        return self.settings


class Provider:
    def __init__(self, candidate: TrackCandidate | None) -> None:
        self.candidate = candidate
        self.contexts: list[AutoplayContext] = []

    async def get_next(self, context: AutoplayContext) -> TrackCandidate | None:
        self.contexts.append(context)
        return self.candidate


class Resolver:
    async def resolve(self, query: str) -> ResolvedMedia:
        return ResolvedMedia(
            title=query,
            source_url=f"https://example.test/{query}",
            stream_url=f"https://cdn.example.test/{query}",
        )


class Voice:
    def __init__(self) -> None:
        self.callbacks = []
        self.played: list[object] = []

    async def connect(self, guild_id: int, channel_id: int) -> None:
        pass

    async def disconnect(self, guild_id: int) -> None:
        pass

    async def play(self, guild_id: int, source: object, *, after=None) -> None:
        self.played.append(source)
        self.callbacks.append(after)

    async def pause(self, guild_id: int) -> None:
        pass

    async def resume(self, guild_id: int) -> None:
        pass

    async def stop(self, guild_id: int) -> None:
        pass

    async def set_volume(self, guild_id: int, volume: int) -> None:
        pass


class Audio:
    async def create(self, track: Track) -> object:
        return f"source:{track.title}"


def test_autoplay_honors_guild_setting_and_preserves_requester() -> None:
    async def scenario() -> None:
        previous = Track(
            title="Previous",
            source_url="https://example.test/previous",
            requested_by=42,
        )
        provider = Provider(
            TrackCandidate("Recommended", "https://example.test/recommended")
        )
        service = AutoplayService(provider, Settings(True))  # type: ignore[arg-type]

        track = await service.next(1, previous)

        assert track is not None
        assert track.title == "Recommended"
        assert track.requested_by == 42
        assert provider.contexts[0].previous_track == previous

    asyncio.run(scenario())


def test_autoplay_does_not_call_provider_when_disabled() -> None:
    async def scenario() -> None:
        provider = Provider(TrackCandidate("Unused", "https://example.test/unused"))
        service = AutoplayService(provider, Settings(False))  # type: ignore[arg-type]

        assert await service.next(1, Track("Previous", "url", 42)) is None
        assert provider.contexts == []

    asyncio.run(scenario())


def test_music_service_requests_autoplay_when_queue_finishes() -> None:
    async def scenario() -> None:
        provider = Provider(
            TrackCandidate("Recommended", "https://example.test/recommended")
        )
        autoplay = AutoplayService(provider, Settings(True))  # type: ignore[arg-type]
        voice = Voice()
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            AllowAllPermissionService(),
            voice_gateway=voice,
            audio_source_factory=Audio(),
            autoplay=autoplay,
        )
        context = MusicRequestContext(
            guild_id=1,
            user_id=42,
            user_voice_channel_id=7,
        )

        await service.play(context, "Previous")
        voice.callbacks[0](None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert voice.played == ["source:Previous", "source:Recommended"]

    asyncio.run(scenario())
