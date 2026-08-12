from __future__ import annotations

import asyncio

from peacemusic.infrastructure.persistence.repositories.postgres_settings import (
    PostgresGuildSettingsRepository,
)
from peacemusic.modules.settings.models import GuildSettings


def test_postgres_settings_mapping_covers_complete_aggregate() -> None:
    settings = GuildSettings(
        guild_id=123,
        general={"language": "ru", "music_channel_id": 10},
        music={
            "default_volume": 55,
            "default_loop_mode": "queue",
            "max_playlist_size": 40,
        },
        voice={"mode_24_7": True, "default_voice_channel": 20},
        ai={"enabled": False, "per_user_rate_limit": 7},
        memory={"memory_retention_days": 30},
    )

    values = PostgresGuildSettingsRepository._values(settings)
    columns = PostgresGuildSettingsRepository._column_names()
    row = dict(zip(columns, values))
    restored = PostgresGuildSettingsRepository._from_row(row)

    assert len(values) == len(columns)
    assert restored == settings


def test_postgres_settings_save_writes_all_columns() -> None:
    class Connection:
        def __init__(self) -> None:
            self.statement: str | None = None
            self.args: tuple[object, ...] = ()

        async def execute(self, statement: str, *args: object) -> None:
            self.statement = statement
            self.args = args

    class Acquire:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        async def __aenter__(self) -> Connection:
            return self.connection

        async def __aexit__(self, *args: object) -> None:
            return None

    class Database:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        def acquire(self) -> Acquire:
            return Acquire(self.connection)

    async def scenario() -> None:
        connection = Connection()
        repository = PostgresGuildSettingsRepository(Database(connection))  # type: ignore[arg-type]
        await repository.save(GuildSettings(guild_id=123))

        assert connection.statement is not None
        assert "notifications_enabled" in connection.statement
        assert "memory_retention_days" in connection.statement
        assert len(connection.args) == len(
            PostgresGuildSettingsRepository._column_names()
        )

    asyncio.run(scenario())
