"""PostgreSQL repository for configured DJ roles."""

from __future__ import annotations

from peacemusic.infrastructure.persistence.database import PostgresDatabase


class PostgresDJRoleRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def list_role_ids(self, guild_id: int) -> tuple[int, ...]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT role_id FROM guild_roles
                 WHERE guild_id = $1
                 ORDER BY role_id
                """,
                guild_id,
            )
        return tuple(row["role_id"] for row in rows)

    async def add_role(self, guild_id: int, role_id: int, role_name: str) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO guild_roles (guild_id, role_id, role_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, role_id) DO UPDATE
                    SET role_name = EXCLUDED.role_name
                """,
                guild_id,
                role_id,
                role_name,
            )

    async def remove_role(self, guild_id: int, role_id: int) -> bool:
        async with self._database.acquire() as connection:
            result = await connection.execute(
                "DELETE FROM guild_roles WHERE guild_id = $1 AND role_id = $2",
                guild_id,
                role_id,
            )
        return result.endswith("1")

    async def list_roles(self, guild_id: int) -> list[tuple[int, str]]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT role_id, role_name FROM guild_roles
                 WHERE guild_id = $1 ORDER BY role_name
                """,
                guild_id,
            )
        return [(row["role_id"], row["role_name"]) for row in rows]
