"""Framework-independent playlist models."""

from __future__ import annotations

from dataclasses import dataclass, field

from peacemusic.modules.music.models import Track


@dataclass(frozen=True, slots=True)
class PlaylistTrack:
    title: str
    source_url: str
    duration: int | None = None

    def as_track(self, *, requested_by: int) -> Track:
        return Track(
            title=self.title,
            source_url=self.source_url,
            requested_by=requested_by,
            duration=self.duration,
        )


@dataclass(frozen=True, slots=True)
class Playlist:
    id: int
    guild_id: int
    owner_user_id: int
    name: str
    tracks: tuple[PlaylistTrack, ...] = field(default_factory=tuple)
