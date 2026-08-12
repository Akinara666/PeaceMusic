"""Ports used by the guild settings application service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from peacemusic.modules.settings.models import GuildSettings


class GuildSettingsRepository(Protocol):
    async def get(self, guild_id: int) -> GuildSettings | None:
        """Load settings for a guild, if persisted."""

    async def save(self, settings: GuildSettings) -> None:
        """Insert or replace settings for a guild."""


class SettingsAuditWriter(Protocol):
    async def record_settings_change(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        changes: Mapping[str, object],
        recorded_at: datetime,
    ) -> None:
        """Persist an auditable settings change."""


class SettingsAuthorizer(Protocol):
    async def can_manage_settings(self, guild_id: int, user_id: int) -> bool:
        """Return whether the caller may change guild settings."""
