"""Shared music application operations used by all adapters."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from peacemusic.core.errors import PermissionDeniedError, PlaybackError, ValidationError
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.modules.audit.service import AuditService
from peacemusic.modules.autoplay.service import AutoplayService
from peacemusic.modules.history.service import PlaybackHistoryService
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
from peacemusic.modules.music.recovery import PlaybackRecoveryService
from peacemusic.modules.settings.service import GuildSettingsService


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
        history: PlaybackHistoryService | None = None,
        autoplay: AutoplayService | None = None,
        recovery: PlaybackRecoveryService | None = None,
        settings: GuildSettingsService | None = None,
        audit: AuditService | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._players = player_manager
        self._resolver = resolver
        self._permissions = permissions
        self._voice_gateway = voice_gateway
        self._audio_source_factory = audio_source_factory
        self._history = history
        self._autoplay = autoplay
        self._recovery = recovery
        self._settings = settings
        self._audit = audit
        self._metrics = metrics
        self._playback_tokens: dict[int, int] = {}
        self._idle_disconnect_tasks: dict[int, asyncio.Task[None]] = {}

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
        if self._voice_gateway is not None and context.user_voice_channel_id is None:
            raise ValidationError("User must be in a voice channel")
        track = await self.resolve_track(context, query)
        await self.enqueue_track(context, track)
        return track

    async def play_direct_audio(
        self, context: MusicRequestContext, *, title: str, url: str
    ) -> Track:
        """Queue a Discord attachment URL without sending it through yt-dlp."""

        await self._require(context, MusicCapability.PLAY)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or host not in {
            "cdn.discordapp.com",
            "media.discordapp.net",
        }:
            raise ValidationError(
                "Direct audio URL is not a trusted Discord attachment"
            )
        if not title.strip():
            raise ValidationError("Audio attachment has no filename")
        track = Track(
            title=title.strip(),
            source_url=url,
            requested_by=context.user_id,
            stream_url=url,
        )
        await self.enqueue_track(context, track)
        return track

    async def enqueue_track(self, context: MusicRequestContext, track: Track) -> None:
        """Enqueue already validated metadata into the shared player."""

        await self._require(context, MusicCapability.PLAY)
        if self._voice_gateway is not None and context.user_voice_channel_id is None:
            raise ValidationError("User must be in a voice channel")
        player = await self._players.get_or_create(context.guild_id)
        self._cancel_idle_disconnect(context.guild_id)
        was_idle = player.current_track is None
        if self._voice_gateway is not None:
            await self._voice_gateway.connect(
                context.guild_id, context.user_voice_channel_id
            )
            player.attach_voice(context.user_voice_channel_id)
        player.enqueue(track)
        if self._history is not None:
            await self._history.record(context.guild_id, track)
        await self._record_audit(
            context,
            "PLAY",
            {"title": track.title, "source_url": track.source_url},
        )
        self._increment_metric("peacemusic_music_play_total")
        if self._voice_gateway is not None and was_idle:
            await self._start_current(player)

    async def resolve_track(self, context: MusicRequestContext, query: str) -> Track:
        """Resolve metadata without enqueueing it into a live player."""

        await self._require(context, MusicCapability.PLAY)
        if not query.strip():
            raise ValidationError("Music query cannot be empty")
        media = await self._resolver.resolve(query)
        return self._track_from_media(media, requested_by=context.user_id)

    async def pause(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.PAUSE)
        player = await self._player(context.guild_id)
        player.pause()
        if self._voice_gateway is not None:
            await self._voice_gateway.pause(context.guild_id)
        self._increment_metric("peacemusic_music_pause_total")

    async def resume(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.RESUME)
        player = await self._player(context.guild_id)
        player.resume()
        if self._voice_gateway is not None:
            await self._voice_gateway.resume(context.guild_id)
        self._increment_metric("peacemusic_music_resume_total")

    async def skip(self, context: MusicRequestContext) -> Track | None:
        await self._require(context, MusicCapability.SKIP)
        player = await self._player(context.guild_id)
        if self._voice_gateway is not None:
            self._invalidate_playback(context.guild_id)
            await self._voice_gateway.stop(context.guild_id)
        next_track = player.skip()
        if self._voice_gateway is not None and next_track is not None:
            await self._start_current(player)
        await self._record_audit(
            context,
            "SKIP",
            {"next_track": next_track.title if next_track else None},
        )
        self._increment_metric("peacemusic_music_skip_total")
        return next_track

    async def seek(self, context: MusicRequestContext, position_seconds: int) -> int:
        await self._require(context, MusicCapability.SEEK)
        player = await self._player(context.guild_id)
        position = player.seek(position_seconds)
        if self._voice_gateway is not None:
            self._invalidate_playback(context.guild_id)
            await self._voice_gateway.stop(context.guild_id)
            await self._start_current(player, start_seconds=position)
        await self._record_audit(context, "SEEK", {"position_seconds": position})
        self._increment_metric("peacemusic_music_seek_total")
        return position

    async def stop(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.STOP)
        player = await self._player(context.guild_id)
        self._invalidate_playback(context.guild_id)
        player.stop()
        if self._voice_gateway is not None:
            await self._voice_gateway.stop(context.guild_id)
        await self._record_audit(context, "STOP")
        self._increment_metric("peacemusic_music_stop_total")

    async def set_volume(self, context: MusicRequestContext, volume: int) -> int:
        await self._require(context, MusicCapability.SET_VOLUME)
        player = await self._player(context.guild_id)
        player.set_volume(volume)
        if self._voice_gateway is not None:
            await self._voice_gateway.set_volume(context.guild_id, volume)
        await self._record_audit(context, "SET_VOLUME", {"volume": player.volume})
        self._increment_metric("peacemusic_music_volume_changes_total")
        return player.volume

    async def disconnect(self, context: MusicRequestContext) -> None:
        await self._require(context, MusicCapability.DISCONNECT)
        player = await self._player(context.guild_id)
        self._invalidate_playback(context.guild_id)
        if self._voice_gateway is not None:
            await self._voice_gateway.stop(context.guild_id)
            await self._voice_gateway.disconnect(context.guild_id)
        player.disconnect()
        await self._record_audit(context, "DISCONNECT")
        self._increment_metric("peacemusic_music_disconnect_total")

    async def connect(self, context: MusicRequestContext) -> None:
        """Connect the guild player to the caller's current voice channel."""

        await self._require(context, MusicCapability.CONNECT)
        if self._voice_gateway is None:
            raise ValidationError("Voice playback is not attached")
        if context.user_voice_channel_id is None:
            raise ValidationError("User must be in a voice channel")
        await self._voice_gateway.connect(
            context.guild_id, context.user_voice_channel_id
        )
        player = await self._player(context.guild_id)
        player.attach_voice(context.user_voice_channel_id)
        await self._record_audit(
            context,
            "CONNECT",
            {"voice_channel_id": context.user_voice_channel_id},
        )
        self._increment_metric("peacemusic_music_connect_total")

    def _increment_metric(self, name: str) -> None:
        if self._metrics is not None:
            self._metrics.increment(name)

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

    async def _record_audit(
        self,
        context: MusicRequestContext,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        if self._audit is not None:
            await self._audit.record(
                guild_id=context.guild_id,
                actor_user_id=context.user_id,
                event_type=event_type,
                payload=payload,
            )

    async def _start_current(
        self, player: GuildPlayer, *, start_seconds: int = 0
    ) -> None:
        if self._voice_gateway is None or self._audio_source_factory is None:
            return
        track = player.current_track
        if track is None:
            return
        token = self._playback_tokens.get(player.guild_id, 0) + 1
        self._playback_tokens[player.guild_id] = token
        loop = asyncio.get_running_loop()

        def after(error: Exception | None) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    self._handle_playback_finished(player.guild_id, token, error)
                )
            )

        async def start(_attempt: int) -> None:
            if start_seconds:
                source = await self._audio_source_factory.create(
                    track, start_seconds=start_seconds
                )
            else:
                source = await self._audio_source_factory.create(track)
            await self._voice_gateway.play(player.guild_id, source, after=after)

        try:
            if self._recovery is None:
                await start(1)
            else:
                player.status = PlaybackStatus.RECOVERING
                await self._recovery.run(start)
                player.status = PlaybackStatus.PLAYING
        except PlaybackError:
            player.status = PlaybackStatus.FAILED
            raise

    async def _handle_playback_finished(
        self, guild_id: int, token: int, error: Exception | None
    ) -> None:
        if self._playback_tokens.get(guild_id) != token:
            return
        player = await self._player(guild_id)
        if error is not None:
            if self._recovery is not None and player.current_track is not None:
                try:
                    await self._start_current(player)
                except PlaybackError:
                    return
                return
            player.status = PlaybackStatus.FAILED
            return
        previous_track = player.current_track
        next_track = player.start_next()
        if next_track is None and self._autoplay is not None and previous_track:
            candidate = await self._autoplay.next(guild_id, previous_track)
            if candidate is not None:
                player.enqueue(candidate)
                next_track = player.current_track
                if self._history is not None:
                    await self._history.record(guild_id, candidate)
        if next_track is not None:
            await self._start_current(player)
        elif self._voice_gateway is not None:
            self._schedule_idle_disconnect(guild_id)

    def _invalidate_playback(self, guild_id: int) -> None:
        self._playback_tokens[guild_id] = self._playback_tokens.get(guild_id, 0) + 1

    def _schedule_idle_disconnect(self, guild_id: int) -> None:
        if self._settings is None or self._voice_gateway is None:
            return
        self._cancel_idle_disconnect(guild_id)
        self._idle_disconnect_tasks[guild_id] = asyncio.create_task(
            self._idle_disconnect_after(guild_id)
        )

    def _cancel_idle_disconnect(self, guild_id: int) -> None:
        task = self._idle_disconnect_tasks.pop(guild_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _idle_disconnect_after(self, guild_id: int) -> None:
        try:
            settings = await self._settings.get(guild_id)  # type: ignore[union-attr]
            if not settings.voice.idle_disconnect_enabled or settings.voice.mode_24_7:
                return
            await asyncio.sleep(settings.voice.idle_disconnect_timeout)
            player = await self._player(guild_id)
            if player.current_track is not None or player.voice_channel_id is None:
                return
            self._invalidate_playback(guild_id)
            await self._voice_gateway.stop(guild_id)  # type: ignore[union-attr]
            await self._voice_gateway.disconnect(guild_id)  # type: ignore[union-attr]
            player.disconnect()
        finally:
            if self._idle_disconnect_tasks.get(guild_id) is asyncio.current_task():
                self._idle_disconnect_tasks.pop(guild_id, None)

    async def shutdown(self) -> None:
        for guild_id in tuple(self._idle_disconnect_tasks):
            self._cancel_idle_disconnect(guild_id)

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
