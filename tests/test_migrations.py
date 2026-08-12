from __future__ import annotations

import re
from pathlib import Path

import pytest

from peacemusic.infrastructure.persistence.migrations import (
    normalize_alembic_database_url,
)


def test_migration_database_url_uses_asyncpg_dialect() -> None:
    assert (
        normalize_alembic_database_url("postgresql://user:pass@db:5432/app")
        == "postgresql+asyncpg://user:pass@db:5432/app"
    )
    assert (
        normalize_alembic_database_url("postgres://user:pass@db:5432/app")
        == "postgresql+asyncpg://user:pass@db:5432/app"
    )
    assert (
        normalize_alembic_database_url("postgresql+asyncpg://user:pass@db:5432/app")
        == "postgresql+asyncpg://user:pass@db:5432/app"
    )


def test_migration_database_url_rejects_non_postgres_urls() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_alembic_database_url("sqlite:///app.db")


def test_migration_revisions_form_one_linear_chain() -> None:
    versions = Path(__file__).parents[1] / "migrations" / "versions"
    revisions: dict[str, str | None] = {}
    for path in sorted(versions.glob("*.py")):
        source = path.read_text()
        revision = re.search(r'^revision = "([^"]+)"', source, re.MULTILINE)
        down_revision = re.search(
            r'^down_revision = (None|"([^"]+)")', source, re.MULTILINE
        )
        assert revision is not None and down_revision is not None
        revisions[revision.group(1)] = (
            None if down_revision.group(1) == "None" else down_revision.group(2)
        )

    assert len(revisions) == 7
    assert revisions["0001_initial_schema"] is None
    assert revisions["0002_playlist_identity"] == "0001_initial_schema"
    assert revisions["0003_complete_guild_settings"] == "0002_playlist_identity"
    assert revisions["0004_memory_records"] == "0003_complete_guild_settings"
    assert revisions["0005_conversation_messages"] == "0004_memory_records"
    assert revisions["0006_player_messages"] == "0005_conversation_messages"
    assert revisions["0007_guild_ai_system_prompt"] == "0006_player_messages"
