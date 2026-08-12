"""Autoplay models independent from recommendation providers."""

from __future__ import annotations

from dataclasses import dataclass

from peacemusic.modules.music.models import Track


@dataclass(frozen=True, slots=True)
class AutoplayContext:
    guild_id: int
    previous_track: Track


@dataclass(frozen=True, slots=True)
class TrackCandidate:
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
