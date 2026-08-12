"""PostgreSQL persistence for the Discord player message identity."""

from __future__ import annotations

from peacemusic.infrastructure.persistence.database import PostgresDatabase


class PostgresPlayerMessageRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def get(self, guild_id: int) -> tuple[int, int] | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT channel_id, message_id FROM player_messages WHERE guild_id = $1",
                guild_id,
            )
        return (int(row["channel_id"]), int(row["message_id"])) if row else None

    async def save(self, guild_id: int, *, channel_id: int, message_id: int) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO player_messages (guild_id, channel_id, message_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    message_id = EXCLUDED.message_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                guild_id,
                channel_id,
                message_id,
            )
