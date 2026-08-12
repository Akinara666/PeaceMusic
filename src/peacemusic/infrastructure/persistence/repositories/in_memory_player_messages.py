"""In-memory player-message identity repository for tests and local use."""

from __future__ import annotations


class InMemoryPlayerMessageRepository:
    def __init__(self) -> None:
        self.values: dict[int, tuple[int, int]] = {}

    async def get(self, guild_id: int) -> tuple[int, int] | None:
        return self.values.get(guild_id)

    async def save(self, guild_id: int, *, channel_id: int, message_id: int) -> None:
        self.values[guild_id] = (channel_id, message_id)
