"""Application service for cached, authorized guild configuration changes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from peacemusic.core.config import DEFAULT_AGENT_SYSTEM_PROMPT, GlobalLimits
from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.modules.settings.defaults import default_guild_settings
from peacemusic.modules.settings.models import GuildSettings
from peacemusic.modules.settings.ports import (
    GuildSettingsRepository,
    SettingsAuditWriter,
    SettingsAuthorizer,
)


class GuildSettingsService:
    """Single access point for effective guild configuration."""

    def __init__(
        self,
        repository: GuildSettingsRepository,
        *,
        limits: GlobalLimits | None = None,
        allowed_models: tuple[str, ...] = ("gemini-3.1-flash-lite",),
        default_system_prompt: str = DEFAULT_AGENT_SYSTEM_PROMPT,
        authorizer: SettingsAuthorizer | None = None,
        audit_writer: SettingsAuditWriter | None = None,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        if cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds cannot be negative")
        if not allowed_models:
            raise ValueError("allowed_models cannot be empty")
        self._repository = repository
        self._limits = limits or GlobalLimits()
        self._allowed_models = allowed_models
        self._default_system_prompt = default_system_prompt
        self._authorizer = authorizer
        self._audit_writer = audit_writer
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[int, tuple[float, GuildSettings]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def get(self, guild_id: int) -> GuildSettings:
        self._validate_guild_id(guild_id)
        now = time.monotonic()
        cached = self._cache.get(guild_id)
        if cached is not None and now - cached[0] < self._cache_ttl_seconds:
            return cached[1].model_copy(deep=True)

        settings = await self._repository.get(guild_id)
        if settings is None:
            settings = default_guild_settings(
                guild_id,
                limits=self._limits,
                allowed_models=self._allowed_models,
                default_system_prompt=self._default_system_prompt,
            )
            await self._repository.save(settings)
        settings = self._validate_effective(settings)
        self._cache[guild_id] = (now, settings)
        return settings.model_copy(deep=True)

    async def update(
        self,
        guild_id: int,
        *,
        actor_user_id: int,
        section: str,
        values: Mapping[str, Any],
    ) -> GuildSettings:
        """Authorize and atomically update one settings section."""

        self._validate_guild_id(guild_id)
        if (
            self._authorizer is not None
            and not await self._authorizer.can_manage_settings(guild_id, actor_user_id)
        ):
            raise PermissionDeniedError("User cannot manage guild settings")

        if section not in {"general", "music", "voice", "ai", "memory"}:
            raise ValidationError(f"Unknown guild settings section: {section}")

        lock = self._locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            current = await self.get(guild_id)
            section_model = getattr(current, section).model_copy(update=dict(values))
            candidate = GuildSettings.model_validate(
                current.model_copy(update={section: section_model}).model_dump()
            )
            candidate = self._validate_effective(candidate)
            await self._repository.save(candidate)
            self._cache[guild_id] = (time.monotonic(), candidate)

            if self._audit_writer is not None:
                changed = {f"{section}.{key}": value for key, value in values.items()}
                await self._audit_writer.record_settings_change(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    changes=changed,
                    recorded_at=datetime.now(timezone.utc),
                )
            return candidate.model_copy(deep=True)

    def invalidate(self, guild_id: int) -> None:
        self._cache.pop(guild_id, None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    def set_authorizer(self, authorizer: SettingsAuthorizer) -> None:
        """Attach the runtime adapter used to authorize future mutations."""

        self._authorizer = authorizer

    def _validate_effective(self, settings: GuildSettings) -> GuildSettings:
        if settings.music.max_queue_size > self._limits.max_queue_size:
            raise ValidationError("max_queue_size exceeds the global safety limit")
        if settings.ai.model not in self._allowed_models:
            raise ValidationError("ai.model is not in the operator allowlist")
        return settings

    @staticmethod
    def _validate_guild_id(guild_id: int) -> None:
        if guild_id <= 0:
            raise ValidationError("guild_id must be positive")
