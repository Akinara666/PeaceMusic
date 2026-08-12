"""Deterministic playlist repository for tests and local development."""

from __future__ import annotations

from peacemusic.modules.playlists.models import Playlist, PlaylistTrack


class InMemoryPlaylistRepository:
    def __init__(self) -> None:
        self.values: dict[int, Playlist] = {}
        self._next_id = 1

    async def create(self, guild_id: int, owner_user_id: int, name: str) -> Playlist:
        playlist = Playlist(self._next_id, guild_id, owner_user_id, name)
        self._next_id += 1
        self.values[playlist.id] = playlist
        return playlist

    async def get(
        self, guild_id: int, owner_user_id: int, name: str
    ) -> Playlist | None:
        for playlist in self.values.values():
            if (
                playlist.guild_id == guild_id
                and playlist.owner_user_id == owner_user_id
                and playlist.name.casefold() == name.casefold()
            ):
                return playlist
        return None

    async def list_for_user(self, guild_id: int, owner_user_id: int) -> list[Playlist]:
        return sorted(
            (
                playlist
                for playlist in self.values.values()
                if playlist.guild_id == guild_id
                and playlist.owner_user_id == owner_user_id
            ),
            key=lambda playlist: playlist.name.casefold(),
        )

    async def delete(self, playlist_id: int) -> None:
        self.values.pop(playlist_id, None)

    async def save_tracks(
        self, playlist_id: int, tracks: list[PlaylistTrack]
    ) -> Playlist:
        playlist = self.values[playlist_id]
        updated = Playlist(
            playlist.id,
            playlist.guild_id,
            playlist.owner_user_id,
            playlist.name,
            tuple(tracks),
        )
        self.values[playlist_id] = updated
        return updated
