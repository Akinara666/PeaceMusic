"""Per-channel sequential turn coordination with global concurrency limits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CoordinatorStats:
    active_turns: int
    completed_turns: int
    timed_out_turns: int


class TurnCoordinator:
    def __init__(
        self, *, max_concurrent: int = 4, timeout_seconds: float = 120.0
    ) -> None:
        if max_concurrent < 1 or timeout_seconds <= 0:
            raise ValueError("Invalid turn coordination limits")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._channel_locks: dict[int, asyncio.Lock] = {}
        self._active_turns = 0
        self._completed_turns = 0
        self._timed_out_turns = 0
        self._stats_lock = asyncio.Lock()
        self._timeout_seconds = timeout_seconds

    async def run(self, channel_id: int, operation: Callable[[], Awaitable[T]]) -> T:
        lock = self._channel_locks.setdefault(channel_id, asyncio.Lock())
        async with lock, self._semaphore:
            async with self._stats_lock:
                self._active_turns += 1
            try:
                result = await asyncio.wait_for(operation(), self._timeout_seconds)
            except asyncio.TimeoutError:
                async with self._stats_lock:
                    self._timed_out_turns += 1
                raise
            else:
                async with self._stats_lock:
                    self._completed_turns += 1
                return result
            finally:
                async with self._stats_lock:
                    self._active_turns -= 1

    async def stats(self) -> CoordinatorStats:
        async with self._stats_lock:
            return CoordinatorStats(
                active_turns=self._active_turns,
                completed_turns=self._completed_turns,
                timed_out_turns=self._timed_out_turns,
            )
