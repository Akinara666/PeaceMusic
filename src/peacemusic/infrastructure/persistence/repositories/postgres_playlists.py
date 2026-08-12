"""PostgreSQL repository for persistent guild/user playlists."""

from __future__ import annotations

from typing import Any

from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.modules.playlists.models import Playlist, PlaylistTrack


class PostgresPlaylistRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def create(self, guild_id: int, owner_user_id: int, name: str) -> Playlist:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO playlists (guild_id, owner_user_id, name)
                VALUES ($1, $2, $3)
                RETURNING id, guild_id, owner_user_id, name
                """,
                guild_id,
                owner_user_id,
                name,
            )
        return Playlist(
            id=row["id"],
            guild_id=row["guild_id"],
            owner_user_id=row["owner_user_id"],
            name=row["name"],
        )

    async def get(
        self, guild_id: int, owner_user_id: int, name: str
    ) -> Playlist | None:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, guild_id, owner_user_id, name
                  FROM playlists
                 WHERE guild_id = $1 AND owner_user_id = $2 AND lower(name) = lower($3)
                """,
                guild_id,
                owner_user_id,
                name,
            )
            if row is None:
                return None
            tracks = await self._tracks(connection, row["id"])
        return self._playlist(row, tracks)

    async def list_for_user(self, guild_id: int, owner_user_id: int) -> list[Playlist]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, guild_id, owner_user_id, name
                  FROM playlists
                 WHERE guild_id = $1 AND owner_user_id = $2
                 ORDER BY lower(name)
                """,
                guild_id,
                owner_user_id,
            )
            playlists = []
            for row in rows:
                playlists.append(
                    self._playlist(row, await self._tracks(connection, row["id"]))
                )
        return playlists

    async def delete(self, playlist_id: int) -> None:
        async with self._database.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM playlist_tracks WHERE playlist_id = $1", playlist_id
                )
                await connection.execute(
                    "DELETE FROM playlists WHERE id = $1", playlist_id
                )

    async def save_tracks(
        self, playlist_id: int, tracks: list[PlaylistTrack]
    ) -> Playlist:
        async with self._database.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM playlist_tracks WHERE playlist_id = $1", playlist_id
                )
                for position, track in enumerate(tracks):
                    await connection.execute(
                        """
                        INSERT INTO playlist_tracks
                            (playlist_id, position, title, source_url, duration)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        playlist_id,
                        position,
                        track.title,
                        track.source_url,
                        track.duration,
                    )
            row = await connection.fetchrow(
                """
                SELECT id, guild_id, owner_user_id, name
                  FROM playlists
                 WHERE id = $1
                """,
                playlist_id,
            )
        if row is None:
            raise KeyError(f"Playlist not found: {playlist_id}")
        return self._playlist(row, tracks)

    @staticmethod
    async def _tracks(connection: Any, playlist_id: int) -> tuple[PlaylistTrack, ...]:
        rows = await connection.fetch(
            """
            SELECT title, source_url, duration
              FROM playlist_tracks
             WHERE playlist_id = $1
             ORDER BY position
            """,
            playlist_id,
        )
        return tuple(
            PlaylistTrack(
                title=row["title"],
                source_url=row["source_url"],
                duration=row["duration"],
            )
            for row in rows
        )

    @staticmethod
    def _playlist(row: Any, tracks: tuple[PlaylistTrack, ...] | list[PlaylistTrack]):
        return Playlist(
            id=row["id"],
            guild_id=row["guild_id"],
            owner_user_id=row["owner_user_id"],
            name=row["name"],
            tracks=tuple(tracks),
        )
