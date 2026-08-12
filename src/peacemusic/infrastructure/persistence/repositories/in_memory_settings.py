"""Deterministic settings repository for unit tests and local composition."""

from __future__ import annotations

from peacemusic.modules.settings.models import GuildSettings


class InMemoryGuildSettingsRepository:
    def __init__(self) -> None:
        self.values: dict[int, GuildSettings] = {}

    async def get(self, guild_id: int) -> GuildSettings | None:
        settings = self.values.get(guild_id)
        return settings.model_copy(deep=True) if settings is not None else None

    async def save(self, settings: GuildSettings) -> None:
        self.values[settings.guild_id] = settings.model_copy(deep=True)


class InMemorySettingsAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def record_settings_change(self, **event: object) -> None:
        self.events.append(event)
