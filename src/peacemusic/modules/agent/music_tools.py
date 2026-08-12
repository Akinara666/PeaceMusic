"""Thin agent adapters over the shared MusicService."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.agent.context import AgentRequestContext
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
        ToolSpec("play_music", ToolCategory.MUSIC, play_music),
        ToolSpec("pause_music", ToolCategory.MUSIC, pause_music),
        ToolSpec("resume_music", ToolCategory.MUSIC, resume_music),
        ToolSpec("skip_music", ToolCategory.MUSIC, skip_music),
        ToolSpec("stop_music", ToolCategory.MUSIC, stop_music),
        ToolSpec("set_volume", ToolCategory.MUSIC, set_volume),
        ToolSpec("set_loop_mode", ToolCategory.MUSIC, set_loop_mode),
        ToolSpec("get_queue", ToolCategory.MUSIC, get_queue),
        ToolSpec("now_playing", ToolCategory.MUSIC, now_playing),
    )


async def _run(operation, context: AgentRequestContext, message: str) -> ToolResult:
    try:
        await operation(_music_context(context))
        return ToolResult.success(message)
    except PeaceMusicError as exc:
        return _failure(exc)


def _music_context(context: AgentRequestContext) -> MusicRequestContext:
    return MusicRequestContext(
        guild_id=context.guild_id or 0,
        user_id=context.user_id,
        user_voice_channel_id=context.user_voice_channel_id,
        bot_voice_channel_id=context.bot_voice_channel_id,
        can_manage_guild=context.can_manage_guild,
    )


def _failure(error: Exception) -> ToolResult:
    code = (
        "INVALID_TOOL_ARGUMENTS"
        if isinstance(error, PydanticValidationError)
        else type(error).__name__.upper()
    )
    return ToolResult.failure(code, str(error))
