"""Framework-independent music models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LoopMode(StrEnum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class PlaybackStatus(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    DISCONNECTED = "disconnected"
    RECOVERING = "recovering"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Track:
    """Metadata needed by the player, not a downloaded audio file."""

    title: str
    source_url: str
    requested_by: int
    webpage_url: str | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    duration: int | None = None
    stream_url: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedMedia:
    """Resolver output before it is associated with a requesting user."""

    title: str
    source_url: str
    webpage_url: str | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    duration: int | None = None
    stream_url: str | None = None
