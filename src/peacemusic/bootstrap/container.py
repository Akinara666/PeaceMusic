"""Dependency composition for the v2 application."""

from __future__ import annotations

from dataclasses import dataclass

from peacemusic.core.config import AppSettings
from peacemusic.core.tasks import TaskSupervisor
from peacemusic.infrastructure.health.server import HealthServer
from peacemusic.infrastructure.persistence.database import PostgresDatabase


@dataclass
class ApplicationContainer:
    """Owned application resources created by one composition root."""

    settings: AppSettings
    database: PostgresDatabase
    tasks: TaskSupervisor
    health: HealthServer

    async def start(self) -> None:
        await self.database.connect()
        await self.health.start()

    async def stop(self) -> None:
        await self.tasks.shutdown()
        await self.health.stop()
        await self.database.close()

    async def is_ready(self) -> bool:
        return await self.database.healthcheck()


def build_container(settings: AppSettings | None = None) -> ApplicationContainer:
    """Build all Stage 1 resources without creating module-level singletons."""

    resolved_settings = settings or AppSettings()
    tasks = TaskSupervisor()
    database = PostgresDatabase(
        resolved_settings.database.url,
        min_size=resolved_settings.database.min_pool_size,
        max_size=resolved_settings.database.max_pool_size,
    )
    health = HealthServer(
        host="0.0.0.0",
        port=resolved_settings.limits.health_server_port,
        readiness_check=lambda: database.healthcheck(),
    )
    return ApplicationContainer(
        settings=resolved_settings,
        database=database,
        tasks=tasks,
        health=health,
    )
