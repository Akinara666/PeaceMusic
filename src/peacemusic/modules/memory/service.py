"""Authorization and lifecycle boundary for long-term memory operations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.modules.memory.models import MemoryKind, MemoryRecord
from peacemusic.modules.memory.namespaces import channel_namespace, user_namespace
from peacemusic.modules.memory.ports import MemoryRepository
from peacemusic.modules.settings.service import GuildSettingsService


class MemoryService:
    def __init__(
        self,
        repository: MemoryRepository,
        *,
        settings_service: GuildSettingsService,
    ) -> None:
        self._repository = repository
        self._settings = settings_service

    async def remember(
        self,
        *,
        guild_id: int,
        user_id: int,
        content: str,
        scope: str = "user",
        kind: MemoryKind = MemoryKind.SEMANTIC,
        channel_id: int | None = None,
    ) -> MemoryRecord:
        settings = await self._settings.get(guild_id)
        if not settings.memory.enabled or not settings.memory.long_term_memory_enabled:
            raise PermissionDeniedError("Long-term memory is disabled")
        namespace = self._namespace(guild_id, user_id, scope, channel_id)
        record = MemoryRecord(
            memory_id=uuid4().hex,
            namespace=namespace,
            kind=kind,
            content=content,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.put(record)
        return record

    async def recall(
        self,
        *,
        guild_id: int,
        user_id: int,
        query: str,
        scope: str = "user",
        kind: MemoryKind | None = None,
        limit: int = 5,
        channel_id: int | None = None,
    ) -> Sequence[MemoryRecord]:
        if limit < 1:
            raise ValidationError("Memory recall limit must be positive")
        settings = await self._settings.get(guild_id)
        if not settings.memory.enabled or not settings.memory.long_term_memory_enabled:
            return ()
        return await self._repository.search(
            self._namespace(guild_id, user_id, scope, channel_id),
            query,
            kind=kind,
            limit=limit,
        )

    async def forget(
        self,
        *,
        guild_id: int,
        user_id: int,
        scope: str = "user",
        memory_id: str | None = None,
        channel_id: int | None = None,
    ) -> int:
        settings = await self._settings.get(guild_id)
        if not settings.memory.enabled:
            raise PermissionDeniedError("Long-term memory is disabled")
        return await self._repository.delete(
            self._namespace(guild_id, user_id, scope, channel_id), memory_id=memory_id
        )

    @staticmethod
    def _namespace(
        guild_id: int, user_id: int, scope: str, channel_id: int | None
    ) -> tuple[str, ...]:
        if scope == "user":
            return user_namespace(guild_id, user_id)
        if scope == "channel":
            if channel_id is None:
                raise ValidationError("channel_id is required for channel memory")
            return channel_namespace(guild_id, channel_id)
        raise ValidationError("Memory scope must be user or channel")
