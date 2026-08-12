from __future__ import annotations

import asyncio
import os

import pytest

from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.infrastructure.persistence.repositories.postgres_settings import (
    PostgresGuildSettingsRepository,
)
from peacemusic.modules.settings.service import GuildSettingsService

pytestmark = pytest.mark.integration


def test_postgres_settings_survive_service_restart() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")

    async def scenario() -> None:
        database = PostgresDatabase(database_url, min_size=1, max_size=2)
        await database.connect()
        try:
            guild_id = 991234567890
            service = GuildSettingsService(PostgresGuildSettingsRepository(database))
            current = await service.get(guild_id)
            current.music.default_volume = 55
            await PostgresGuildSettingsRepository(database).save(current)

            restarted = GuildSettingsService(PostgresGuildSettingsRepository(database))
            loaded = await restarted.get(guild_id)
            assert loaded.music.default_volume == 55
        finally:
            await database.close()

    asyncio.run(scenario())
