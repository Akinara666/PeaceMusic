"""In-memory access-control repository for tests and local adapters."""

from __future__ import annotations


class InMemoryAccessControlRepository:
    def __init__(self) -> None:
        self.disabled_users: set[tuple[int, int]] = set()
        self.muted_channels: set[tuple[int, int]] = set()

    async def is_user_disabled(self, guild_id: int, user_id: int) -> bool:
        return (guild_id, user_id) in self.disabled_users

    async def is_channel_muted(self, guild_id: int, channel_id: int) -> bool:
        return (guild_id, channel_id) in self.muted_channels

    async def set_user_disabled(
        self, guild_id: int, user_id: int, disabled: bool
    ) -> None:
        self._set(self.disabled_users, guild_id, user_id, disabled)

    async def set_channel_muted(
        self, guild_id: int, channel_id: int, muted: bool
    ) -> None:
        self._set(self.muted_channels, guild_id, channel_id, muted)

    @staticmethod
    def _set(
        values: set[tuple[int, int]], guild_id: int, target_id: int, enabled: bool
    ) -> None:
        key = (guild_id, target_id)
        if enabled:
            values.add(key)
        else:
            values.discard(key)
