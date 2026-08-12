"""Persistence port for guild-configured DJ roles."""

from __future__ import annotations

from typing import Protocol


class DJRoleRepository(Protocol):
    async def list_role_ids(self, guild_id: int) -> tuple[int, ...]:
        """Return role IDs configured as DJ roles for a guild."""

    async def add_role(self, guild_id: int, role_id: int, role_name: str) -> None:
        """Add or retain one configured DJ role."""

    async def remove_role(self, guild_id: int, role_id: int) -> bool:
        """Remove a configured role and return whether it existed."""

    async def list_roles(self, guild_id: int) -> list[tuple[int, str]]:
        """Return configured role IDs and display names."""
