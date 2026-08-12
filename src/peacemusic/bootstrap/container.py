"""Dependency composition for the v2 application."""

from __future__ import annotations

from dataclasses import dataclass

from peacemusic.core.config import AppSettings
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.core.tasks import TaskSupervisor
from peacemusic.infrastructure.health.server import HealthServer
from peacemusic.infrastructure.attachments.downloader import HttpAttachmentDownloader
from peacemusic.infrastructure.llm.gemini_files import GeminiFilesAdapter
from peacemusic.infrastructure.llm.langgraph_persistence import LangGraphPersistence
from peacemusic.infrastructure.media.ytdlp import YtDlpMediaResolver
from peacemusic.infrastructure.media.autoplay import ResolverAutoplayProvider
from peacemusic.infrastructure.llm.langchain_agent import LangChainAgentFactory
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.limits import UserRateLimiter
from peacemusic.modules.agent.memory_tools import build_memory_tool_specs
from peacemusic.modules.agent.music_context import music_context
from peacemusic.modules.agent.music_tools import build_music_tool_specs
from peacemusic.modules.agent.service import AgentService
from peacemusic.modules.access.service import AccessControlService
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.attachments.service import AttachmentService
from peacemusic.modules.attachments.workflow import AttachmentProviderWorkflow
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
from peacemusic.infrastructure.persistence.repositories.postgres_player_messages import (
    PostgresPlayerMessageRepository,
)
from peacemusic.infrastructure.persistence.repositories.langgraph_memory import (
    LangGraphMemoryRepository,
)
from peacemusic.infrastructure.persistence.repositories.postgres_conversation import (
    PostgresConversationRepository,
)
from peacemusic.infrastructure.persistence.repositories.postgres_dj_roles import (
    PostgresDJRoleRepository,
)
from peacemusic.infrastructure.persistence.repositories.postgres_access import (
    PostgresAccessControlRepository,
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
    dj_roles: PostgresDJRoleRepository | None = None
    playlists: PlaylistService | None = None
    history: PlaybackHistoryService | None = None
    memory: MemoryService | None = None
    metrics: MetricsRegistry | None = None
    conversation: PostgresConversationRepository | None = None
    langgraph: LangGraphPersistence | None = None
    agent_factory: LangChainAgentFactory | None = None
    player_messages: PostgresPlayerMessageRepository | None = None
    access: AccessControlService | None = None

    async def start(self) -> None:
        await self.database.connect()
        if self.langgraph is not None and self.agent_factory is not None:
            await self.langgraph.start()
            self.agent_factory.attach_persistence(
                checkpointer=self.langgraph.checkpointer,
                store=self.langgraph.store,
            )
        await self.health.start()

    async def stop(self) -> None:
        await self.music.shutdown()
        await self.tasks.shutdown()
        await self.health.stop()
        if self.langgraph is not None:
            await self.langgraph.stop()
        await self.database.close()

    async def is_ready(self) -> bool:
        return self._discord_ready and await self.database.healthcheck()

    def mark_discord_ready(self, ready: bool) -> None:
        self._discord_ready = ready


def build_container(settings: AppSettings | None = None) -> ApplicationContainer:
    """Build all Stage 1 resources without creating module-level singletons."""

    resolved_settings = settings or AppSettings()
    tasks = TaskSupervisor()
    metrics = MetricsRegistry()
    rate_limiter = UserRateLimiter()
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
        default_system_prompt=resolved_settings.gemini.system_prompt,
        audit_writer=settings_audit,
    )
    dj_roles = PostgresDJRoleRepository(database)
    access = AccessControlService(
        PostgresAccessControlRepository(database), audit=audit
    )
    history = PlaybackHistoryService(PostgresPlaybackHistoryRepository(database))
    conversation = PostgresConversationRepository(database)
    player_messages = PostgresPlayerMessageRepository(database)
    langgraph = LangGraphPersistence(
        resolved_settings.database.url,
        embedding_api_key=resolved_settings.gemini.api_key.get_secret_value(),
    )
    attachment_workflow = AttachmentProviderWorkflow(
        AttachmentService(
            max_bytes=resolved_settings.limits.max_download_size_mb * 1024 * 1024
        ),
        GeminiFilesAdapter(api_key=resolved_settings.gemini.api_key.get_secret_value()),
        downloader=HttpAttachmentDownloader(),
    )
    memory = MemoryService(
        LangGraphMemoryRepository(langgraph),
        settings_service=guild_settings,
        metrics=metrics,
    )
    media_resolver = YtDlpMediaResolver(metrics=metrics)
    autoplay = AutoplayService(
        ResolverAutoplayProvider(media_resolver),
        guild_settings,
    )
    music = MusicService(
        GuildPlayerManager(
            default_max_queue_size=resolved_settings.limits.max_queue_size
        ),
        media_resolver,
        DiscordMusicPermissionService(dj_roles),
        history=history,
        autoplay=autoplay,
        recovery=PlaybackRecoveryService(metrics=metrics),
        settings=guild_settings,
        audit=audit,
        metrics=metrics,
    )
    playlists = PlaylistService(
        PostgresPlaylistRepository(database),
        music,
    )
    tool_registry = ToolRegistry(
        (*build_music_tool_specs(music), *build_memory_tool_specs(memory))
    )
    agent_factory = LangChainAgentFactory(
        api_key=resolved_settings.gemini.api_key.get_secret_value(),
        model_name=resolved_settings.gemini.response_model,
    )
    agent = AgentService(
        settings_service=guild_settings,
        tool_registry=tool_registry,
        agent_factory=agent_factory,
        coordinator=TurnCoordinator(
            max_concurrent=resolved_settings.limits.max_concurrent_ai_turns,
        ),
        metrics=metrics,
        conversation_repository=conversation,
        rate_limiter=rate_limiter,
        attachment_preparer=attachment_workflow,
        direct_audio_handler=lambda context, attachment: music.play_direct_audio(
            music_context(context),
            title=attachment.filename,
            url=attachment.url or "",
        ),
    )
    health = HealthServer(
        host="0.0.0.0",
        port=resolved_settings.limits.health_server_port,
        readiness_check=lambda: False,
        metrics_provider=metrics.render,
    )
    container = ApplicationContainer(
        settings=resolved_settings,
        database=database,
        guild_settings=guild_settings,
        dj_roles=dj_roles,
        music=music,
        agent=agent,
        tasks=tasks,
        health=health,
        playlists=playlists,
        history=history,
        memory=memory,
        metrics=metrics,
        conversation=conversation,
        langgraph=langgraph,
        agent_factory=agent_factory,
        player_messages=player_messages,
        access=access,
    )
    health.set_readiness_check(container.is_ready)
    return container
