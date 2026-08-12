"""Bounded queue with explicit loop semantics."""

from __future__ import annotations

import random
from collections.abc import Iterable

from peacemusic.core.errors import ResourceNotFoundError, ValidationError
from peacemusic.modules.music.models import LoopMode, Track


class TrackQueue:
    """Upcoming tracks for one guild player.

    The queue deliberately has no knowledge of Discord, network resolvers, or
    audio processes.  ``advance`` receives the track that just finished so
    queue-loop behavior remains deterministic and testable.
    """

    def __init__(self, *, max_size: int = 200, tracks: Iterable[Track] = ()) -> None:
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._tracks = list(tracks)
        if len(self._tracks) > max_size:
            raise ValidationError("Initial queue exceeds max_size")
        self._loop_mode = LoopMode.OFF

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def loop_mode(self) -> LoopMode:
        return self._loop_mode

    @property
    def size(self) -> int:
        return len(self._tracks)

    def set_loop_mode(self, mode: LoopMode | str) -> None:
        try:
            self._loop_mode = LoopMode(mode)
        except ValueError as exc:
            raise ValidationError(f"Unknown loop mode: {mode!r}") from exc

    def add(self, track: Track) -> None:
        if self.size >= self._max_size:
            raise ValidationError("Queue is full")
        self._tracks.append(track)

    def extend(self, tracks: Iterable[Track]) -> None:
        pending = list(tracks)
        if self.size + len(pending) > self._max_size:
            raise ValidationError("Queue would exceed max_size")
        self._tracks.extend(pending)

    def remove(self, index: int) -> Track:
        self._validate_index(index)
        return self._tracks.pop(index)

    def move(self, source_index: int, target_index: int) -> None:
        self._validate_index(source_index)
        if target_index < 0 or target_index >= self.size:
            raise ResourceNotFoundError("Target queue index is out of range")
        track = self._tracks.pop(source_index)
        self._tracks.insert(target_index, track)

    def clear(self) -> list[Track]:
        tracks = list(self._tracks)
        self._tracks.clear()
        return tracks

    def shuffle(self) -> None:
        random.shuffle(self._tracks)

    def peek(self) -> Track | None:
        return self._tracks[0] if self._tracks else None

    def list(self) -> list[Track]:
        return list(self._tracks)

    def advance(self, current: Track | None = None) -> Track | None:
        """Return the next track and apply the configured loop mode."""

        if self._loop_mode is LoopMode.TRACK and current is not None:
            return current
        if self._loop_mode is LoopMode.QUEUE and current is not None:
            self._tracks.append(current)
            # Rotate in place when the bounded queue is already full.  This
            # keeps loop mode from bypassing the configured safety ceiling.
            return self._tracks.pop(0)
        return self._tracks.pop(0) if self._tracks else None

    def _validate_index(self, index: int) -> None:
        if index < 0 or index >= self.size:
            raise ResourceNotFoundError("Queue index is out of range")
