"""Dependency composition for the v2 application."""

from __future__ import annotations

from dataclasses import dataclass

from peacemusic.core.config import AppSettings
from peacemusic.core.tasks import TaskSupervisor
from peacemusic.infrastructure.health.server import HealthServer
from peacemusic.infrastructure.media.ytdlp import YtDlpMediaResolver
from peacemusic.infrastructure.media.autoplay import ResolverAutoplayProvider
from peacemusic.infrastructure.llm.langchain_agent import LangChainAgentFactory
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.music_tools import build_music_tool_specs
from peacemusic.modules.agent.service import AgentService
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.audit.service import AuditService
from peacemusic.modules.autoplay.service import AutoplayService
from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.infrastructure.persistence.repositories.postgres_audit import (
    PostgresAuditWriter,
    PostgresSettingsAuditWriter,
)
from peacemusic.infrastructure.persistence.repositories.postgres_settings import (
    PostgresGuildSettingsRepository,
)
from peacemusic.infrastructure.persistence.repositories.postgres_playlists import (
    PostgresPlaylistRepository,
)
from peacemusic.infrastructure.persistence.repositories.postgres_history import (
    PostgresPlaybackHistoryRepository,
)
from peacemusic.infrastructure.persistence.repositories.postgres_memory import (
    PostgresMemoryRepository,
)
from peacemusic.adapters.discord.permissions import DiscordMusicPermissionService
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.music.recovery import PlaybackRecoveryService
from peacemusic.modules.playlists.service import PlaylistService
from peacemusic.modules.history.service import PlaybackHistoryService
from peacemusic.modules.memory.service import MemoryService
from peacemusic.modules.settings.service import GuildSettingsService


@dataclass
class ApplicationContainer:
    """Owned application resources created by one composition root."""

    settings: AppSettings
    database: PostgresDatabase
    guild_settings: GuildSettingsService
    music: MusicService
    agent: AgentService
    tasks: TaskSupervisor
    health: HealthServer
    _discord_ready: bool = False
    playlists: PlaylistService | None = None
    history: PlaybackHistoryService | None = None
    memory: MemoryService | None = None

    async def start(self) -> None:
        await self.database.connect()
        await self.health.start()

    async def stop(self) -> None:
        await self.music.shutdown()
        await self.tasks.shutdown()
        await self.health.stop()
        await self.database.close()

    async def is_ready(self) -> bool:
        return self._discord_ready and await self.database.healthcheck()

    def mark_discord_ready(self, ready: bool) -> None:
        self._discord_ready = ready


def build_container(settings: AppSettings | None = None) -> ApplicationContainer:
    """Build all Stage 1 resources without creating module-level singletons."""

    resolved_settings = settings or AppSettings()
    tasks = TaskSupervisor()
    database = PostgresDatabase(
        resolved_settings.database.url,
        min_size=resolved_settings.database.min_pool_size,
        max_size=resolved_settings.database.max_pool_size,
    )
    settings_repository = PostgresGuildSettingsRepository(database)
    settings_audit = PostgresSettingsAuditWriter(database)
    audit = AuditService(PostgresAuditWriter(database))
    guild_settings = GuildSettingsService(
        settings_repository,
        limits=resolved_settings.limits,
        allowed_models=resolved_settings.gemini.allowed_models,
        audit_writer=settings_audit,
    )
    history = PlaybackHistoryService(PostgresPlaybackHistoryRepository(database))
    memory = MemoryService(
        PostgresMemoryRepository(database),
        settings_service=guild_settings,
    )
    media_resolver = YtDlpMediaResolver()
    autoplay = AutoplayService(
        ResolverAutoplayProvider(media_resolver),
        guild_settings,
    )
    music = MusicService(
        GuildPlayerManager(
            default_max_queue_size=resolved_settings.limits.max_queue_size
        ),
        media_resolver,
        DiscordMusicPermissionService(),
        history=history,
        autoplay=autoplay,
        recovery=PlaybackRecoveryService(),
        settings=guild_settings,
        audit=audit,
    )
    playlists = PlaylistService(
        PostgresPlaylistRepository(database),
        music,
    )
    tool_registry = ToolRegistry(build_music_tool_specs(music))
    agent = AgentService(
        settings_service=guild_settings,
        tool_registry=tool_registry,
        agent_factory=LangChainAgentFactory(
            api_key=resolved_settings.gemini.api_key.get_secret_value(),
            model_name=resolved_settings.gemini.response_model,
        ),
        coordinator=TurnCoordinator(
            max_concurrent=resolved_settings.limits.max_concurrent_ai_turns,
        ),
    )
    health = HealthServer(
        host="0.0.0.0",
        port=resolved_settings.limits.health_server_port,
        readiness_check=lambda: False,
    )
    container = ApplicationContainer(
        settings=resolved_settings,
        database=database,
        guild_settings=guild_settings,
        music=music,
        agent=agent,
        tasks=tasks,
        health=health,
        playlists=playlists,
        history=history,
        memory=memory,
    )
    health.set_readiness_check(container.is_ready)
    return container
