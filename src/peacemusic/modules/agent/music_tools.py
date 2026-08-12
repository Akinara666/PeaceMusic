"""Thin agent adapters over the shared MusicService."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from peacemusic.core.errors import PeaceMusicError, describe_exception
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.music_context import music_context
from peacemusic.modules.agent.results import ToolResult
from peacemusic.modules.agent.tools import ToolCategory, ToolSpec
from peacemusic.modules.music.permissions import MusicRequestContext
from peacemusic.modules.music.service import MusicService


class PlayMusicArguments(BaseModel):
    query: str = Field(min_length=1, max_length=512)


class VolumeArguments(BaseModel):
    value: int = Field(ge=0, le=100)


class LoopArguments(BaseModel):
    mode: Literal["off", "track", "queue"]


class QueueIndexArguments(BaseModel):
    index: int = Field(ge=0)


class QueueMoveArguments(BaseModel):
    source_index: int = Field(ge=0)
    target_index: int = Field(ge=0)


class SeekArguments(BaseModel):
    seconds: int = Field(ge=0)


def build_music_tool_specs(service: MusicService) -> tuple[ToolSpec, ...]:
    """Create model-facing tools with no duplicated music business logic."""

    async def play_music(context: AgentRequestContext, query: str) -> ToolResult:
        try:
            args = PlayMusicArguments(query=query)
            track = await service.play(_music_context(context), args.query)
            return ToolResult.success(
                f"Queued {track.title}",
                data={"title": track.title, "source_url": track.source_url},
            )
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def pause_music(context: AgentRequestContext) -> ToolResult:
        return await _run(service.pause, context, "Playback paused")

    async def resume_music(context: AgentRequestContext) -> ToolResult:
        return await _run(service.resume, context, "Playback resumed")

    async def skip_music(context: AgentRequestContext) -> ToolResult:
        try:
            track = await service.skip(_music_context(context))
            return ToolResult.success(
                "Skipped current track",
                data={"next_track": track.title if track else None},
            )
        except PeaceMusicError as exc:
            return _failure(exc)

    async def stop_music(context: AgentRequestContext) -> ToolResult:
        return await _run(service.stop, context, "Playback stopped")

    async def join_voice(context: AgentRequestContext) -> ToolResult:
        return await _run(service.connect, context, "Joined your voice channel")

    async def disconnect_voice(context: AgentRequestContext) -> ToolResult:
        return await _run(service.disconnect, context, "Disconnected from voice")

    async def seek_music(context: AgentRequestContext, seconds: int) -> ToolResult:
        try:
            args = SeekArguments(seconds=seconds)
            position = await service.seek(_music_context(context), args.seconds)
            return ToolResult.success(
                f"Playback seeked to {position} seconds",
                data={"position_seconds": position},
            )
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def set_volume(context: AgentRequestContext, value: int) -> ToolResult:
        try:
            args = VolumeArguments(value=value)
            volume = await service.set_volume(_music_context(context), args.value)
            return ToolResult.success(
                f"Volume set to {volume}%", data={"volume": volume}
            )
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def set_loop_mode(context: AgentRequestContext, mode: str) -> ToolResult:
        try:
            args = LoopArguments(mode=mode)
            selected = await service.set_loop_mode(_music_context(context), args.mode)
            return ToolResult.success(
                f"Loop mode set to {selected.value}",
                data={"mode": selected.value},
            )
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def get_queue(context: AgentRequestContext) -> ToolResult:
        try:
            queue = await service.queue(_music_context(context))
            return ToolResult.success(
                f"Queue contains {len(queue)} tracks",
                data={"tracks": [track.title for track in queue]},
            )
        except PeaceMusicError as exc:
            return _failure(exc)

    async def remove_from_queue(context: AgentRequestContext, index: int) -> ToolResult:
        try:
            args = QueueIndexArguments(index=index)
            track = await service.remove_from_queue(_music_context(context), args.index)
            return ToolResult.success(
                f"Removed {track.title}", data={"title": track.title}
            )
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def move_in_queue(
        context: AgentRequestContext, source_index: int, target_index: int
    ) -> ToolResult:
        try:
            args = QueueMoveArguments(
                source_index=source_index,
                target_index=target_index,
            )
            await service.move_in_queue(
                _music_context(context), args.source_index, args.target_index
            )
            return ToolResult.success("Queue position updated")
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def shuffle_queue(context: AgentRequestContext) -> ToolResult:
        return await _run(service.shuffle_queue, context, "Queue shuffled")

    async def clear_queue(context: AgentRequestContext) -> ToolResult:
        try:
            count = await service.clear_queue(_music_context(context))
            return ToolResult.success("Queue cleared", data={"removed": count})
        except PeaceMusicError as exc:
            return _failure(exc)

    async def now_playing(context: AgentRequestContext) -> ToolResult:
        try:
            player = await service.player_state(context.guild_id or 0)
            return ToolResult.success(
                (
                    player.current_track.title
                    if player.current_track
                    else "Nothing playing"
                ),
                data={
                    "title": (
                        player.current_track.title if player.current_track else None
                    ),
                    "status": player.status.value,
                    "volume": player.volume,
                },
            )
        except PeaceMusicError as exc:
            return _failure(exc)

    return (
        ToolSpec(
            "play_music",
            ToolCategory.MUSIC,
            play_music,
            PlayMusicArguments,
            "Play or queue a song from a supported media URL or search query.",
        ),
        ToolSpec(
            "pause_music",
            ToolCategory.MUSIC,
            pause_music,
            description="Pause the currently playing track.",
        ),
        ToolSpec(
            "resume_music",
            ToolCategory.MUSIC,
            resume_music,
            description="Resume the paused track.",
        ),
        ToolSpec(
            "skip_music",
            ToolCategory.MUSIC,
            skip_music,
            description="Skip the current track and start the next queued track.",
        ),
        ToolSpec(
            "stop_music",
            ToolCategory.MUSIC,
            stop_music,
            description="Stop playback and clear the current music queue.",
        ),
        ToolSpec(
            "join_voice",
            ToolCategory.MUSIC,
            join_voice,
            description="Join the user's current Discord voice channel.",
        ),
        ToolSpec(
            "disconnect_voice",
            ToolCategory.MUSIC,
            disconnect_voice,
            description="Disconnect the bot from the guild's voice channel.",
        ),
        ToolSpec(
            "seek_music",
            ToolCategory.MUSIC,
            seek_music,
            SeekArguments,
            "Move the current track to a specified position in seconds.",
        ),
        ToolSpec(
            "set_volume",
            ToolCategory.MUSIC,
            set_volume,
            VolumeArguments,
            "Set the playback volume from 0 to 100 percent.",
        ),
        ToolSpec(
            "set_loop_mode",
            ToolCategory.MUSIC,
            set_loop_mode,
            LoopArguments,
            "Set looping for the current track, the queue, or turn looping off.",
        ),
        ToolSpec(
            "get_queue",
            ToolCategory.MUSIC,
            get_queue,
            description="Show the tracks currently waiting in the music queue.",
        ),
        ToolSpec(
            "remove_from_queue",
            ToolCategory.MUSIC,
            remove_from_queue,
            QueueIndexArguments,
            "Remove one track from the queue by its zero-based position.",
        ),
        ToolSpec(
            "move_in_queue",
            ToolCategory.MUSIC,
            move_in_queue,
            QueueMoveArguments,
            "Move a queued track from one zero-based position to another.",
        ),
        ToolSpec(
            "shuffle_queue",
            ToolCategory.MUSIC,
            shuffle_queue,
            description="Randomize the order of tracks waiting in the queue.",
        ),
        ToolSpec(
            "clear_queue",
            ToolCategory.MUSIC,
            clear_queue,
            description="Remove all waiting tracks from the music queue.",
        ),
        ToolSpec(
            "now_playing",
            ToolCategory.MUSIC,
            now_playing,
            description="Report the current track, playback status, and volume.",
        ),
    )


async def _run(operation, context: AgentRequestContext, message: str) -> ToolResult:
    try:
        await operation(_music_context(context))
        return ToolResult.success(message)
    except PeaceMusicError as exc:
        return _failure(exc)


def _music_context(context: AgentRequestContext) -> MusicRequestContext:
    return music_context(context)


def _failure(error: Exception) -> ToolResult:
    code = (
        "INVALID_TOOL_ARGUMENTS"
        if isinstance(error, PydanticValidationError)
        else type(error).__name__.upper()
    )
    return ToolResult.failure(code, describe_exception(error))
