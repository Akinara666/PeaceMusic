"""Deterministic DJ-role repository for tests."""

from __future__ import annotations


class InMemoryDJRoleRepository:
    def __init__(self) -> None:
        self.values: dict[int, dict[int, str]] = {}

    async def list_role_ids(self, guild_id: int) -> tuple[int, ...]:
        return tuple(self.values.get(guild_id, {}))

    async def add_role(self, guild_id: int, role_id: int, role_name: str) -> None:
        self.values.setdefault(guild_id, {})[role_id] = role_name

    async def remove_role(self, guild_id: int, role_id: int) -> bool:
        roles = self.values.get(guild_id, {})
        if role_id not in roles:
            return False
        del roles[role_id]
        return True

    async def list_roles(self, guild_id: int) -> list[tuple[int, str]]:
        return list(self.values.get(guild_id, {}).items())
