"""Shared music application operations used by all adapters."""

from __future__ import annotations

from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.modules.music.models import LoopMode, ResolvedMedia, Track
from peacemusic.modules.music.permissions import (
    MusicCapability,
    MusicRequestContext,
    PermissionService,
)
from peacemusic.modules.music.player import GuildPlayer
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.ports import MediaResolver


class MusicService:
    """Application boundary for slash commands, UI, and future agent tools."""

    def __init__(
        self,
        player_manager: GuildPlayerManager,
        resolver: MediaResolver,
        permissions: PermissionService,
    ) -> None:
        self._players = player_manager
        self._resolver = resolver
        self._permissions = permissions

    async def play(self, context: MusicRequestContext, query: str) -> Track:
        await self._require(context, MusicCapability.PLAY)
        if not query.strip():
            raise ValidationError("Music query cannot be empty")
        media = await self._resolver.resolve(query)
        track = self._track_from_media(media, requested_by=context.user_id)
        player = await self._players.get_or_create(context.guild_id)
        player.enqueue(track)
        return track

    async def pause(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.PAUSE)
        (await self._player(context.guild_id)).pause()

    async def resume(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.RESUME)
        (await self._player(context.guild_id)).resume()

    async def skip(self, context: MusicRequestContext) -> Track | None:
        await self._require(context, MusicCapability.SKIP)
        return (await self._player(context.guild_id)).skip()

    async def stop(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.STOP)
        (await self._player(context.guild_id)).stop()

    async def set_volume(self, context: MusicRequestContext, volume: int) -> int:
        await self._require(context, MusicCapability.SET_VOLUME)
        player = await self._player(context.guild_id)
        player.set_volume(volume)
        return player.volume

    async def set_loop_mode(
        self, context: MusicRequestContext, mode: LoopMode | str
    ) -> LoopMode:
        await self._require(context, MusicCapability.LOOP)
        player = await self._player(context.guild_id)
        player.set_loop_mode(mode)
        return player.queue.loop_mode

    async def queue(self, context: MusicRequestContext) -> list[Track]:
        return (await self._player(context.guild_id)).queue.list()

    async def player_state(self, guild_id: int) -> GuildPlayer:
        return await self._player(guild_id)

    async def _require(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> None:
        if not await self._permissions.allowed(context, capability):
            raise PermissionDeniedError(f"Capability denied: {capability.value}")

    async def _player(self, guild_id: int) -> GuildPlayer:
        return await self._players.get_or_create(guild_id)

    @staticmethod
    def _track_from_media(media: ResolvedMedia, *, requested_by: int) -> Track:
        return Track(
            title=media.title,
            source_url=media.source_url,
            requested_by=requested_by,
            webpage_url=media.webpage_url,
            thumbnail=media.thumbnail,
            uploader=media.uploader,
            duration=media.duration,
            stream_url=media.stream_url,
        )
