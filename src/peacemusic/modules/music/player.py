"""Runtime player state independent from Discord voice objects."""

from __future__ import annotations

from peacemusic.core.errors import ValidationError
from peacemusic.modules.music.models import LoopMode, PlaybackStatus, Track
from peacemusic.modules.music.queue import TrackQueue


class GuildPlayer:
    """State machine for one guild's active playback session."""

    def __init__(self, guild_id: int, *, max_queue_size: int = 200) -> None:
        self.guild_id = guild_id
        self.queue = TrackQueue(max_size=max_queue_size)
        self.current_track: Track | None = None
        self.status = PlaybackStatus.IDLE
        self.volume = 70
        self.max_volume = 100
        self.position_seconds = 0
        self.voice_channel_id: int | None = None

    @property
    def is_active(self) -> bool:
        return self.status in {
            PlaybackStatus.PLAYING,
            PlaybackStatus.PAUSED,
            PlaybackStatus.RECOVERING,
        }

    def enqueue(self, track: Track) -> None:
        self.queue.add(track)
        if self.current_track is None:
            self.start_next()

    def start_next(self) -> Track | None:
        next_track = self.queue.advance(self.current_track)
        self.current_track = next_track
        self.position_seconds = 0
        self.status = (
            PlaybackStatus.PLAYING if next_track is not None else PlaybackStatus.IDLE
        )
        return next_track

    def pause(self) -> None:
        if self.status is not PlaybackStatus.PLAYING:
            raise ValidationError("Player is not playing")
        self.status = PlaybackStatus.PAUSED

    def resume(self) -> None:
        if self.status is not PlaybackStatus.PAUSED:
            raise ValidationError("Player is not paused")
        self.status = PlaybackStatus.PLAYING

    def skip(self) -> Track | None:
        return self.start_next()

    def stop(self) -> None:
        self.queue.clear()
        self.current_track = None
        self.position_seconds = 0
        self.status = PlaybackStatus.STOPPED

    def set_volume(self, volume: int) -> None:
        if volume < 0 or volume > self.max_volume:
            raise ValidationError(f"volume must be between 0 and {self.max_volume}")
        self.volume = volume

    def set_loop_mode(self, mode: LoopMode | str) -> None:
        self.queue.set_loop_mode(mode)
