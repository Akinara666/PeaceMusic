"""Persistence ports for playlists."""

from __future__ import annotations

from typing import Protocol

from peacemusic.modules.playlists.models import Playlist, PlaylistTrack


class PlaylistRepository(Protocol):
    async def create(self, guild_id: int, owner_user_id: int, name: str) -> Playlist:
        """Create a playlist owned by one user."""

    async def get(
        self, guild_id: int, owner_user_id: int, name: str
    ) -> Playlist | None:
        """Load one playlist owned by the user."""

    async def list_for_user(self, guild_id: int, owner_user_id: int) -> list[Playlist]:
        """List playlists owned by the user in a guild."""

    async def delete(self, playlist_id: int) -> None:
        """Delete a playlist and its tracks."""

    async def save_tracks(
        self, playlist_id: int, tracks: list[PlaylistTrack]
    ) -> Playlist:
        """Replace the ordered track references in a playlist."""
