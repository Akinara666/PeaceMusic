"""Bounded application-side limits for agent requests."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class UserRateLimiter:
    """Enforce a sliding-window turn limit per guild/user pair."""

    def __init__(self, *, window_seconds: float = 60.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_seconds = window_seconds
        self._events: defaultdict[tuple[int | None, int], deque[float]] = defaultdict(
            deque
        )
        self._lock = asyncio.Lock()

    async def allow(self, key: tuple[int | None, int], limit: int) -> bool:
        """Record a turn when capacity remains and return whether it is allowed."""

        if limit < 1:
            return False
        now = time.monotonic()
        cutoff = now - self._window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True
