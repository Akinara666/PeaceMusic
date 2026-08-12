"""Shared music application operations used by all adapters."""

from __future__ import annotations

import asyncio

from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.modules.music.models import (
    LoopMode,
    PlaybackStatus,
    ResolvedMedia,
    Track,
)
from peacemusic.modules.music.permissions import (
    MusicCapability,
    MusicRequestContext,
    PermissionService,
)
from peacemusic.modules.music.player import GuildPlayer
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.ports import (
    AudioSourceFactory,
    MediaResolver,
    VoiceGateway,
)


class MusicService:
    """Application boundary for slash commands, UI, and future agent tools."""

    def __init__(
        self,
        player_manager: GuildPlayerManager,
        resolver: MediaResolver,
        permissions: PermissionService,
        *,
        voice_gateway: VoiceGateway | None = None,
        audio_source_factory: AudioSourceFactory | None = None,
    ) -> None:
        self._players = player_manager
        self._resolver = resolver
        self._permissions = permissions
        self._voice_gateway = voice_gateway
        self._audio_source_factory = audio_source_factory
        self._playback_tokens: dict[int, int] = {}

    def attach_runtime(
        self,
        *,
        voice_gateway: VoiceGateway,
        audio_source_factory: AudioSourceFactory,
    ) -> None:
        """Attach Discord-owned runtime adapters after bot construction."""

        self._voice_gateway = voice_gateway
        self._audio_source_factory = audio_source_factory

    async def play(self, context: MusicRequestContext, query: str) -> Track:
        await self._require(context, MusicCapability.PLAY)
        if not query.strip():
            raise ValidationError("Music query cannot be empty")
        if self._voice_gateway is not None and context.user_voice_channel_id is None:
            raise ValidationError("User must be in a voice channel")
        media = await self._resolver.resolve(query)
        track = self._track_from_media(media, requested_by=context.user_id)
        player = await self._players.get_or_create(context.guild_id)
        was_idle = player.current_track is None
        if self._voice_gateway is not None:
            await self._voice_gateway.connect(
                context.guild_id, context.user_voice_channel_id
            )
            player.attach_voice(context.user_voice_channel_id)
        player.enqueue(track)
        if self._voice_gateway is not None and was_idle:
            await self._start_current(player)
        return track

    async def pause(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.PAUSE)
        player = await self._player(context.guild_id)
        player.pause()
        if self._voice_gateway is not None:
            await self._voice_gateway.pause(context.guild_id)

    async def resume(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.RESUME)
        player = await self._player(context.guild_id)
        player.resume()
        if self._voice_gateway is not None:
            await self._voice_gateway.resume(context.guild_id)

    async def skip(self, context: MusicRequestContext) -> Track | None:
        await self._require(context, MusicCapability.SKIP)
        player = await self._player(context.guild_id)
        if self._voice_gateway is not None:
            self._invalidate_playback(context.guild_id)
            await self._voice_gateway.stop(context.guild_id)
        next_track = player.skip()
        if self._voice_gateway is not None and next_track is not None:
            await self._start_current(player)
        return next_track

    async def stop(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.STOP)
        player = await self._player(context.guild_id)
        self._invalidate_playback(context.guild_id)
        player.stop()
        if self._voice_gateway is not None:
            await self._voice_gateway.stop(context.guild_id)

    async def set_volume(self, context: MusicRequestContext, volume: int) -> int:
        await self._require(context, MusicCapability.SET_VOLUME)
        player = await self._player(context.guild_id)
        player.set_volume(volume)
        if self._voice_gateway is not None:
            await self._voice_gateway.set_volume(context.guild_id, volume)
        return player.volume

    async def disconnect(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.DISCONNECT)
        player = await self._player(context.guild_id)
        self._invalidate_playback(context.guild_id)
        if self._voice_gateway is not None:
            await self._voice_gateway.stop(context.guild_id)
            await self._voice_gateway.disconnect(context.guild_id)
        player.disconnect()

    async def set_loop_mode(
        self, context: MusicRequestContext, mode: LoopMode | str
    ) -> LoopMode:
        await self._require(context, MusicCapability.LOOP)
        player = await self._player(context.guild_id)
        player.set_loop_mode(mode)
        return player.queue.loop_mode

    async def queue(self, context: MusicRequestContext) -> list[Track]:
        return (await self._player(context.guild_id)).queue.list()

    async def remove_from_queue(
        self, context: MusicRequestContext, index: int
    ) -> Track:
        await self._require(context, MusicCapability.QUEUE_REMOVE)
        return (await self._player(context.guild_id)).queue.remove(index)

    async def move_in_queue(
        self, context: MusicRequestContext, source_index: int, target_index: int
    ) -> None:
        await self._require(context, MusicCapability.QUEUE_MOVE)
        (await self._player(context.guild_id)).queue.move(source_index, target_index)

    async def shuffle_queue(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.QUEUE_SHUFFLE)
        (await self._player(context.guild_id)).queue.shuffle()

    async def clear_queue(self, context: MusicRequestContext) -> int:
        await self._require(context, MusicCapability.QUEUE_CLEAR)
        return len((await self._player(context.guild_id)).queue.clear())

    async def player_state(self, guild_id: int) -> GuildPlayer:
        return await self._player(guild_id)

    async def _require(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> None:
        if not await self._permissions.allowed(context, capability):
            raise PermissionDeniedError(f"Capability denied: {capability.value}")

    async def _player(self, guild_id: int) -> GuildPlayer:
        return await self._players.get_or_create(guild_id)

    async def _start_current(self, player: GuildPlayer) -> None:
        if self._voice_gateway is None or self._audio_source_factory is None:
            return
        track = player.current_track
        if track is None:
            return
        token = self._playback_tokens.get(player.guild_id, 0) + 1
        self._playback_tokens[player.guild_id] = token
        source = await self._audio_source_factory.create(track)
        loop = asyncio.get_running_loop()

        def after(error: Exception | None) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    self._handle_playback_finished(player.guild_id, token, error)
                )
            )

        await self._voice_gateway.play(player.guild_id, source, after=after)

    async def _handle_playback_finished(
        self, guild_id: int, token: int, error: Exception | None
    ) -> None:
        if self._playback_tokens.get(guild_id) != token:
            return
        player = await self._player(guild_id)
        if error is not None:
            player.status = PlaybackStatus.FAILED
            return
        next_track = player.start_next()
        if next_track is not None:
            await self._start_current(player)

    def _invalidate_playback(self, guild_id: int) -> None:
        self._playback_tokens[guild_id] = self._playback_tokens.get(guild_id, 0) + 1

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
