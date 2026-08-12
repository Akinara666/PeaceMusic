from __future__ import annotations

import asyncio

from peacemusic.infrastructure.persistence.repositories.in_memory_dj_roles import (
    InMemoryDJRoleRepository,
)


def test_dj_role_repository_is_guild_scoped() -> None:
    async def scenario() -> None:
        repository = InMemoryDJRoleRepository()
        await repository.add_role(1, 10, "DJ")
        await repository.add_role(2, 20, "Moderator")

        assert await repository.list_role_ids(1) == (10,)
        assert await repository.list_role_ids(2) == (20,)
        assert await repository.remove_role(1, 999) is False

    asyncio.run(scenario())
