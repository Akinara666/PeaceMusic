"""Persistence ports for guild access controls."""

from __future__ import annotations

from typing import Protocol


class AccessControlRepository(Protocol):
    async def is_user_disabled(self, guild_id: int, user_id: int) -> bool:
        """Return whether a user is blocked from bot interactions."""

    async def is_channel_muted(self, guild_id: int, channel_id: int) -> bool:
        """Return whether bot responses are silenced in a channel."""

    async def set_user_disabled(
        self, guild_id: int, user_id: int, disabled: bool
    ) -> None:
        """Enable or disable a user's access."""

    async def set_channel_muted(
        self, guild_id: int, channel_id: int, muted: bool
    ) -> None:
        """Enable or disable silent mode for a channel."""
