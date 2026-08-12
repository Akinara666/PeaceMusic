"""PostgreSQL access-control repository."""

from __future__ import annotations

from peacemusic.infrastructure.persistence.database import PostgresDatabase


class PostgresAccessControlRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def is_user_disabled(self, guild_id: int, user_id: int) -> bool:
        async with self._database.acquire() as connection:
            return bool(
                await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM disabled_users "
                    "WHERE guild_id = $1 AND user_id = $2)",
                    guild_id,
                    user_id,
                )
            )

    async def is_channel_muted(self, guild_id: int, channel_id: int) -> bool:
        async with self._database.acquire() as connection:
            return bool(
                await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM channel_mutes "
                    "WHERE guild_id = $1 AND channel_id = $2)",
                    guild_id,
                    channel_id,
                )
            )

    async def set_user_disabled(
        self, guild_id: int, user_id: int, disabled: bool
    ) -> None:
        async with self._database.acquire() as connection:
            if disabled:
                await connection.execute(
                    "INSERT INTO disabled_users (guild_id, user_id) "
                    "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    guild_id,
                    user_id,
                )
            else:
                await connection.execute(
                    "DELETE FROM disabled_users WHERE guild_id = $1 AND user_id = $2",
                    guild_id,
                    user_id,
                )

    async def set_channel_muted(
        self, guild_id: int, channel_id: int, muted: bool
    ) -> None:
        async with self._database.acquire() as connection:
            if muted:
                await connection.execute(
                    "INSERT INTO channel_mutes (guild_id, channel_id, silenced_at) "
                    "VALUES ($1, $2, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING",
                    guild_id,
                    channel_id,
                )
            else:
                await connection.execute(
                    "DELETE FROM channel_mutes WHERE guild_id = $1 AND channel_id = $2",
                    guild_id,
                    channel_id,
                )
