"""Autoplay policy and provider orchestration."""

from __future__ import annotations

from peacemusic.modules.autoplay.models import AutoplayContext
from peacemusic.modules.autoplay.ports import AutoplayProvider
from peacemusic.modules.music.models import Track
from peacemusic.modules.settings.service import GuildSettingsService


class AutoplayService:
    def __init__(
        self,
        provider: AutoplayProvider,
        settings_service: GuildSettingsService,
    ) -> None:
        self._provider = provider
        self._settings = settings_service

    async def next(self, guild_id: int, previous_track: Track) -> Track | None:
        settings = await self._settings.get(guild_id)
        if not settings.music.autoplay_enabled:
            return None
        candidate = await self._provider.get_next(
            AutoplayContext(guild_id=guild_id, previous_track=previous_track)
        )
        if candidate is None or candidate.source_url == previous_track.source_url:
            return None
        return candidate.as_track(requested_by=previous_track.requested_by)
