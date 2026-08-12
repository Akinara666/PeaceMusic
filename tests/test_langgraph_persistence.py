from __future__ import annotations

import asyncio
import sys
import types

import pytest

from peacemusic.infrastructure.llm.langgraph_persistence import (
    LangGraphPersistence,
    to_psycopg_database_url,
)


def test_langgraph_database_url_conversion() -> None:
    assert (
        to_psycopg_database_url("postgresql+asyncpg://user:pass@db/app")
        == "postgresql://user:pass@db/app"
    )
    assert to_psycopg_database_url("postgres://user:pass@db/app").startswith(
        "postgres://"
    )
    with pytest.raises(ValueError):
        to_psycopg_database_url("sqlite:///app.db")


def test_langgraph_persistence_owns_setup_and_shutdown(monkeypatch) -> None:
    class FakeContext:
        instances = []

        def __init__(self, url: str) -> None:
            self.url = url
            self.setup_calls = 0
            self.exit_calls = 0
            self.__class__.instances.append(self)

        @classmethod
        def from_conn_string(cls, url: str):
            return cls(url)

        async def __aenter__(self):
            return self

        async def __aexit__(self, _type, _value, _traceback):
            self.exit_calls += 1

        async def setup(self):
            self.setup_calls += 1

    modules = {
        "langgraph": types.ModuleType("langgraph"),
        "langgraph.checkpoint": types.ModuleType("langgraph.checkpoint"),
        "langgraph.checkpoint.postgres": types.ModuleType(
            "langgraph.checkpoint.postgres"
        ),
        "langgraph.checkpoint.postgres.aio": types.ModuleType(
            "langgraph.checkpoint.postgres.aio"
        ),
        "langgraph.store": types.ModuleType("langgraph.store"),
        "langgraph.store.postgres": types.ModuleType("langgraph.store.postgres"),
        "langgraph.store.postgres.aio": types.ModuleType(
            "langgraph.store.postgres.aio"
        ),
    }
    modules["langgraph.checkpoint.postgres.aio"].AsyncPostgresSaver = FakeContext
    modules["langgraph.store.postgres.aio"].AsyncPostgresStore = FakeContext
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    async def scenario() -> None:
        persistence = LangGraphPersistence("postgresql://user:pass@db/app")
        await persistence.start()

        assert persistence.checkpointer is not persistence.store
        assert all(item.setup_calls == 1 for item in FakeContext.instances)
        await persistence.stop()
        assert all(item.exit_calls == 1 for item in FakeContext.instances)

    asyncio.run(scenario())
