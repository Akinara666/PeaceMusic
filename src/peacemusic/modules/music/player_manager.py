"""Per-guild runtime player registry."""

from __future__ import annotations

import asyncio

from peacemusic.modules.music.player import GuildPlayer


class GuildPlayerManager:
    def __init__(self, *, default_max_queue_size: int = 200) -> None:
        self._players: dict[int, GuildPlayer] = {}
        self._lock = asyncio.Lock()
        self._default_max_queue_size = default_max_queue_size

    async def get_or_create(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is not None:
            return player
        async with self._lock:
            return self._players.setdefault(
                guild_id,
                GuildPlayer(
                    guild_id,
                    max_queue_size=self._default_max_queue_size,
                ),
            )

    def get(self, guild_id: int) -> GuildPlayer | None:
        return self._players.get(guild_id)

    async def remove(self, guild_id: int) -> GuildPlayer | None:
        async with self._lock:
            return self._players.pop(guild_id, None)

    def active_guild_ids(self) -> tuple[int, ...]:
        return tuple(self._players)
