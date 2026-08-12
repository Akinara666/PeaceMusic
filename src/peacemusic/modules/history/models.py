"""Framework-independent playback history models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PlaybackHistoryEntry:
    id: int
    guild_id: int
    title: str
    source_url: str
    requested_by: int
    played_at: datetime
    duration: int | None = None
