"""Bounded playback recovery policy."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from peacemusic.core.errors import PlaybackError

T = TypeVar("T")


class PlaybackRecoveryService:
    def __init__(
        self, *, max_attempts: int = 3, retry_delay_seconds: float = 1.0
    ) -> None:
        if max_attempts < 1 or retry_delay_seconds < 0:
            raise ValueError("Invalid playback recovery limits")
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds

    async def run(
        self,
        operation: Callable[[int], Awaitable[T]],
        *,
        refresh_source: Callable[[], Awaitable[None]] | None = None,
    ) -> T:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await operation(attempt)
            except Exception as exc:  # noqa: BLE001 - policy owns retry boundary
                last_error = exc
                if attempt == self.max_attempts:
                    break
                if refresh_source is not None:
                    await refresh_source()
                if self.retry_delay_seconds:
                    await asyncio.sleep(self.retry_delay_seconds)
        raise PlaybackError(
            "Playback failed after bounded recovery attempts"
        ) from last_error
