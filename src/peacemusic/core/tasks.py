"""Supervised background task lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any

logger = logging.getLogger(__name__)


class TaskSupervisor:
    """Own, observe, and shut down application background tasks."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closed = False

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def start(self, awaitable: Awaitable[Any], *, name: str) -> asyncio.Task[Any]:
        """Schedule an awaitable and attach failure observation to it."""

        if self._closed:
            raise RuntimeError("TaskSupervisor is shut down")
        task = asyncio.create_task(awaitable, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:  # noqa: BLE001 - task failures must be logged centrally
            logger.exception(
                "Supervised task failed", extra={"task_name": task.get_name()}
            )

    async def shutdown(self) -> None:
        """Cancel and await every task currently owned by the supervisor."""

        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
