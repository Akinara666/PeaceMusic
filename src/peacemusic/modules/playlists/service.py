"""Shared playlist operations used by Discord and future agent adapters."""

from __future__ import annotations

from peacemusic.core.errors import ResourceNotFoundError, ValidationError
from peacemusic.modules.music.models import Track
from peacemusic.modules.music.permissions import MusicRequestContext
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.playlists.models import Playlist, PlaylistTrack
from peacemusic.modules.playlists.ports import PlaylistRepository


class PlaylistService:
    def __init__(
        self,
        repository: PlaylistRepository,
        music: MusicService,
        *,
        max_playlist_size: int = 100,
    ) -> None:
        if max_playlist_size < 1:
            raise ValueError("max_playlist_size must be positive")
        self._repository = repository
        self._music = music
        self._max_playlist_size = max_playlist_size

    async def create(self, context: MusicRequestContext, name: str) -> Playlist:
        normalized = self._normalize_name(name)
        if await self._repository.get(context.guild_id, context.user_id, normalized):
            raise ValidationError("A playlist with that name already exists")
        return await self._repository.create(
            context.guild_id, context.user_id, normalized
        )

    async def list(self, context: MusicRequestContext) -> list[Playlist]:
        return await self._repository.list_for_user(context.guild_id, context.user_id)

    async def delete(self, context: MusicRequestContext, name: str) -> None:
        playlist = await self._get(context, name)
        self._ensure_owner(context, playlist)
        await self._repository.delete(playlist.id)

    async def add(
        self, context: MusicRequestContext, name: str, query: str
    ) -> Playlist:
        playlist = await self._get(context, name)
        self._ensure_owner(context, playlist)
        if len(playlist.tracks) >= self._max_playlist_size:
            raise ValidationError("Playlist has reached its maximum size")
        track = await self._music.resolve_track(context, query)
        return await self._repository.save_tracks(
            playlist.id,
            [*playlist.tracks, self._playlist_track(track)],
        )

    async def remove(
        self, context: MusicRequestContext, name: str, index: int
    ) -> PlaylistTrack:
        playlist = await self._get(context, name)
        self._ensure_owner(context, playlist)
        if index < 0 or index >= len(playlist.tracks):
            raise ValidationError("Playlist track index is out of range")
        tracks = list(playlist.tracks)
        removed = tracks.pop(index)
        await self._repository.save_tracks(playlist.id, tracks)
        return removed

    async def play(self, context: MusicRequestContext, name: str) -> int:
        playlist = await self._get(context, name)
        for entry in playlist.tracks:
            await self._music.enqueue_track(
                context, entry.as_track(requested_by=context.user_id)
            )
        return len(playlist.tracks)

    async def get(self, context: MusicRequestContext, name: str) -> Playlist:
        return await self._get(context, name)

    async def _get(self, context: MusicRequestContext, name: str) -> Playlist:
        normalized = self._normalize_name(name)
        playlist = await self._repository.get(
            context.guild_id, context.user_id, normalized
        )
        if playlist is None:
            raise ResourceNotFoundError(f"Playlist not found: {normalized}")
        return playlist

    @staticmethod
    def _ensure_owner(context: MusicRequestContext, playlist: Playlist) -> None:
        if playlist.owner_user_id != context.user_id and not context.can_manage_guild:
            raise ResourceNotFoundError("Playlist not found")

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValidationError("Playlist name cannot be empty")
        if len(normalized) > 100:
            raise ValidationError("Playlist name cannot exceed 100 characters")
        return normalized

    @staticmethod
    def _playlist_track(track: Track) -> PlaylistTrack:
        return PlaylistTrack(
            title=track.title,
            source_url=track.source_url,
            duration=track.duration,
        )
