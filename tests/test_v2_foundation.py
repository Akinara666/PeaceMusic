from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import pytest

from peacemusic.core.config import AppSettings
from peacemusic.core.tasks import TaskSupervisor
from peacemusic.infrastructure.health.server import HealthServer
from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.bootstrap.container import ApplicationContainer


def test_app_settings_reads_operator_environment() -> None:
    env = {
        "DISCORD_BOT_TOKEN": "discord-secret",
        "GOOGLE_API_KEY": "gemini-secret",
        "DATABASE_URL": "postgresql://localhost/test",
        "ALLOWED_AI_MODELS": '["gemini-test"]',
        "GEMINI_RESPONSE_MODEL": "gemini-test",
        "GLOBAL_MAX_QUEUE_SIZE": "25",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = AppSettings()

    assert settings.discord.token.get_secret_value() == "discord-secret"
    assert settings.gemini.api_key.get_secret_value() == "gemini-secret"
    assert settings.database.url == "postgresql://localhost/test"
    assert settings.gemini.allowed_models == ("gemini-test",)
    assert settings.limits.max_queue_size == 25


def test_app_settings_rejects_model_outside_operator_allowlist() -> None:
    env = {
        "DISCORD_BOT_TOKEN": "discord-secret",
        "GOOGLE_API_KEY": "gemini-secret",
        "ALLOWED_AI_MODELS": '["gemini-safe"]',
        "GEMINI_RESPONSE_MODEL": "gemini-untrusted",
    }

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="ALLOWED_AI_MODELS"):
            AppSettings()


def test_task_supervisor_cancels_owned_tasks() -> None:
    async def scenario() -> None:
        supervisor = TaskSupervisor()
        finished = asyncio.Event()

        async def worker() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        supervisor.start(worker(), name="test-worker")
        await asyncio.sleep(0)
        assert supervisor.active_count == 1

        await supervisor.shutdown()

        assert finished.is_set()
        assert supervisor.active_count == 0

    asyncio.run(scenario())


def test_health_server_reports_live_ready_and_metrics() -> None:
    async def scenario() -> None:
        server = HealthServer(
            host="127.0.0.1",
            port=18080,
            readiness_check=lambda: True,
            metrics_provider=lambda: "peacemusic_test_metric 1\n",
        )

        live = await server._live(None)  # type: ignore[arg-type]
        ready = await server._ready(None)  # type: ignore[arg-type]
        metrics = await server._metrics(None)  # type: ignore[arg-type]

        assert live.status == 200
        assert json.loads(live.text) == {"status": "ok"}
        assert ready.status == 200
        assert json.loads(ready.text) == {"status": "ready"}
        assert metrics.text == "peacemusic_test_metric 1\n"

    asyncio.run(scenario())


def test_database_is_not_ready_before_connecting() -> None:
    async def scenario() -> None:
        database = PostgresDatabase(
            "postgresql://localhost/test", min_size=1, max_size=1
        )

        assert database.connected is False
        assert await database.healthcheck() is False
        await database.close()

    asyncio.run(scenario())


def test_container_readiness_requires_discord_and_database() -> None:
    class HealthyDatabase:
        async def healthcheck(self) -> bool:
            return True

        async def close(self) -> None:
            pass

        async def connect(self) -> None:
            pass

    async def scenario() -> None:
        container = ApplicationContainer(
            settings=object(),  # type: ignore[arg-type]
            database=HealthyDatabase(),  # type: ignore[arg-type]
            guild_settings=object(),  # type: ignore[arg-type]
            music=object(),  # type: ignore[arg-type]
            tasks=TaskSupervisor(),
            health=object(),  # type: ignore[arg-type]
        )

        assert await container.is_ready() is False
        container.mark_discord_ready(True)
        assert await container.is_ready() is True

    asyncio.run(scenario())
